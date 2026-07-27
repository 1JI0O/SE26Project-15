"""WebSocket ↔ basedpyright stdio bridge for Desktop LSP."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

# Per-project active bridges; a new connection replaces the previous one.
_active_sessions: dict[int, LspBridgeSession] = {}


def encode_lsp_message(payload: str | dict) -> bytes:
    body = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"))
    encoded = body.encode("utf-8")
    header = f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii")
    return header + encoded


def decode_lsp_messages(buffer: bytearray) -> tuple[list[str], bytearray]:
    messages: list[str] = []
    while True:
        header_end = buffer.find(b"\r\n\r\n")
        if header_end < 0:
            break
        header = buffer[:header_end].decode("ascii", errors="replace")
        content_length = 0
        for line in header.split("\r\n"):
            if line.lower().startswith("content-length:"):
                content_length = int(line.split(":", 1)[1].strip())
                break
        if content_length <= 0:
            buffer.clear()
            break
        body_start = header_end + 4
        body_end = body_start + content_length
        if len(buffer) < body_end:
            break
        messages.append(buffer[body_start:body_end].decode("utf-8"))
        del buffer[:body_end]
    return messages, buffer


def basedpyright_command() -> list[str]:
    executable = shutil.which("basedpyright-langserver")
    if executable:
        return [executable, "--stdio"]
    return [sys.executable, "-m", "basedpyright.langserver", "--stdio"]


@dataclass
class LspBridgeSession:
    project_id: int
    workspace_root: Path
    process: asyncio.subprocess.Process
    stdout_buffer: bytearray = field(default_factory=bytearray)
    closed: bool = False

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=2)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()

    async def write_stdin(self, message: str) -> None:
        if self.process.stdin is None or self.closed:
            raise RuntimeError("LSP process stdin is unavailable")
        self.process.stdin.write(encode_lsp_message(message))
        await self.process.stdin.drain()

    async def read_stdout_messages(self) -> list[str]:
        if self.process.stdout is None or self.closed:
            return []
        chunk = await self.process.stdout.read(4096)
        if not chunk:
            self.closed = True
            return []
        self.stdout_buffer.extend(chunk)
        messages, self.stdout_buffer = decode_lsp_messages(self.stdout_buffer)
        return messages


async def start_lsp_session(project_id: int, workspace_root: Path) -> LspBridgeSession:
    previous = _active_sessions.pop(project_id, None)
    if previous is not None:
        await previous.close()

    command = basedpyright_command()
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(workspace_root),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    session = LspBridgeSession(
        project_id=project_id,
        workspace_root=workspace_root,
        process=process,
    )
    _active_sessions[project_id] = session
    return session


async def run_websocket_bridge(
    *,
    project_id: int,
    workspace_root: Path,
    receive_text: Callable[[], Awaitable[str | None]],
    send_text: Callable[[str], Awaitable[None]],
    on_close: Callable[[], Awaitable[None]] | None = None,
) -> None:
    session = await start_lsp_session(project_id, workspace_root)
    try:
        await asyncio.gather(
            _pump_ws_to_lsp(session, receive_text),
            _pump_lsp_to_ws(session, send_text),
            _watch_process(session, send_text),
        )
    finally:
        await session.close()
        if _active_sessions.get(project_id) is session:
            _active_sessions.pop(project_id, None)
        if on_close is not None:
            await on_close()


async def _pump_ws_to_lsp(
    session: LspBridgeSession,
    receive_text: Callable[[], Awaitable[str | None]],
) -> None:
    while not session.closed:
        message = await receive_text()
        if message is None:
            session.closed = True
            return
        await session.write_stdin(message)


async def _pump_lsp_to_ws(
    session: LspBridgeSession,
    send_text: Callable[[str], Awaitable[None]],
) -> None:
    while not session.closed:
        messages = await session.read_stdout_messages()
        if not messages and session.process.returncode is not None:
            session.closed = True
            return
        for message in messages:
            await send_text(message)
        if not messages:
            await asyncio.sleep(0.01)


async def _watch_process(
    session: LspBridgeSession,
    send_text: Callable[[str], Awaitable[None]],
) -> None:
    returncode = await session.process.wait()
    session.closed = True
    if returncode not in (0, None):
        detail = "basedpyright 语言服务异常退出"
        if session.process.stderr is not None:
            stderr = (await session.process.stderr.read()).decode("utf-8", errors="replace").strip()
            if stderr:
                detail = f"{detail}: {stderr[:300]}"
        await send_text(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "window/showMessage",
                    "params": {"type": 1, "message": detail},
                }
            )
        )
