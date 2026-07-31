"""Headless Agent trace runner for VS Code (filesystem-backed, desktop-aligned).

Requires an LLM API key. Walks a tool-calling loop that reads paper/code evidence,
validates quotes, and progressively appends to `.tracelab/traces/links.json`.
Static keyword matching is NOT used as the primary path.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import httpx

from tracelab_core.progress import emit_progress
from tracelab_core.review import load_links, save_links
from tracelab_core.workspace import TraceLabPaths, append_job_log, read_json

ProgressFn = Callable[[str, str], None]

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_paper_blocks",
            "description": "List paper blocks (id, kind, page, text preview) for tracing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "offset": {"type": "integer"},
                    "limit": {"type": "integer"},
                    "query": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_paper_block",
            "description": "Get full text of a paper block by id.",
            "parameters": {
                "type": "object",
                "properties": {"block_id": {"type": "string"}},
                "required": ["block_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_symbols",
            "description": "List code symbols (id, path, name, lines).",
            "parameters": {
                "type": "object",
                "properties": {
                    "offset": {"type": "integer"},
                    "limit": {"type": "integer"},
                    "query": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_symbol_source",
            "description": "Read source for a symbol_id (path::Name).",
            "parameters": {
                "type": "object",
                "properties": {"symbol_id": {"type": "string"}},
                "required": ["symbol_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_source_lines",
            "description": "Read a workspace-relative source file by line range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "line_start": {"type": "integer"},
                    "line_end": {"type": "integer"},
                },
                "required": ["path", "line_start", "line_end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_repository_text",
            "description": "Search Python sources for a text query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "publish_trace_candidates",
            "description": (
                "Publish validated paper↔code trace candidates. Each item needs "
                "paper_block_id, paper_quote, code_path, code_line_start, code_line_end, "
                "code_quote, relation_type, confidence, rationale."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "candidates": {
                        "type": "array",
                        "items": {"type": "object"},
                    }
                },
                "required": ["candidates"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish_analysis",
            "description": "Finish the trace analysis run.",
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
            },
        },
    },
]

SYSTEM_PROMPT = """你是 TraceLab 论文↔代码追溯 Agent。
目标：为论文中的方法/公式/模块找到对应的代码实现，并发布带双侧精确证据的追溯关系。

规则：
1. 先用 list_paper_blocks / list_symbols 侦察，再 read_source_lines / get_symbol_source / get_paper_block 取证。
2. 每条关系必须有 paper_quote（出现在论文块原文）和 code_quote（出现在指定代码行范围内）。
3. 不要编造 block_id / path / 行号；不确定就继续读代码。
4. 分批 publish_trace_candidates；完成后调用 finish_analysis。
5. 优先覆盖模型结构、注意力、损失、训练步骤等高价值内容。
"""


def _activity(tool: str, args: dict[str, Any]) -> str:
    if tool == "read_source_lines":
        return f"阅读代码 {args.get('path')}:{args.get('line_start')}"
    if tool == "get_symbol_source":
        return f"阅读符号 {args.get('symbol_id')}"
    if tool == "get_paper_block":
        return f"阅读论文块 {args.get('block_id')}"
    if tool == "list_paper_blocks":
        return "侦察论文块"
    if tool == "list_symbols":
        return "侦察代码符号"
    if tool == "search_repository_text":
        return f"搜索代码 `{args.get('query', '')[:40]}`"
    if tool == "publish_trace_candidates":
        n = len(args.get("candidates") or [])
        return f"发布候选 {n} 条"
    if tool == "finish_analysis":
        return "结束分析"
    return f"调用工具 {tool}"


def _fingerprint(link: dict[str, Any]) -> str:
    paper = link.get("paper_target") or {}
    code = link.get("code_target") or {}
    raw = "|".join(
        [
            str(paper.get("block_id", "")),
            str(paper.get("quote", ""))[:200],
            str(code.get("path", "")),
            str(code.get("line_start", "")),
            str(code.get("quote", ""))[:200],
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _quote_in_text(haystack: str, quote: str) -> bool:
    q = (quote or "").strip()
    if len(q) < 6:
        return False
    if q in haystack:
        return True
    # Tolerate whitespace / $ drift between markdown and plain text.
    compact = re.sub(r"\s+", "", haystack)
    needle = re.sub(r"\s+", "", q)
    return len(needle) >= 6 and needle in compact


class WorkspaceTraceContext:
    def __init__(self, paths: TraceLabPaths) -> None:
        self.paths = paths
        self.workspace = paths.root.parent  # .tracelab -> workspace root
        self.paper_doc = read_json(paths.paper_document_json, {}) or {}
        self.normalized = read_json(paths.normalized_json, {}) or {}
        self.symbols: list[dict[str, Any]] = list(read_json(paths.symbols_json, []) or [])
        self.markdown = ""
        if paths.document_md.is_file():
            self.markdown = paths.document_md.read_text(encoding="utf-8", errors="replace")
        elif self.paper_doc.get("markdown"):
            self.markdown = str(self.paper_doc["markdown"])
        self.blocks = list(self.paper_doc.get("blocks") or [])
        if not self.blocks:
            # Fallback: paragraphs from normalized.json
            for paragraph in self.normalized.get("paragraphs") or []:
                self.blocks.append(
                    {
                        "id": paragraph.get("id"),
                        "text": paragraph.get("text", ""),
                        "kind": "paragraph",
                        "page": paragraph.get("page", 1),
                    }
                )
        self.block_by_id = {str(b.get("id")): b for b in self.blocks if b.get("id")}
        self.symbol_by_id = {str(s.get("id")): s for s in self.symbols if s.get("id")}
        self.published = 0
        self.rejected = 0
        self.finished = False
        self.job_events: list[dict[str, Any]] = []

    def tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "list_paper_blocks":
            return self._list_paper_blocks(args)
        if name == "get_paper_block":
            return self._get_paper_block(str(args.get("block_id", "")))
        if name == "list_symbols":
            return self._list_symbols(args)
        if name == "get_symbol_source":
            return self._get_symbol_source(str(args.get("symbol_id", "")))
        if name == "read_source_lines":
            return self._read_source_lines(
                str(args.get("path", "")),
                int(args.get("line_start") or 1),
                int(args.get("line_end") or 1),
            )
        if name == "search_repository_text":
            return self._search_repo(str(args.get("query", "")), int(args.get("limit") or 20))
        if name == "publish_trace_candidates":
            return self._publish(list(args.get("candidates") or []))
        if name == "finish_analysis":
            self.finished = True
            return {"ok": True, "summary": args.get("summary", ""), "published": self.published}
        return {"ok": False, "error": f"unknown_tool:{name}"}

    def _list_paper_blocks(self, args: dict[str, Any]) -> dict[str, Any]:
        offset = max(0, int(args.get("offset") or 0))
        limit = min(40, max(1, int(args.get("limit") or 20)))
        query = str(args.get("query") or "").strip().lower()
        items = []
        for block in self.blocks:
            text = str(block.get("text") or "")
            if query and query not in text.lower() and query not in str(block.get("id", "")).lower():
                continue
            items.append(
                {
                    "id": block.get("id"),
                    "kind": block.get("kind") or block.get("type"),
                    "page": block.get("page") or block.get("page_number"),
                    "preview": text[:240],
                }
            )
        slice_ = items[offset : offset + limit]
        return {"ok": True, "total": len(items), "offset": offset, "items": slice_}

    def _get_paper_block(self, block_id: str) -> dict[str, Any]:
        block = self.block_by_id.get(block_id)
        if not block:
            return {"ok": False, "error": "block_not_found", "block_id": block_id}
        return {"ok": True, "block": block}

    def _list_symbols(self, args: dict[str, Any]) -> dict[str, Any]:
        offset = max(0, int(args.get("offset") or 0))
        limit = min(60, max(1, int(args.get("limit") or 30)))
        query = str(args.get("query") or "").strip().lower()
        items = []
        for symbol in self.symbols:
            blob = " ".join(
                str(symbol.get(k, ""))
                for k in ("id", "name", "qualified_name", "path", "kind")
            ).lower()
            if query and query not in blob:
                continue
            items.append(
                {
                    "id": symbol.get("id"),
                    "path": symbol.get("path"),
                    "name": symbol.get("name") or symbol.get("qualified_name"),
                    "kind": symbol.get("kind"),
                    "line_start": symbol.get("line_start") or symbol.get("lineno"),
                    "line_end": symbol.get("line_end") or symbol.get("end_lineno"),
                }
            )
        return {
            "ok": True,
            "total": len(items),
            "offset": offset,
            "items": items[offset : offset + limit],
        }

    def _resolve_path(self, rel: str) -> Path | None:
        rel = rel.lstrip("./")
        candidate = (self.workspace / rel).resolve()
        try:
            candidate.relative_to(self.workspace.resolve())
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def _read_source_lines(self, rel: str, start: int, end: int) -> dict[str, Any]:
        path = self._resolve_path(rel)
        if not path:
            return {"ok": False, "error": "file_not_found", "path": rel}
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, start)
        end = min(len(lines), max(start, end))
        excerpt = "\n".join(
            f"{i}|{lines[i - 1]}" for i in range(start, end + 1)
        )
        return {
            "ok": True,
            "path": rel,
            "line_start": start,
            "line_end": end,
            "content": excerpt[:12000],
        }

    def _get_symbol_source(self, symbol_id: str) -> dict[str, Any]:
        symbol = self.symbol_by_id.get(symbol_id)
        if not symbol:
            # Try path::name fuzzy
            for sid, item in self.symbol_by_id.items():
                if sid.endswith(symbol_id) or symbol_id in sid:
                    symbol = item
                    symbol_id = sid
                    break
        if not symbol:
            return {"ok": False, "error": "symbol_not_found", "symbol_id": symbol_id}
        start = int(symbol.get("line_start") or symbol.get("lineno") or 1)
        end = int(symbol.get("line_end") or symbol.get("end_lineno") or start + 40)
        result = self._read_source_lines(str(symbol.get("path", "")), start, end)
        result["symbol_id"] = symbol_id
        return result

    def _search_repo(self, query: str, limit: int) -> dict[str, Any]:
        if not query.strip():
            return {"ok": False, "error": "empty_query"}
        hits: list[dict[str, Any]] = []
        for path in self.workspace.rglob("*.py"):
            if ".tracelab" in path.parts or ".venv" in path.parts or "node_modules" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if query not in text:
                continue
            rel = path.relative_to(self.workspace).as_posix()
            for i, line in enumerate(text.splitlines(), start=1):
                if query in line:
                    hits.append({"path": rel, "line": i, "text": line.strip()[:200]})
                    if len(hits) >= limit:
                        return {"ok": True, "hits": hits}
        return {"ok": True, "hits": hits}

    def _publish(self, candidates: list[Any]) -> dict[str, Any]:
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        existing = load_links(self.paths)
        seen = {_fingerprint(link) for link in existing}

        for raw in candidates:
            if not isinstance(raw, dict):
                rejected.append({"reason": "not_object"})
                continue
            block_id = str(raw.get("paper_block_id") or raw.get("block_id") or "")
            paper_quote = str(raw.get("paper_quote") or "")
            code_path = str(raw.get("code_path") or raw.get("path") or "")
            line_start = int(raw.get("code_line_start") or raw.get("line_start") or 1)
            line_end = int(raw.get("code_line_end") or raw.get("line_end") or line_start)
            code_quote = str(raw.get("code_quote") or "")
            symbol_id = str(raw.get("code_symbol_id") or raw.get("symbol_id") or "")

            block = self.block_by_id.get(block_id)
            if not block:
                rejected.append({"reason": "unknown_block", "block_id": block_id})
                continue
            block_text = str(block.get("text") or "")
            if not (
                _quote_in_text(block_text, paper_quote)
                or _quote_in_text(self.markdown, paper_quote)
            ):
                rejected.append({"reason": "paper_quote_mismatch", "block_id": block_id})
                continue

            path = self._resolve_path(code_path)
            if not path and symbol_id and symbol_id in self.symbol_by_id:
                code_path = str(self.symbol_by_id[symbol_id].get("path") or "")
                path = self._resolve_path(code_path)
                line_start = int(
                    self.symbol_by_id[symbol_id].get("line_start")
                    or self.symbol_by_id[symbol_id].get("lineno")
                    or line_start
                )
                line_end = int(
                    self.symbol_by_id[symbol_id].get("line_end")
                    or self.symbol_by_id[symbol_id].get("end_lineno")
                    or line_end
                )
            if not path:
                rejected.append({"reason": "code_path_missing", "path": code_path})
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            start = max(1, line_start)
            end = min(len(lines), max(start, line_end))
            window = "\n".join(lines[start - 1 : end])
            # Expand window slightly for quote match.
            wider = "\n".join(lines[max(0, start - 6) : min(len(lines), end + 6)])
            if not (_quote_in_text(window, code_quote) or _quote_in_text(wider, code_quote)):
                rejected.append(
                    {
                        "reason": "code_quote_mismatch",
                        "path": code_path,
                        "line_start": start,
                        "line_end": end,
                    }
                )
                continue

            link = {
                "id": str(uuid.uuid4()),
                "status": "proposed",
                "source": "agent",
                "relation_type": str(raw.get("relation_type") or "implements"),
                "confidence": float(raw.get("confidence") or 0.7),
                "rationale": str(raw.get("rationale") or ""),
                "fingerprint": "",
                "paper_target": {"block_id": block_id, "quote": paper_quote},
                "code_target": {
                    "symbol_id": symbol_id,
                    "path": code_path,
                    "line_start": start,
                    "line_end": end,
                    "quote": code_quote,
                },
            }
            link["fingerprint"] = _fingerprint(link)
            if link["fingerprint"] in seen:
                rejected.append({"reason": "duplicate", "fingerprint": link["fingerprint"]})
                continue
            seen.add(link["fingerprint"])
            accepted.append(link)

        if accepted:
            existing.extend(accepted)
            save_links(self.paths, existing)
            self.published += len(accepted)
            emit_progress(
                "publish",
                f"已发布 {len(accepted)} 条（累计 {self.published}）",
                published=self.published,
                event_kind="analysis.published",
            )
        self.rejected += len(rejected)
        return {
            "ok": True,
            "accepted": len(accepted),
            "rejected": len(rejected),
            "rejected_samples": rejected[:8],
            "published_total": self.published,
        }


def _chat(
    client: httpx.Client,
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    thinking_mode: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "temperature": 0,
        "messages": messages,
        "tools": TOOL_DEFINITIONS,
        "tool_choice": "auto",
        "max_tokens": 8192,
    }
    if thinking_mode in {"enabled", "disabled"}:
        payload["thinking"] = {"type": thinking_mode}
    response = client.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
    )
    if response.status_code in {400, 422}:
        # JSON-action fallback when native tools unsupported.
        catalog = [
            {"name": t["function"]["name"], "description": t["function"]["description"]}
            for t in TOOL_DEFINITIONS
        ]
        fallback_messages = list(messages)
        fallback_messages.insert(
            1,
            {
                "role": "system",
                "content": (
                    "Native tools unavailable. Return JSON: "
                    '{"action":"tool","tool_name":"...","arguments":{}} or '
                    '{"action":"final","answer":"..."}. Tools: '
                    + json.dumps(catalog, ensure_ascii=False)
                ),
            },
        )
        fallback = {
            "model": model,
            "temperature": 0,
            "messages": fallback_messages,
            "max_tokens": 8192,
        }
        response = client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=fallback,
        )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]


def run_agent_trace(
    paths: TraceLabPaths,
    *,
    llm_config: dict[str, Any],
    max_steps: int = 48,
    replace: bool = False,
) -> dict[str, Any]:
    if not llm_config or not llm_config.get("enabled") or not llm_config.get("api_key"):
        raise RuntimeError(
            "Agent 追溯需要已配置的 LLM API Key。请在侧栏保存密钥后再运行「生成追溯」。"
        )
    if not paths.normalized_json.is_file() and not paths.paper_document_json.is_file():
        raise FileNotFoundError("论文未解析；请先运行「解析论文」。")
    if not paths.symbols_json.is_file():
        raise FileNotFoundError("代码未分析；请先运行「分析代码」。")

    if replace:
        save_links(paths, [])
        emit_progress("agent", "已清空既有追溯，开始重新生成")

    ctx = WorkspaceTraceContext(paths)
    emit_progress("agent", "启动 Agent 追溯（多步取证）")
    base_url = str(llm_config.get("base_url", "")).rstrip("/")
    api_key = str(llm_config.get("api_key", ""))
    model = str(llm_config.get("model") or "deepseek-chat")
    timeout = float(llm_config.get("timeout_seconds") or 180)
    thinking_mode = str(llm_config.get("thinking_mode") or "")

    user_brief = (
        f"工作区已加载：论文 blocks={len(ctx.blocks)}，符号={len(ctx.symbols)}，"
        f"markdown_chars={len(ctx.markdown)}。"
        "请开始侦察并发布高质量追溯关系。"
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_brief},
    ]

    started = time.monotonic()
    steps = 0
    with httpx.Client(timeout=timeout) as client:
        while steps < max_steps and not ctx.finished:
            steps += 1
            emit_progress("agent", f"Agent 步骤 {steps}/{max_steps}", current=steps, total=max_steps)
            message = _chat(
                client,
                base_url=base_url,
                api_key=api_key,
                model=model,
                messages=messages,
                thinking_mode=thinking_mode,
            )
            tool_calls = message.get("tool_calls") or []
            content = str(message.get("content") or "").strip()

            if tool_calls:
                messages.append(message)
                for call in tool_calls:
                    function = call.get("function") or {}
                    name = str(function.get("name") or "")
                    try:
                        args = json.loads(function.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    if not isinstance(args, dict):
                        args = {}
                    activity = _activity(name, args)
                    emit_progress("tool", activity, tool=name, step=steps)
                    ctx.job_events.append({"step": steps, "tool": name, "activity": activity})
                    result = ctx.tool(name, args)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id") or name,
                            "content": json.dumps(result, ensure_ascii=False)[:16000],
                        }
                    )
                continue

            # JSON-action fallback
            if content.startswith("{"):
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict) and parsed.get("action") == "tool":
                    name = str(parsed.get("tool_name") or "")
                    args = parsed.get("arguments") if isinstance(parsed.get("arguments"), dict) else {}
                    activity = _activity(name, args)
                    emit_progress("tool", activity, tool=name, step=steps)
                    result = ctx.tool(name, args)
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": json.dumps(
                                {"tool_result": {"name": name, "result": result}},
                                ensure_ascii=False,
                            )[:16000],
                        }
                    )
                    continue
                if isinstance(parsed, dict) and parsed.get("action") == "final":
                    ctx.finished = True
                    emit_progress("agent", f"Agent 结束：{str(parsed.get('answer') or '')[:120]}")
                    break

            # Plain final text
            if content:
                messages.append({"role": "assistant", "content": content})
                if ctx.published > 0:
                    ctx.finished = True
                    emit_progress("agent", "Agent 以文本收尾")
                    break
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "请继续使用工具取证并 publish_trace_candidates；"
                            "若已完成请调用 finish_analysis。"
                        ),
                    }
                )
                continue

            messages.append(
                {
                    "role": "user",
                    "content": "请调用工具继续，或 finish_analysis。",
                }
            )

    elapsed_ms = int((time.monotonic() - started) * 1000)
    links = load_links(paths)
    append_job_log(
        paths,
        "agent-trace",
        {
            "source": "agent",
            "steps": steps,
            "published": ctx.published,
            "rejected": ctx.rejected,
            "elapsed_ms": elapsed_ms,
            "finished": ctx.finished,
            "events": ctx.job_events[-80:],
            "total_links": len(links),
        },
    )
    emit_progress(
        "save",
        f"Agent 追溯完成：新增 {ctx.published}，总计 {len(links)}，耗时 {elapsed_ms}ms",
    )
    return {
        "created": ctx.published,
        "total": len(links),
        "source": "agent",
        "static_count": 0,
        "llm_count": ctx.published,
        "steps": steps,
        "rejected": ctx.rejected,
        "elapsed_ms": elapsed_ms,
        "finished": ctx.finished,
    }
