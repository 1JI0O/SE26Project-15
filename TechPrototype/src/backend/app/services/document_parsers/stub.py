from pathlib import Path
from typing import Any

from app.services.document_parsers.base import ParseOutcome
from app.services.document_parsers.normalizer import normalize_mineru_payload


class StubParser:
    name = "stub"
    cache_namespace = "stub:v1"

    def __init__(self, payload: Any | None = None) -> None:
        self.payload = payload or [
            {
                "type": "title",
                "content": {"title_content": "TraceLab Stub Paper", "level": 1},
                "bbox": [100, 100, 900, 180],
                "page_idx": 0,
            },
            {
                "type": "paragraph",
                "content": {"paragraph_content": "Stub parser content for tests."},
                "bbox": [100, 220, 900, 300],
                "page_idx": 0,
            },
        ]

    def parse(self, path: Path) -> ParseOutcome:
        if not path.exists() or path.stat().st_size == 0:
            raise ValueError("PDF file is empty or missing")
        document = normalize_mineru_payload(
            self.payload,
            filename=path.name,
            parser_version="stub-1",
        )
        document.parser = self.name
        return ParseOutcome(document=document, raw_payload=self.payload)
