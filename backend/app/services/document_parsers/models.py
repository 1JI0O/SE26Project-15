from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class PaperBlock:
    id: str
    kind: str
    text: str
    page_number: int
    #: Block box in 0-1 of the page, top-left origin (MinerU's 0-1000 space, rescaled).
    bbox: list[float] | None = None
    section_path: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Per-line boxes ``{"text", "bbox"}`` in the same 0-1 space, recovered from
    #: ``middle.json`` when available. Empty for documents parsed before geometry
    #: capture existed, or when the block could not be matched to its lines — the
    #: reader then highlights the whole block box instead.
    lines: list[dict[str, Any]] = field(default_factory=list)
    #: Page dimensions in PDF points, from ``middle.json``. Carried so the reader can
    #: compare them against the page it actually rendered: a mismatch (a rotated page,
    #: a MinerU/renderer disagreement) means the boxes cannot be trusted, and drawing
    #: them anyway would put highlights over unrelated text.
    page_size: list[float] | None = None


@dataclass(slots=True)
class PaperPage:
    page_number: int
    title: str
    blocks: list[PaperBlock] = field(default_factory=list)


@dataclass(slots=True)
class ParsedDocument:
    parser: str
    parser_version: str
    title: str
    abstract: str
    pages: list[PaperPage]
    sections: list[dict[str, Any]]
    paragraphs: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["pages"] = [
            {
                "page_number": page.page_number,
                "title": page.title,
                "body": [block.text for block in page.blocks if block.text],
                "anchors": [
                    {
                        "id": block.id,
                        "type": block.kind,
                        "text": block.text,
                        "bbox": block.bbox,
                        "page": block.page_number,
                        "section_path": block.section_path,
                    }
                    for block in page.blocks
                ],
                "blocks": [asdict(block) for block in page.blocks],
            }
            for page in self.pages
        ]
        return payload
