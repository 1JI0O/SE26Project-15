"""A PDF the parser cannot open is client input, so the upload must answer 400.

The route only checks the filename extension, so anything renamed to .pdf reaches pypdf.
pypdf raises a wide range of types for bad input, and letting those propagate produced a
500 -- telling the client to retry a request that can never succeed.

Found by the stress-test round documented in ``docs/stress-test-report.md`` (D4).
"""

import io

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.main import app
from app.services.paper_parser import PdfParseError, parse_pdf


def _valid_pdf() -> bytes:
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("label", "payload"),
    [
        ("header_only", b"%PDF-1.7\n"),  # no xref table: "startxref not found"
        ("truncated", _valid_pdf()[:120]),
        ("not_a_pdf", b"this is plain text pretending to be a paper"),
        ("empty", b""),
    ],
)
def test_malformed_pdf_upload_is_rejected_with_400(label: str, payload: bytes) -> None:
    with TestClient(app) as client:
        project_id = client.post("/api/v1/projects", json={"name": f"bad-pdf-{label}"}).json()["id"]
        response = client.post(
            f"/api/v1/projects/{project_id}/paper",
            files={"file": (f"{label}.pdf", payload, "application/pdf")},
        )

    assert response.status_code == 400, f"{label}: expected 400, got {response.status_code}"
    assert response.json()["detail"]


def test_valid_pdf_upload_still_succeeds() -> None:
    """Guard against the 400 path swallowing legitimate uploads."""

    with TestClient(app) as client:
        project_id = client.post("/api/v1/projects", json={"name": "good-pdf"}).json()["id"]
        response = client.post(
            f"/api/v1/projects/{project_id}/paper",
            files={"file": ("paper.pdf", _valid_pdf(), "application/pdf")},
        )

    assert response.status_code == 201


def test_parse_pdf_raises_domain_error(tmp_path) -> None:
    """The service layer signals bad input with PdfParseError, not a bare pypdf type.

    PdfParseError subclasses ValueError so the broad guards in local_sync and
    workspace_service keep treating it as a recoverable preview failure.
    """

    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7\n")

    with pytest.raises(PdfParseError):
        parse_pdf(broken)
    assert issubclass(PdfParseError, ValueError)
