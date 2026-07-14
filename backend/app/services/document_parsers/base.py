from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.services.document_parsers.models import ParsedDocument


@dataclass(slots=True)
class ParseOutcome:
    document: ParsedDocument
    raw_payload: Any
    raw_archive: bytes | None = None
    external_task_id: str | None = None


class DocumentParser(Protocol):
    name: str
    cache_namespace: str

    def parse(self, path: Path) -> ParseOutcome: ...
