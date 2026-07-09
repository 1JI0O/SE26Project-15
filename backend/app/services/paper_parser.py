import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

SECTION_RE = re.compile(
    r"^(abstract|introduction|related work|method|methods|approach|experiments?|results?|"
    r"discussion|conclusion|references|appendix|[0-9]+(?:\\.[0-9]+)*\\s+.+)$",
    re.IGNORECASE,
)


def _clean_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _extract_abstract(full_text: str) -> str:
    match = re.search(
        r"abstract\\s*(?P<body>.+?)(?:\\n\\s*(?:1\\s+)?introduction\\b|\\n\\s*keywords?\\b)",
        full_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return ""
    return " ".join(match.group("body").split())[:2000]


def _paragraphs_for_page(page_number: int, text: str) -> list[dict[str, Any]]:
    paragraphs: list[dict[str, Any]] = []
    blocks = re.split(r"\\n\\s*\\n", text)
    for block in blocks:
        normalized = " ".join(block.split())
        if len(normalized) < 24:
            continue
        paragraphs.append({"page": page_number, "text": normalized})
    return paragraphs


def parse_pdf(path: str | Path) -> dict[str, Any]:
    reader = PdfReader(str(path))
    page_texts: list[tuple[int, str]] = []
    for index, page in enumerate(reader.pages, start=1):
        page_texts.append((index, page.extract_text() or ""))

    all_lines: list[str] = []
    paragraphs: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    for page_number, text in page_texts:
        lines = _clean_lines(text)
        all_lines.extend(lines)
        paragraphs.extend(_paragraphs_for_page(page_number, text))
        for line in lines:
            if SECTION_RE.match(line) and len(line) <= 140:
                sections.append({"title": line, "page": page_number})

    for idx, paragraph in enumerate(paragraphs, start=1):
        paragraph["id"] = f"paragraph:{idx}"

    title = all_lines[0] if all_lines else Path(path).stem
    full_text = "\\n".join(text for _, text in page_texts)
    abstract = _extract_abstract(full_text)
    if not abstract and paragraphs:
        abstract = paragraphs[0]["text"][:1000]

    return {
        "title": title[:500],
        "abstract": abstract,
        "sections": sections,
        "paragraphs": paragraphs,
    }

