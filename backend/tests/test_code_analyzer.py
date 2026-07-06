import zipfile
from pathlib import Path

from app.services.code_analyzer import analyze_code_archive


def _write_zip(path: Path, entries: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for filename, content in entries.items():
            archive.writestr(filename, content)


def test_analyze_code_archive_respects_gitignore_and_macos_artifacts(tmp_path: Path) -> None:
    archive_path = tmp_path / "repo.zip"
    _write_zip(
        archive_path,
        {
            "repo/.gitignore": "ignored.py\nbuild/\n*.pyc\n",
            "repo/model.py": (
                "import torch.nn as nn\n\n"
                "class Net(nn.Module):\n"
                "    def forward(self, x):\n"
                "        return x\n"
            ),
            "repo/ignored.py": "def ignored():\n    return None\n",
            "repo/build/generated.py": "def generated():\n    return None\n",
            "repo/cache.pyc": "compiled",
            "repo/.DS_Store": "finder metadata",
            "repo/._model.py": "appledouble metadata",
            "__MACOSX/repo/model.py": "resource fork",
            "MACOS_junk/noise.py": "def noise():\n    return None\n",
        },
    )

    analysis = analyze_code_archive(archive_path)

    paths = {item["path"] for item in analysis["file_tree"]}
    assert "repo/model.py" in paths
    assert "repo/.gitignore" in paths
    assert "repo/ignored.py" not in paths
    assert "repo/build/generated.py" not in paths
    assert "repo/cache.pyc" not in paths
    assert "repo/.DS_Store" not in paths
    assert "repo/._model.py" not in paths
    assert "__MACOSX/repo/model.py" not in paths
    assert "MACOS_junk/noise.py" not in paths
    assert {item["name"] for item in analysis["pytorch_candidates"]} == {"Net"}
