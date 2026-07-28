from pathlib import Path

from tracelab_core.workspace import (
    append_job_log,
    ensure_layout,
    import_pdf,
    read_json,
    tracelab_paths,
    write_json,
)


def test_ensure_layout_creates_tracelab(tmp_path: Path) -> None:
    paths = ensure_layout(tmp_path)
    assert paths.root.is_dir()
    assert paths.config.is_file()
    assert paths.links_json.is_file()


def test_ensure_layout_preserves_existing_metadata(tmp_path: Path) -> None:
    paths = ensure_layout(tmp_path)
    write_json(paths.config, {"version": 7, "name": "保留"})
    write_json(paths.links_json, {"links": [{"id": "existing"}]})

    second = ensure_layout(tmp_path)

    assert read_json(second.config) == {"version": 7, "name": "保留"}
    assert read_json(second.links_json)["links"] == [{"id": "existing"}]


def test_import_pdf_copies_source(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    paths = import_pdf(tmp_path, pdf)
    assert paths.source_pdf.is_file()
    assert paths.source_pdf.read_bytes() == pdf.read_bytes()
    config = read_json(paths.config)
    assert Path(config["paper_source"]).as_posix() == "papers/source.pdf"
    assert config["paper_imported_at"].endswith("Z")


def test_tracelab_paths_relative(tmp_path: Path) -> None:
    paths = tracelab_paths(tmp_path)
    assert paths.root.name == ".tracelab"


def test_tracelab_paths_exposes_every_artifact(tmp_path: Path) -> None:
    paths = tracelab_paths(tmp_path)
    expected = {
        "config": ".tracelab/config.json",
        "papers_dir": ".tracelab/papers",
        "source_pdf": ".tracelab/papers/source.pdf",
        "parsed_dir": ".tracelab/papers/parsed",
        "normalized_json": ".tracelab/papers/parsed/normalized.json",
        "document_md": ".tracelab/papers/parsed/document.md",
        "paper_document_json": ".tracelab/papers/parsed/paper_document.json",
        "paper_assets_dir": ".tracelab/papers/parsed/assets",
        "analysis_dir": ".tracelab/analysis",
        "symbols_json": ".tracelab/analysis/symbols.json",
        "tensor_graph_json": ".tracelab/analysis/tensor_graph.json",
        "architecture_json": ".tracelab/analysis/architecture.json",
        "revision_json": ".tracelab/analysis/revision.json",
        "traces_dir": ".tracelab/traces",
        "links_json": ".tracelab/traces/links.json",
        "jobs_dir": ".tracelab/traces/jobs",
    }
    for attribute, relative in expected.items():
        assert getattr(paths, attribute).relative_to(tmp_path).as_posix() == relative


def test_json_io_is_utf8_and_missing_path_returns_default(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "data.json"
    payload = {"title": "论文", "items": [1, 2]}

    assert read_json(target, payload) is payload
    write_json(target, payload)

    assert read_json(target) == payload
    assert "论文" in target.read_text(encoding="utf-8")


def test_append_job_log_writes_timestamped_payload(tmp_path: Path) -> None:
    paths = ensure_layout(tmp_path)
    target = append_job_log(paths, "analyze", {"count": 3, "job": "overridden"})

    assert target.parent == paths.jobs_dir
    assert target.name.endswith("-analyze.json")
    payload = read_json(target)
    assert payload["job"] == "overridden"
    assert payload["count"] == 3
    assert payload["at"].endswith("Z")
