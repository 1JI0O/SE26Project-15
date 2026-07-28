from pathlib import Path

from tracelab_core.workspace import ensure_layout, import_pdf, tracelab_paths


def test_ensure_layout_creates_tracelab(tmp_path: Path) -> None:
    paths = ensure_layout(tmp_path)
    assert paths.root.is_dir()
    assert paths.config.is_file()
    assert paths.links_json.is_file()


def test_import_pdf_copies_source(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    paths = import_pdf(tmp_path, pdf)
    assert paths.source_pdf.is_file()
    assert paths.source_pdf.read_bytes() == pdf.read_bytes()


def test_tracelab_paths_relative(tmp_path: Path) -> None:
    paths = tracelab_paths(tmp_path)
    assert paths.root.name == ".tracelab"
