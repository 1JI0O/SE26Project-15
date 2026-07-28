from __future__ import annotations

import asyncio
import json
import stat
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.code_analysis import analyzer as analyzer_module
from app.services.code_analysis import archive as archive_module
from app.services.code_analysis import definition_resolve as definitions
from app.services.code_analysis import editor as editor_module
from app.services.code_analysis import ignore_rules, lsp_bridge
from app.services.code_analysis.archive import InvalidCodeArchiveError
from app.services.code_analysis.definition_resolve import CallableSymbol, DefinitionIndex
from app.services.code_analysis.editor import (
    FileNotEditableError,
    FileTooLargeError,
    InvalidRepositoryPathError,
)
from app.services.code_analysis.languages import language_for
from app.services.code_analysis.python_ast import analyze_python
from app.services.code_analysis.tree import build_hierarchical_tree


def _write_zip(path: Path, entries: dict[str, str | bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


def _symbol(
    path: str,
    name: str,
    *,
    kind: str = "function",
    qualified_name: str | None = None,
    symbol_id: str | None = None,
) -> dict[str, Any]:
    qualified = qualified_name or name
    return {
        "id": symbol_id or f"{path}::{qualified}",
        "kind": kind,
        "name": name,
        "path": path,
        "qualified_name": qualified,
        "line_start": 2,
        "line_end": 4,
    }


def _caller(path: str = "caller.py", *, owner: str | None = None) -> CallableSymbol:
    return CallableSymbol(
        symbol_id=f"{path}::caller",
        path=path,
        name="caller",
        line_start=1,
        line_end=5,
        owner_symbol_id=owner,
    )


def test_archive_rejects_limits_and_skips_unsafe_members(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "unsafe.zip"
    symlink = zipfile.ZipInfo("repo/link.py")
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("repo/ok.py", "x = 1")
        archive.writestr("../escape.py", "bad")
        archive.writestr("repo/folder/", "")
        archive.writestr(symlink, "ok.py")

    with zipfile.ZipFile(archive_path) as archive:
        assert [item.filename for item in archive_module.safe_members(archive)] == ["repo/ok.py"]

    monkeypatch.setattr(archive_module, "MAX_ARCHIVE_FILES", 1)
    with zipfile.ZipFile(archive_path) as archive, pytest.raises(
        InvalidCodeArchiveError, match="more than 1 entries"
    ):
        archive_module.safe_members(archive)

    single_path = tmp_path / "large.zip"
    _write_zip(single_path, {"repo/large.py": "12"})
    monkeypatch.setattr(archive_module, "MAX_ARCHIVE_FILES", 20_000)
    monkeypatch.setattr(archive_module, "MAX_ARCHIVE_UNCOMPRESSED_BYTES", 1)
    with zipfile.ZipFile(single_path) as archive, pytest.raises(
        InvalidCodeArchiveError, match="uncompressed size"
    ):
        archive_module.safe_members(archive)

    assert archive_module.common_top_folder([]) == ""


def test_oversized_ignore_file_is_ignored_as_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "ignore.zip"
    _write_zip(archive_path, {"repo/.gitignore": "*.py\n", "repo/kept.py": "x = 1"})
    monkeypatch.setattr(ignore_rules, "MAX_SOURCE_BYTES", 2)

    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        specs = ignore_rules.build_ignore_specs(archive, members)

    assert not ignore_rules.is_ignored(Path("repo/kept.py"), specs)  # type: ignore[arg-type]


def test_editor_rejects_non_utf8_types_and_oversized_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "repo.zip"
    _write_zip(
        archive_path,
        {
            "repo/model.py": b"\xff",
            "repo/image.png": b"image",
        },
    )

    with pytest.raises(FileNotEditableError, match="valid UTF-8"):
        editor_module.read_repository_file(archive_path, "model.py")
    with pytest.raises(FileNotEditableError, match="File type"):
        editor_module.read_repository_file(archive_path, "image.png")
    with pytest.raises(FileNotEditableError, match="File type"):
        editor_module.save_repository_file(archive_path, tmp_path / "edits", "image.png", "x")

    monkeypatch.setattr(editor_module, "MAX_SOURCE_BYTES", 0)
    with pytest.raises(FileTooLargeError, match="editor limit"):
        editor_module.read_repository_file(archive_path, "model.py")


def test_editor_rejects_unsafe_overlay_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "repo.zip"
    _write_zip(archive_path, {"repo/model.py": "x = 1"})

    fake_parent = SimpleNamespace(mkdir=lambda **_kwargs: None)
    fake_target = SimpleNamespace(is_symlink=lambda: True, parents=[], parent=fake_parent)
    monkeypatch.setattr(editor_module, "_safe_edit_target", lambda *_args: fake_target)
    with pytest.raises(InvalidRepositoryPathError, match="Symbolic links"):
        editor_module.read_repository_file(
            archive_path,
            "model.py",
            edits_root=tmp_path / "edits",
        )
    with pytest.raises(InvalidRepositoryPathError, match="Symbolic links"):
        editor_module.save_repository_file(
            archive_path,
            tmp_path / "edits",
            "model.py",
            "x = 2",
        )


def test_editor_rejects_oversized_saved_overlay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "repo.zip"
    edits_root = tmp_path / "edits"
    _write_zip(archive_path, {"repo/model.py": "x"})
    edited = edits_root / "model.py"
    edited.parent.mkdir(parents=True)
    edited.write_text("xx", encoding="utf-8")
    monkeypatch.setattr(editor_module, "MAX_SOURCE_BYTES", 1)

    with pytest.raises(FileTooLargeError, match="Edited file"):
        editor_module.read_repository_file(archive_path, "model.py", edits_root=edits_root)


def test_scan_count_languages_and_empty_tree(tmp_path: Path) -> None:
    archive_path = tmp_path / "repo.zip"
    _write_zip(
        archive_path,
        {
            "repo/main.py": "x = 1",
            "repo/README.md": "docs",
            "repo/config.yaml": "enabled: true",
            "repo/data.bin": b"\x00",
            "repo/.git/hidden.py": "ignored = True",
        },
    )

    scan = analyzer_module.scan_code_archive(archive_path)

    assert scan["summary"]["python_file_count"] == 1
    assert analyzer_module.count_filtered_files(archive_path) == 1
    assert language_for("README.md") == "docs"
    assert language_for("config.yaml") == "config"
    assert language_for("weights.bin") == "binary"
    assert language_for("script.sh") == "other"
    assert build_hierarchical_tree([]) == []


def test_analysis_falls_back_to_archive_when_overlay_is_unreadable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "repo.zip"
    _write_zip(archive_path, {"repo/model.py": "def original():\n    return 1\n"})

    def reject_overlay(*_args: Any, **_kwargs: Any) -> str:
        raise editor_module.FileAccessError("bad overlay")

    monkeypatch.setattr(editor_module, "read_repository_file", reject_overlay)
    result = analyzer_module.analyze_code_archive(archive_path, edits_root=tmp_path / "edits")

    assert any(item["name"] == "original" for item in result["symbols"])


def test_python_ast_handles_async_functions_and_syntax_errors() -> None:
    valid = analyze_python("worker.py", "async def run(x):\n    return await x()\n")
    assert valid.symbols[0]["is_async"] is True
    assert valid.calls[0]["callee"] == "x"

    invalid = analyze_python("broken.py", "def broken(:\n")
    assert invalid.tree is None
    assert invalid.symbols[0]["kind"] == "parse_error"


def test_definition_index_resolves_self_dynamic_and_ambiguous_calls() -> None:
    owner = "model.py::Model"
    symbols = [
        _symbol("model.py", "Model", kind="class"),
        _symbol("model.py", "run", kind="method", qualified_name="Model.run"),
        _symbol("model.py", "missing_owner", kind="method", qualified_name="Model.helper"),
        _symbol("a.py", "duplicate"),
        _symbol("b.py", "duplicate"),
        _symbol("a.py", "Widget", kind="class"),
        _symbol("b.py", "Widget", kind="class"),
        {"id": "ignored", "kind": "variable", "name": "x", "path": "a.py"},
        {"id": "", "kind": "function", "name": "bad", "path": "a.py"},
    ]
    index = DefinitionIndex(symbols, {})

    assert index.resolve(_caller(owner=owner), "self.run").status == "resolved"
    missing_method = index.resolve(_caller(owner=owner), "self.unknown")
    assert missing_method.reason == "当前类中找不到唯一方法 self.unknown"
    assert index.resolve(_caller(), "self.run").reason == "无法解析 self 调用"
    assert index.resolve(_caller(), "dynamic_call").reason == "调用目标由运行时表达式决定"
    assert index.resolve(_caller(), "duplicate").status == "ambiguous"
    assert index.resolve(_caller(), "Widget").status == "ambiguous"
    assert index.resolve(_caller(), "absent").status == "unresolved"


def test_definition_index_resolves_imported_and_global_symbols() -> None:
    symbols = [
        _symbol("pkg/tools.py", "helper"),
        _symbol("other.py", "unique"),
        _symbol("pkg/model.py", "Model", kind="class"),
    ]
    index = DefinitionIndex(
        symbols,
        {"caller.py": {"alias": "pkg.tools.helper", "Model": "pkg.model.Model"}},
    )
    caller = _caller()

    assert index.canonical_callee("caller.py", "plain") == "plain"
    assert index.resolve(caller, "alias").symbol_id == "pkg/tools.py::helper"
    assert index.resolve(caller, "unique").symbol_id == "other.py::unique"
    assert index.resolve(caller, "Model").symbol_id == "pkg/model.py::Model"
    assert index.resolve_identifier("caller.py", "alias").status == "resolved"
    assert index.resolve_identifier("caller.py", "Model").status == "resolved"
    assert index.resolve_identifier("caller.py", "unique").status == "resolved"
    assert index.resolve_identifier("caller.py", "").reason == "标识符为空"
    assert index.resolve_identifier("caller.py", "absent").status == "unresolved"


def test_definition_index_reports_import_and_same_file_ambiguity() -> None:
    first = _symbol("pkg/tool.py", "run", symbol_id="pkg/tool.py::run-one")
    second = _symbol("pkg/tool.py", "run", symbol_id="pkg/tool.py::run-two")
    classes = [
        _symbol("a.py", "Model", kind="class"),
        _symbol("b.py", "Model", kind="class"),
    ]
    index = DefinitionIndex(
        [first, second, *classes],
        {"caller.py": {"run": "pkg.tool.run"}},
    )

    assert index.resolve(_caller("pkg/tool.py"), "run").status == "ambiguous"
    assert index.resolve(_caller(), "run").reason == "项目中存在多个导入目标 pkg.tool.run"
    assert index.resolve_identifier("caller.py", "run").status == "ambiguous"
    assert index.resolve_identifier("caller.py", "Model").status == "ambiguous"


def test_definition_helpers_cover_fallbacks_and_identifier_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SimpleNamespace(
        analysis_json={},
        symbols_json=[_symbol("valid.py", "target")],
        imports_json=[],
        storage_path="unused.zip",
    )
    payload = definitions._analysis_payload(repository)
    assert payload["calls"] == []

    sources = {
        "valid.py": "from pkg import thing\n",
        "broken.py": "def broken(:\n",
        "missing.py": None,
    }
    monkeypatch.setattr(
        definitions,
        "read_archive_file",
        lambda _storage, path, **_kwargs: sources.get(path),
    )
    imports = definitions._build_imports_by_path(
        repository,
        edits_root=None,
        paths={"README.md", "valid.py", "broken.py", "missing.py"},
    )
    assert imports == {"valid.py": {"thing": "pkg.thing"}}

    calls = [{"path": "a.py", "line_start": 2, "column_start": 3, "column_end": 7}]
    assert definitions._find_call_at(calls, path="a.py", line=2, column=4) is calls[0]
    assert definitions._find_call_at(calls, path="a.py", line=3, column=4) is None
    assert definitions._extract_identifier("", 0) is None
    assert definitions._extract_identifier("call pkg.tool.run now", 15) == "pkg.tool.run"
    assert definitions._extract_identifier("no symbol here", 99) is None


def test_resolve_definition_rejects_unsupported_or_unanalysed_files() -> None:
    empty = SimpleNamespace(
        analysis_json={},
        symbols_json=[],
        imports_json=[],
        storage_path="unused.zip",
    )
    unsupported = definitions.resolve_definition(
        empty,
        path="README.md",
        line=1,
        column=0,
        identifier=None,
        edits_root=None,
    )
    pending = definitions.resolve_definition(
        empty,
        path="main.py",
        line=1,
        column=0,
        identifier=None,
        edits_root=None,
    )

    assert unsupported.reason == "仅支持 Python 文件"
    assert pending.reason == "仓库尚未完成静态分析"


def test_lsp_decoder_handles_partial_and_invalid_frames() -> None:
    partial_header = bytearray(b"Content-Length: 2\r\n")
    assert lsp_bridge.decode_lsp_messages(partial_header) == ([], partial_header)

    partial_body = bytearray(b"Content-Length: 4\r\n\r\n{}")
    assert lsp_bridge.decode_lsp_messages(partial_body) == ([], partial_body)

    invalid = bytearray(b"Other: value\r\n\r\nbody")
    messages, remaining = lsp_bridge.decode_lsp_messages(invalid)
    assert messages == []
    assert remaining == bytearray()


def test_basedpyright_command_prefers_installed_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lsp_bridge.shutil, "which", lambda _name: "C:/bin/basedpyright.exe")
    assert lsp_bridge.basedpyright_command() == ["C:/bin/basedpyright.exe", "--stdio"]
    monkeypatch.setattr(lsp_bridge.shutil, "which", lambda _name: None)
    assert lsp_bridge.basedpyright_command()[1:] == ["-m", "basedpyright.langserver", "--stdio"]


class _FakeStdin:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.drained = False

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        self.drained = True


class _FakeStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    async def read(self, _size: int = -1) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""


class _FakeProcess:
    def __init__(self, *, returncode: int | None = None, timeout_once: bool = False) -> None:
        self.returncode = returncode
        self.stdin = _FakeStdin()
        self.stdout = _FakeStream([])
        self.stderr = _FakeStream([])
        self.timeout_once = timeout_once
        self.wait_calls = 0
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        self.wait_calls += 1
        if self.timeout_once and self.wait_calls == 1:
            raise TimeoutError
        self.returncode = -9 if self.killed else (self.returncode or 0)
        return self.returncode


def test_lsp_session_io_and_close_paths(tmp_path: Path) -> None:
    async def scenario() -> None:
        process = _FakeProcess(timeout_once=True)
        session = lsp_bridge.LspBridgeSession(1, tmp_path, process)  # type: ignore[arg-type]
        await session.write_stdin('{"jsonrpc":"2.0"}')
        assert process.stdin.writes and process.stdin.drained

        process.stdout = _FakeStream([lsp_bridge.encode_lsp_message("{}"), b""])
        assert await session.read_stdout_messages() == ["{}"]
        assert await session.read_stdout_messages() == []
        session.closed = False
        await session.close()
        assert process.terminated and process.killed
        await session.close()

        closed = lsp_bridge.LspBridgeSession(2, tmp_path, process, closed=True)  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="stdin"):
            await closed.write_stdin("{}")
        assert await closed.read_stdout_messages() == []

    asyncio.run(scenario())


def test_start_lsp_session_replaces_previous_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        previous = SimpleNamespace(closed=False)

        async def close_previous() -> None:
            previous.closed = True

        previous.close = close_previous
        process = _FakeProcess()

        async def create_process(*args: Any, **kwargs: Any) -> _FakeProcess:
            assert args
            assert kwargs["cwd"] == str(tmp_path)
            return process

        monkeypatch.setattr(lsp_bridge, "_active_sessions", {7: previous})
        monkeypatch.setattr(lsp_bridge, "basedpyright_command", lambda: ["language-server"])
        monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)

        session = await lsp_bridge.start_lsp_session(7, tmp_path)
        assert previous.closed is True
        assert session.process is process
        assert lsp_bridge._active_sessions[7] is session

    asyncio.run(scenario())


def test_lsp_pumps_and_process_error_notification(tmp_path: Path) -> None:
    async def scenario() -> None:
        received = iter(["one", None])

        async def receive() -> str | None:
            return next(received)

        written: list[str] = []
        ws_session = SimpleNamespace(closed=False)

        async def write(message: str) -> None:
            written.append(message)

        ws_session.write_stdin = write
        await lsp_bridge._pump_ws_to_lsp(ws_session, receive)
        assert written == ["one"] and ws_session.closed is True

        sent: list[str] = []

        async def send(message: str) -> None:
            sent.append(message)

        process = _FakeProcess(returncode=0)
        output_session = SimpleNamespace(closed=False, process=process)
        batches = iter([["first", "second"], []])

        async def read_messages() -> list[str]:
            result = next(batches)
            if not result:
                process.returncode = 0
            return result

        output_session.read_stdout_messages = read_messages
        await lsp_bridge._pump_lsp_to_ws(output_session, send)
        assert sent == ["first", "second"] and output_session.closed is True

        failed = _FakeProcess(returncode=3)
        failed.stderr = _FakeStream([b"failure detail"])
        watched = SimpleNamespace(closed=False, process=failed)
        await lsp_bridge._watch_process(watched, send)
        assert watched.closed is True
        notice = json.loads(sent[-1])
        assert "failure detail" in notice["params"]["message"]

        clean = _FakeProcess(returncode=0)
        await lsp_bridge._watch_process(SimpleNamespace(closed=False, process=clean), send)

    asyncio.run(scenario())


def test_run_websocket_bridge_closes_and_calls_hook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        closed: list[str] = []
        session = SimpleNamespace(closed=False)

        async def close() -> None:
            session.closed = True
            closed.append("session")

        session.close = close

        async def start(_project_id: int, _workspace_root: Path) -> Any:
            return session

        async def no_op(*_args: Any) -> None:
            return None

        async def receive() -> str | None:
            return None

        async def send(_message: str) -> None:
            return None

        async def on_close() -> None:
            closed.append("hook")

        monkeypatch.setattr(lsp_bridge, "_active_sessions", {9: session})
        monkeypatch.setattr(lsp_bridge, "start_lsp_session", start)
        monkeypatch.setattr(lsp_bridge, "_pump_ws_to_lsp", no_op)
        monkeypatch.setattr(lsp_bridge, "_pump_lsp_to_ws", no_op)
        monkeypatch.setattr(lsp_bridge, "_watch_process", no_op)

        await lsp_bridge.run_websocket_bridge(
            project_id=9,
            workspace_root=tmp_path,
            receive_text=receive,
            send_text=send,
            on_close=on_close,
        )
        assert closed == ["session", "hook"]
        assert 9 not in lsp_bridge._active_sessions

    asyncio.run(scenario())
