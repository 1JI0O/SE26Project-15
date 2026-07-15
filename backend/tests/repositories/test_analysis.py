import zipfile
from pathlib import Path

import pytest

from app.services.code_analysis.analyzer import analyze_code_archive
from app.services.code_analysis.archive import InvalidCodeArchiveError
from app.services.code_analysis.editor import save_repository_file


def _write_zip(path: Path, entries: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for filename, content in entries.items():
            archive.writestr(filename, content)


def test_repository_filtering_uses_git_exclude_and_build_defaults(tmp_path: Path) -> None:
    archive_path = tmp_path / "repository.zip"
    _write_zip(
        archive_path,
        {
            "sample/.git/info/exclude": "private.py\n",
            "sample/.gitignore": "generated/\n",
            "sample/model.py": "def model():\n    return 1\n",
            "sample/private.py": "SECRET = True\n",
            "sample/generated/code.py": "VALUE = 1\n",
            "sample/node_modules/pkg/index.js": "module.exports = {}\n",
            "sample/.venv/lib/site.py": "VALUE = 1\n",
            "sample/dist/bundle.js": "compiled\n",
        },
    )

    analysis = analyze_code_archive(archive_path)

    assert {entry["path"] for entry in analysis["file_tree"]} == {
        ".gitignore",
        "model.py",
    }
    assert analysis["archive_root"] == "sample"
    assert analysis["summary"]["ignored_count"] == 6


def test_gitignore_priority_is_independent_of_zip_member_order(tmp_path: Path) -> None:
    archive_path = tmp_path / "repository.zip"
    _write_zip(
        archive_path,
        {
            "sample/.gitignore": "!keep.py\n",
            "sample/.git/info/exclude": "*.py\n",
            "sample/keep.py": "VALUE = 1\n",
            "sample/drop.py": "VALUE = 2\n",
        },
    )

    analysis = analyze_code_archive(archive_path)

    paths = {entry["path"] for entry in analysis["file_tree"]}
    assert "keep.py" in paths
    assert "drop.py" not in paths


def test_python_symbols_and_calls_have_stable_locations(tmp_path: Path) -> None:
    archive_path = tmp_path / "repository.zip"
    _write_zip(
        archive_path,
        {
            "sample/models/block.py": (
                "import torch.nn as nn\n\n"
                "class Block(nn.Module):\n"
                "    def forward(self, x):\n"
                "        return self.conv(x)\n"
            )
        },
    )

    analysis = analyze_code_archive(archive_path)

    method = next(symbol for symbol in analysis["symbols"] if symbol["kind"] == "method")
    assert method == {
        "id": "models/block.py::Block.forward",
        "kind": "method",
        "type": "method",
        "name": "forward",
        "path": "models/block.py",
        "line": 4,
        "line_start": 4,
        "line_end": 5,
        "qualified_name": "Block.forward",
        "args": ["self", "x"],
        "is_async": False,
    }
    call = next(item for item in analysis["calls"] if item["callee"] == "self.conv")
    assert call["caller_symbol_id"] == method["id"]
    assert call["path"] == "models/block.py"
    assert call["line_start"] == call["line_end"] == 5


def test_tensor_graph_contains_branch_residual_merge_and_concat(tmp_path: Path) -> None:
    archive_path = tmp_path / "repository.zip"
    _write_zip(
        archive_path,
        {
            "sample/block.py": (
                "import torch\n"
                "import torch.nn as nn\n\n"
                "class Block(nn.Module):\n"
                "    def forward(self, x):\n"
                "        identity = x\n"
                "        out = self.conv(x)\n"
                "        if self.proj is not None:\n"
                "            identity = self.proj(x)\n"
                "        out += identity\n"
                "        return torch.cat([out, x], dim=1)\n"
            )
        },
    )

    graph = analyze_code_archive(archive_path)["tensor_graph"]

    operations = {node["op"] for node in graph["nodes"]}
    assert {"branch", "branch_merge", "add", "concatenate", "return"} <= operations
    assert any(edge["kind"] == "residual" for edge in graph["edges"])
    assert all(node["source_path"] == "block.py" for node in graph["nodes"])
    assert all(node["line_start"] >= 5 for node in graph["nodes"])
    assert all(node["shape"] is None and node["shape_reason"] for node in graph["nodes"])


def test_architecture_graph_selects_main_model_and_keeps_debug_graph(tmp_path: Path) -> None:
    archive_path = tmp_path / "repository.zip"
    _write_zip(
        archive_path,
        {
            "sample/models/model.py": (
                "import torch.nn as nn\n\n"
                "class Encoder(nn.Module):\n"
                "    def __init__(self):\n"
                "        super().__init__()\n"
                "        self.conv = nn.Conv2d(3, 16, 3)\n"
                "    def forward(self, x):\n"
                "        return self.conv(x)\n\n"
                "class Model(nn.Module):\n"
                "    def __init__(self):\n"
                "        super().__init__()\n"
                "        self.encoder = Encoder()\n"
                "        self.head = nn.Linear(16, 4)\n"
                "    def forward(self, images):\n"
                "        features = self.encoder(images)\n"
                "        return self.head(features)\n\n"
                "class TrainingLoss(nn.Module):\n"
                "    def forward(self, prediction, target):\n"
                "        return prediction + target\n"
            )
        },
    )

    analysis = analyze_code_archive(archive_path)
    architecture = analysis["architecture_graph"]
    graph = architecture["graphs"][architecture["default_root"]]

    assert architecture["default_root"] == "models/model.py::Model"
    assert [node["label"] for node in graph["nodes"]] == [
        "Images",
        "Encoder",
        "Head",
        "Output",
    ]
    encoder = next(node for node in graph["nodes"] if node["label"] == "Encoder")
    assert encoder["metadata"]["expandable"] is True
    assert encoder["metadata"]["component_symbol_id"] == "models/model.py::Encoder"
    assert all("Loss" not in root["label"] for root in architecture["roots"])
    assert any(node["op"] == "add" for node in analysis["tensor_graph"]["nodes"])


def test_analysis_uses_saved_edit_overlay(tmp_path: Path) -> None:
    archive_path = tmp_path / "repository.zip"
    edits_root = tmp_path / "edits"
    _write_zip(
        archive_path,
        {
            "repo/model.py": (
                "import torch.nn as nn\n\n"
                "class Model(nn.Module):\n"
                "    def forward(self, x):\n"
                "        return x + x\n"
            )
        },
    )
    save_repository_file(
        archive_path,
        edits_root,
        "model.py",
        (
            "import torch.nn as nn\n\n"
            "class Model(nn.Module):\n"
            "    def forward(self, x):\n"
            "        return x * x\n"
        ),
    )

    graph = analyze_code_archive(archive_path, edits_root=edits_root)["tensor_graph"]

    assert any(node["op"] == "multiply" for node in graph["nodes"])
    assert not any(node["op"] == "add" for node in graph["nodes"])


def test_duplicate_archive_paths_are_rejected(tmp_path: Path) -> None:
    archive_path = tmp_path / "repository.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("repo/model.py", "VALUE = 1\n")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("repo/model.py", "VALUE = 2\n")

    with pytest.raises(InvalidCodeArchiveError, match="duplicate path"):
        analyze_code_archive(archive_path)
