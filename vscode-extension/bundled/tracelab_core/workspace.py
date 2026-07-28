"""`.tracelab/` workspace layout and JSON IO."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TraceLabPaths:
    root: Path

    @property
    def config(self) -> Path:
        return self.root / "config.json"

    @property
    def papers_dir(self) -> Path:
        return self.root / "papers"

    @property
    def source_pdf(self) -> Path:
        return self.papers_dir / "source.pdf"

    @property
    def parsed_dir(self) -> Path:
        return self.papers_dir / "parsed"

    @property
    def normalized_json(self) -> Path:
        return self.parsed_dir / "normalized.json"

    @property
    def analysis_dir(self) -> Path:
        return self.root / "analysis"

    @property
    def symbols_json(self) -> Path:
        return self.analysis_dir / "symbols.json"

    @property
    def tensor_graph_json(self) -> Path:
        return self.analysis_dir / "tensor_graph.json"

    @property
    def document_md(self) -> Path:
        return self.parsed_dir / "document.md"

    @property
    def paper_document_json(self) -> Path:
        return self.parsed_dir / "paper_document.json"

    @property
    def paper_assets_dir(self) -> Path:
        return self.parsed_dir / "assets"

    @property
    def architecture_json(self) -> Path:
        return self.analysis_dir / "architecture.json"

    @property
    def revision_json(self) -> Path:
        return self.analysis_dir / "revision.json"

    @property
    def traces_dir(self) -> Path:
        return self.root / "traces"

    @property
    def links_json(self) -> Path:
        return self.traces_dir / "links.json"

    @property
    def jobs_dir(self) -> Path:
        return self.traces_dir / "jobs"


def tracelab_paths(workspace_root: Path) -> TraceLabPaths:
    return TraceLabPaths(workspace_root / ".tracelab")


def ensure_layout(workspace_root: Path) -> TraceLabPaths:
    paths = tracelab_paths(workspace_root)
    for directory in (
        paths.root,
        paths.papers_dir,
        paths.parsed_dir,
        paths.analysis_dir,
        paths.traces_dir,
        paths.jobs_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    if not paths.config.is_file():
        write_json(
            paths.config,
            {
                "version": 1,
                "created_at": _now_iso(),
                "paper_source": "papers/source.pdf",
            },
        )
    if not paths.links_json.is_file():
        write_json(paths.links_json, {"links": [], "updated_at": _now_iso()})
    return paths


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def import_pdf(workspace_root: Path, pdf_path: Path) -> TraceLabPaths:
    paths = ensure_layout(workspace_root)
    shutil.copy2(pdf_path, paths.source_pdf)
    config = read_json(paths.config, {}) or {}
    config["paper_source"] = str(paths.source_pdf.relative_to(paths.root))
    config["paper_imported_at"] = _now_iso()
    write_json(paths.config, config)
    return paths


def append_job_log(paths: TraceLabPaths, job_name: str, payload: dict[str, Any]) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = paths.jobs_dir / f"{stamp}-{job_name}.json"
    write_json(target, {"job": job_name, "at": _now_iso(), **payload})
    return target


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
