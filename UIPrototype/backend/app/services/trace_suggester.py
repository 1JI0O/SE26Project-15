from typing import Any


def _normalize(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def suggest_trace_links(
    sections: list[dict[str, Any]],
    paragraphs: list[dict[str, Any]],
    symbols: list[dict[str, Any]],
    pytorch_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    paper_refs = paragraphs[:8] or [{"id": "paper:abstract", "text": ""}]

    for candidate in pytorch_candidates[:5]:
        paper_ref = paper_refs[0].get("id", "paper:abstract")
        suggestions.append(
            {
                "paper_ref": paper_ref,
                "code_ref": f"{candidate['path']}:{candidate['name']}",
                "relation_type": "implements",
                "confidence": 0.66,
                "rationale": "代码类疑似 PyTorch 模型，可作为论文模型结构描述的候选实现。",
            }
        )

    section_tokens = [(_normalize(section.get("title", "")), section) for section in sections[:20]]
    for symbol in symbols:
        symbol_name = _normalize(symbol.get("name", ""))
        if not symbol_name:
            continue
        for section_token, section in section_tokens:
            if symbol_name and symbol_name in section_token:
                suggestions.append(
                    {
                        "paper_ref": f"section:{section.get('title', '')}",
                        "code_ref": f"{symbol.get('path')}:{symbol.get('name')}",
                        "relation_type": "mentions",
                        "confidence": 0.52,
                        "rationale": "章节标题与代码符号名称存在文本匹配，可进入人工确认队列。",
                    }
                )
                break
        if len(suggestions) >= 10:
            break

    return suggestions[:10]

