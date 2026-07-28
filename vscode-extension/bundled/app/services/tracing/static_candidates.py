from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*|[\u4e00-\u9fff]{2,}")
CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "into",
    "using",
    "class",
    "function",
    "method",
    "model",
    "module",
    "paper",
    "code",
}


@dataclass(frozen=True)
class StaticCandidate:
    candidate_id: str
    paper_block_id: str
    code_symbol_id: str
    relation_type: str
    confidence: float
    rationale: str
    evidence: list[dict[str, str]]
    paper_text: str
    code_text: str


def _tokens(value: str) -> set[str]:
    expanded = CAMEL_RE.sub(" ", value.replace("_", " ").replace("/", " "))
    return {
        token.lower()
        for token in TOKEN_RE.findall(expanded)
        if len(token) > 1 and token.lower() not in STOPWORDS
    }


def _overlap(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))


def _paper_blocks(
    sections: list[dict[str, Any]], paragraphs: list[dict[str, Any]]
) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    for index, paragraph in enumerate(paragraphs):
        text = str(paragraph.get("text", "")).strip()
        if text:
            blocks.append(
                {
                    "id": str(paragraph.get("id") or f"paragraph:{index + 1}"),
                    "text": text,
                    "section": " / ".join(paragraph.get("section_path", [])),
                }
            )
    if blocks:
        return blocks
    for index, section in enumerate(sections):
        title = str(section.get("title", "")).strip()
        if title:
            blocks.append({"id": f"section:{index + 1}", "text": title, "section": title})
    return blocks


def _symbol_id(symbol: dict[str, Any]) -> str:
    if symbol.get("id"):
        return str(symbol["id"])
    path = str(symbol.get("path", ""))
    qualified = str(symbol.get("qualified_name") or symbol.get("name", ""))
    return f"{path}::{qualified}" if path else qualified


def _symbol_text(symbol: dict[str, Any]) -> tuple[str, str, str, str]:
    path = str(symbol.get("path", ""))
    qualified = str(symbol.get("qualified_name") or symbol.get("name", ""))
    signature = str(symbol.get("signature", ""))
    comments = " ".join(
        str(value) for value in (symbol.get("docstring", ""), symbol.get("comments", "")) if value
    )
    calls_value = symbol.get("calls", [])
    calls = " ".join(
        str(call.get("name", "")) if isinstance(call, dict) else str(call) for call in calls_value
    )
    display = " ".join(part for part in (qualified, signature, comments, calls, path) if part)
    line_start = int(symbol.get("line_start") or symbol.get("line") or 1)
    line_end = int(symbol.get("line_end") or line_start)
    ref = f"{path}:{line_start}-{line_end}" if path else qualified
    quote = " ".join(part for part in (signature, comments) if part) or qualified or path
    return display, comments, calls, f"{ref}\n{quote[:1000]}"


def generate_static_candidates(
    sections: list[dict[str, Any]],
    paragraphs: list[dict[str, Any]],
    symbols: list[dict[str, Any]],
    pytorch_candidates: list[dict[str, Any]] | None = None,
    tensor_graph: dict[str, Any] | None = None,
    *,
    limit: int = 30,
) -> list[StaticCandidate]:
    blocks = _paper_blocks(sections, paragraphs)
    if not blocks or not symbols:
        return []
    pytorch_keys = {
        (str(item.get("path", "")), str(item.get("name", "")))
        for item in (pytorch_candidates or [])
    }
    tensor_symbols = {
        str(node.get("symbol_id", ""))
        for node in (tensor_graph or {}).get("nodes", [])
        if node.get("symbol_id")
    }
    ranked: list[StaticCandidate] = []
    for block in blocks[:80]:
        paper_text = block["text"]
        section_text = block["section"]
        for symbol in symbols[:500]:
            symbol_id = _symbol_id(symbol)
            if not symbol_id:
                continue
            display, comments, calls, ref_quote = _symbol_text(symbol)
            code_ref, _, code_quote = ref_quote.partition("\n")
            code_quote = code_quote or symbol_id
            keyword = _overlap(paper_text, display)
            comment = _overlap(paper_text, comments)
            call_support = _overlap(paper_text, calls)
            tensor_support = 1.0 if symbol_id in tensor_symbols else 0.0
            path_prior = _overlap(f"{paper_text} {section_text}", str(symbol.get("path", "")))
            is_pytorch = (str(symbol.get("path", "")), str(symbol.get("name", ""))) in pytorch_keys
            if is_pytorch:
                path_prior = max(path_prior, 0.6)
            score = (
                0.35 * keyword
                + 0.25 * comment
                + 0.15 * call_support
                + 0.15 * tensor_support
                + 0.10 * path_prior
            )
            if is_pytorch and score < 0.26:
                score = 0.26
            if score < 0.20:
                continue
            relation = "implements" if score >= 0.30 or is_pytorch else "mentions"
            features = []
            if keyword:
                features.append("关键词/符号匹配")
            if comment:
                features.append("注释语义匹配")
            if call_support:
                features.append("调用关系支持")
            if tensor_support:
                features.append("张量图支持")
            if is_pytorch:
                features.append("PyTorch 模块候选")
            rationale = "、".join(features) or "静态结构先验匹配"
            ranked.append(
                StaticCandidate(
                    candidate_id=f"candidate-{len(ranked) + 1}",
                    paper_block_id=block["id"],
                    code_symbol_id=symbol_id,
                    relation_type=relation,
                    confidence=round(min(1.0, score), 4),
                    rationale=f"{rationale}，需人工确认。",
                    evidence=[
                        {"side": "paper", "ref": block["id"], "quote": paper_text[:1000]},
                        {"side": "code", "ref": code_ref, "quote": code_quote[:1000]},
                    ],
                    paper_text=paper_text,
                    code_text=code_quote,
                )
            )
    ranked.sort(key=lambda item: item.confidence, reverse=True)
    deduplicated: list[StaticCandidate] = []
    seen: set[tuple[str, str]] = set()
    for candidate in ranked:
        key = (candidate.paper_block_id, candidate.code_symbol_id)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(candidate)
        if len(deduplicated) >= limit:
            break
    return deduplicated
