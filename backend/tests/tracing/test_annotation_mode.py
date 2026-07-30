"""Annotation-mode trace creation: line-range code refs and server-derived evidence.

Annotation mode differs from the Agent and legacy paths in two ways that need their own
coverage: the code side is identified by a ``path:start-end`` line range rather than an
indexed symbol id, and the client sends no evidence at all — the selection *is* the evidence,
so the server derives both quotes.
"""

import zipfile
from collections.abc import Iterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from app.api.routes.traces import router
from app.db.session import get_session
from app.models.entities import CodeRepository, PaperDocument, Project

SOURCE = (
    "import torch\n"
    "\n"
    "class FocalLoss(torch.nn.Module):\n"
    "    def forward(self, pred, target):\n"
    "        p = torch.sigmoid(pred)\n"
    "        w = (1 - p) ** self.gamma\n"
    "        return -(w * target * torch.log(p)).mean()\n"
)


def _client(tmp_path: Path) -> tuple[TestClient, int]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    archive_path = tmp_path / "repo.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("repo/losses.py", SOURCE)

    with Session(engine) as session:
        project = Project(name="Annotation fixture")
        session.add(project)
        session.commit()
        session.refresh(project)
        block = {
            "id": "p1-b1",
            "kind": "paragraph",
            "page": 1,
            "section_path": ["Method", "Loss"],
            "text": "We adopt a focal loss that down-weights easy negatives.",
        }
        session.add(
            PaperDocument(
                project_id=project.id or 0,
                filename="paper.pdf",
                storage_path="paper.pdf",
                parse_status="succeeded",
                sections_json=[],
                paragraphs_json=[block],
                pages_json=[{"page_number": 1, "blocks": [block]}],
            )
        )
        session.add(
            CodeRepository(
                project_id=project.id or 0,
                filename="repo.zip",
                storage_path=str(archive_path),
                analysis_status="succeeded",
                analysis_revision=1,
                file_tree_json=[{"path": "losses.py", "language": "python", "editable": True}],
                symbols_json=[],
                imports_json=[],
                pytorch_candidates_json=[],
            )
        )
        session.commit()
        project_id = project.id or 0

    def session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_session] = session_override
    return TestClient(app), project_id


def test_line_range_ref_without_evidence_derives_both_quotes(tmp_path: Path) -> None:
    client, project_id = _client(tmp_path)
    with client:
        created = client.post(
            f"/api/v1/projects/{project_id}/trace-links",
            json={
                "paper_ref": "p1-b1",
                "code_ref": "losses.py:5-7",
                "relation_type": "implements",
                "confidence": 0.85,
                "rationale": "These lines compute the focal down-weighting term.",
                "evidence": [],
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["source"] == "manual"
        assert body["code_symbol_id"] == "losses.py:5-7"

        evidence = {item["side"]: item for item in body["evidence"]}
        assert set(evidence) == {"paper", "code"}
        # Paper side quotes the real block body, not the ref.
        assert "down-weights easy negatives" in evidence["paper"]["quote"]
        # Code side quotes the actual selected lines and records where they came from.
        assert "torch.sigmoid" in evidence["code"]["quote"]
        assert "log(p)" in evidence["code"]["quote"]
        assert evidence["code"]["path"] == "losses.py"
        assert (evidence["code"]["line_start"], evidence["code"]["line_end"]) == (5, 7)


def test_manual_link_carries_anchor_ids_so_both_panes_can_decorate(tmp_path: Path) -> None:
    """Without a target id on each side the reader silently draws no highlight.

    ``useTraceIndex`` keys its decoration maps by target id and skips any link whose id is
    null, which is how a manual relation could show up in the matrix, jump correctly, and
    still leave both panes unmarked and unclickable.
    """

    client, project_id = _client(tmp_path)
    with client:
        created = client.post(
            f"/api/v1/projects/{project_id}/trace-links",
            json={
                "paper_ref": "p1-b1",
                "code_ref": "losses.py:5-7",
                "relation_type": "implements",
                "confidence": 0.85,
                "rationale": "These lines compute the focal down-weighting term.",
                "evidence": [],
            },
        )
        assert created.status_code == 201, created.text
        evidence = {item["side"]: item for item in created.json()["evidence"]}

        assert evidence["paper"]["target_id"], "paper anchor id missing"
        assert evidence["code"]["target_id"], "code anchor id missing"
        assert evidence["paper"]["target_id"] != evidence["code"]["target_id"]
        # The reader needs a target_type / role to pick a decoration style.
        assert evidence["paper"]["target_type"]
        assert evidence["code"]["role"]
        # Occurrence drives which match inside the block gets wrapped.
        assert evidence["paper"]["occurrence"] == 1


def test_same_paper_block_reuses_one_anchor_across_fanout(tmp_path: Path) -> None:
    """One paper target → several code sites must collapse to a single paper highlight."""

    client, project_id = _client(tmp_path)
    with client:
        first = client.post(
            f"/api/v1/projects/{project_id}/trace-links",
            json={
                "paper_ref": "p1-b1",
                "code_ref": "losses.py:5-7",
                "relation_type": "implements",
                "confidence": 0.8,
                "rationale": "Down-weighting term lives here.",
                "evidence": [],
            },
        )
        second = client.post(
            f"/api/v1/projects/{project_id}/trace-links",
            json={
                "paper_ref": "p1-b1",
                "code_ref": "losses.py:3",
                "relation_type": "defines",
                "confidence": 0.7,
                "rationale": "And the class is declared here.",
                "evidence": [],
            },
        )
        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text

        def paper_target(response: object) -> str:
            body = response.json()  # type: ignore[attr-defined]
            return next(e["target_id"] for e in body["evidence"] if e["side"] == "paper")

        def code_target(response: object) -> str:
            body = response.json()  # type: ignore[attr-defined]
            return next(e["target_id"] for e in body["evidence"] if e["side"] == "code")

        # Same block, same quote → same anchor, so the reader draws one highlight.
        assert paper_target(first) == paper_target(second)
        # Different line ranges → distinct code anchors.
        assert code_target(first) != code_target(second)


def test_anchor_id_is_stable_across_identical_recreation(tmp_path: Path) -> None:
    """Anchor ids are content-derived, not random, so selection survives a reload."""

    first_client, first_project = _client(tmp_path)
    with first_client:
        first = first_client.post(
            f"/api/v1/projects/{first_project}/trace-links",
            json={
                "paper_ref": "p1-b1",
                "code_ref": "losses.py:5-7",
                "relation_type": "implements",
                "confidence": 0.8,
                "rationale": "First database.",
                "evidence": [],
            },
        )
    second_client, second_project = _client(tmp_path)
    with second_client:
        second = second_client.post(
            f"/api/v1/projects/{second_project}/trace-links",
            json={
                "paper_ref": "p1-b1",
                "code_ref": "losses.py:5-7",
                "relation_type": "implements",
                "confidence": 0.8,
                "rationale": "Second database, same anchors.",
                "evidence": [],
            },
        )
    ids = [
        {e["side"]: e["target_id"] for e in response.json()["evidence"]}
        for response in (first, second)
    ]
    assert ids[0] == ids[1]


def test_single_line_ref_is_accepted(tmp_path: Path) -> None:
    client, project_id = _client(tmp_path)
    with client:
        created = client.post(
            f"/api/v1/projects/{project_id}/trace-links",
            json={
                "paper_ref": "p1-b1",
                "code_ref": "losses.py:3",
                "relation_type": "defines",
                "confidence": 0.7,
                "rationale": "Class declaration for the loss.",
                "evidence": [],
            },
        )
        assert created.status_code == 201, created.text
        evidence = {item["side"]: item for item in created.json()["evidence"]}
        assert "class FocalLoss" in evidence["code"]["quote"]
        assert (evidence["code"]["line_start"], evidence["code"]["line_end"]) == (3, 3)


def test_out_of_range_lines_are_clamped_to_the_file(tmp_path: Path) -> None:
    client, project_id = _client(tmp_path)
    with client:
        created = client.post(
            f"/api/v1/projects/{project_id}/trace-links",
            json={
                "paper_ref": "p1-b1",
                "code_ref": "losses.py:5-9999",
                "relation_type": "implements",
                "confidence": 0.6,
                "rationale": "Selection ran past the end of the file.",
                "evidence": [],
            },
        )
        assert created.status_code == 201, created.text
        evidence = {item["side"]: item for item in created.json()["evidence"]}
        assert evidence["code"]["line_end"] == len(SOURCE.splitlines())


def test_explicit_evidence_is_preserved_and_not_overwritten(tmp_path: Path) -> None:
    client, project_id = _client(tmp_path)
    with client:
        created = client.post(
            f"/api/v1/projects/{project_id}/trace-links",
            json={
                "paper_ref": "p1-b1",
                "code_ref": "losses.py:5-7",
                "relation_type": "implements",
                "confidence": 0.9,
                "rationale": "Caller supplied its own quotes.",
                "evidence": [
                    {"side": "paper", "ref": "p1-b1", "quote": "focal loss"},
                    {"side": "code", "ref": "losses.py:5-7", "quote": "torch.sigmoid(pred)"},
                ],
            },
        )
        assert created.status_code == 201, created.text
        evidence = {item["side"]: item for item in created.json()["evidence"]}
        assert evidence["paper"]["quote"] == "focal loss"
        assert evidence["code"]["quote"] == "torch.sigmoid(pred)"


def test_unresolvable_paper_block_is_rejected_not_silently_stored(tmp_path: Path) -> None:
    """A reference that anchors to nothing must fail loudly.

    Storing it would create a relation that lists in the matrix and even jumps, while both
    panes stay blank — the failure would only surface much later, far from its cause.
    """

    client, project_id = _client(tmp_path)
    with client:
        created = client.post(
            f"/api/v1/projects/{project_id}/trace-links",
            json={
                "paper_ref": "para-42",
                "code_ref": "losses.py:5-7",
                "relation_type": "mentions",
                "confidence": 0.4,
                "rationale": "Block id that matches no stored block.",
                "evidence": [],
            },
        )
        assert created.status_code == 422
        assert "para-42" in created.json()["detail"]


def test_unresolvable_code_reference_is_rejected(tmp_path: Path) -> None:
    client, project_id = _client(tmp_path)
    with client:
        created = client.post(
            f"/api/v1/projects/{project_id}/trace-links",
            json={
                "paper_ref": "p1-b1",
                "code_ref": "does/not/exist.py::Ghost",
                "relation_type": "implements",
                "confidence": 0.5,
                "rationale": "Symbol that is not in the index.",
                "evidence": [],
            },
        )
        assert created.status_code == 422
        assert "does/not/exist.py::Ghost" in created.json()["detail"]


def test_update_and_delete_round_trip(tmp_path: Path) -> None:
    client, project_id = _client(tmp_path)
    with client:
        created = client.post(
            f"/api/v1/projects/{project_id}/trace-links",
            json={
                "paper_ref": "p1-b1",
                "code_ref": "losses.py:5-7",
                "relation_type": "implements",
                "confidence": 0.5,
                "rationale": "Initial rationale for the relation.",
                "evidence": [],
            },
        )
        trace_id = created.json()["id"]

        updated = client.patch(
            f"/api/v1/projects/{project_id}/trace-links/{trace_id}",
            json={"confidence": 0.95, "rationale": "Revised after a closer read."},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["confidence"] == 0.95
        assert updated.json()["rationale"] == "Revised after a closer read."
        # An omitted field keeps its stored value.
        assert updated.json()["relation_type"] == "implements"

        deleted = client.delete(f"/api/v1/projects/{project_id}/trace-links/{trace_id}")
        assert deleted.status_code == 200, deleted.text
        # Soft delete: the row survives as rejected for the audit trail.
        rows = client.get(f"/api/v1/projects/{project_id}/trace-links").json()
        assert [row["status"] for row in rows] == ["rejected"]
