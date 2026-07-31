"""Regression tests for what survives a round trip through cloud sync.

Root causes these guard against, all of the same shape — the sync protocol was written
against an earlier version of the domain and was never extended as features landed:

1. ``import_cloud_file`` parsed every downloaded PDF with the pypdf compatibility parser
   and stamped ``parser="cloud-import"`` / ``content_hash=""``. MinerU was never invoked on
   the receiving device no matter how it was configured, and the empty content hash made
   ``markdown_for_cache`` miss, so the reader silently fell back to synthesized markdown.
2. ``trace_payload`` carried 8 of the ~20 fields a TraceLink now has. Downloaded relations
   arrived with ``relevance=0`` / ``source="static"`` and both foreign keys null.
3. ``paper_target`` / ``code_target`` had no sync coverage at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import get_args, get_type_hints

from app.core.config import settings
from app.models.entities import Project, TraceLink
from app.schemas.local_sync import LocalCloudEntityImport
from app.services import local_sync


class _NullSession:
    """trace_payload only reads rows to translate ids; nothing to translate here."""

    def get(self, _model, _key):  # noqa: ANN001, ANN202
        return None


def _payload_fields() -> set[str]:
    project = Project(name="p")
    link = TraceLink(
        project_id=1,
        paper_ref="block:1",
        code_ref="mod::fn",
        relation_type="implements",
    )
    return set(local_sync.trace_payload(project, link, session=_NullSession()).keys())


def test_trace_payload_carries_scoring_and_provenance() -> None:
    """A relation's rank and origin must survive the wire.

    ``relevance`` drives the workbench's ordering and the 相关度 badge; ``source``
    distinguishes agent-generated relations from manual ones in the list filter. Both
    defaulted on the receiving device before these were added to the payload.
    """

    fields = _payload_fields()
    for field in (
        "relevance",
        "source",
        "static_confidence",
        "llm_confidence",
        "uncertainty",
        "model_info",
        "score_basis",
        "provenance",
        "supersedes_trace_id",
        "fingerprint",
    ):
        assert field in fields, f"trace_payload dropped {field}"


def test_trace_payload_translates_local_ids_to_public_ids() -> None:
    """Device-local primary keys must not travel.

    ``paper_target_id`` is a ``ptarget-<hex>`` local key and ``paper_document_id`` an
    autoincrement int; neither means anything on another install. Sending them raw would
    have the importer either drop the reference or point it at an unrelated row.
    """

    fields = _payload_fields()
    assert "paper_target_public_id" in fields
    assert "code_target_public_id" in fields
    assert "paper_document_public_id" in fields
    assert "code_repository_public_id" in fields
    assert "paper_target_id" not in fields
    assert "code_target_id" not in fields
    assert "paper_document_id" not in fields
    assert "code_repository_id" not in fields


# Hard-coded copy of the cloud server's SyncEntityType
# (server/tracelab_server/schemas/cloud.py). The server rejects an unknown entity_type at
# the Pydantic boundary with 422, and because push batches every pending operation into one
# request, a single unrecognised type blocks the whole workspace. If the server list changes
# without this mirror being updated, fail here instead of in production sync.
_SERVER_SYNC_ENTITY_TYPES = {
    "project",
    "paper_document",
    "code_repository",
    "code_edit",
    "paper_target",
    "code_target",
    "trace_link",
    "agent_conversation",
    "agent_message",
    "agent_run",
    "agent_run_event",
    "agent_memory",
}


def test_locally_importable_types_are_accepted_by_the_server() -> None:
    hints = get_type_hints(LocalCloudEntityImport)
    local_types = set(get_args(hints["entity_type"]))
    unknown = local_types - _SERVER_SYNC_ENTITY_TYPES
    assert not unknown, f"local import accepts types the server rejects: {sorted(unknown)}"


def test_imported_paper_is_not_stamped_as_a_final_pypdf_parse(monkeypatch) -> None:  # noqa: ANN001
    """The reported bug: a synced paper showed up parsed by pypdf, not MinerU.

    The import writes a placeholder so the reader has text immediately, then re-derives the
    document with *this device's* configured parser. What must never happen again is the
    placeholder being recorded as a completed parse — that is what made the fallback
    permanent and invisible.
    """

    from fastapi.testclient import TestClient

    from app.api.routes import local_sync as route
    from app.main import app

    scheduled: list[tuple[int, str]] = []
    monkeypatch.setattr(
        route, "schedule_paper_reparse", lambda pid, public_id: scheduled.append((pid, public_id))
    )

    public_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "import fidelity"}).json()
        response = client.put(
            f"/api/v1/local-sync/projects/{project['id']}/imports/paper_document/{public_id}",
            content=_MINIMAL_PDF,
            params={
                "filename": "paper.pdf",
                "version": 1,
                "blob_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            },
            headers={"Content-Type": "application/octet-stream"},
        )
        assert response.status_code == 200
        document = client.get(f"/api/v1/projects/{project['id']}/paper").json()

    assert document["parser"] != "cloud-import"
    assert document["content_hash"] == ""  # only the real parse may claim a cache key
    # Not "succeeded": the placeholder is not an answer, and the RAG paper index skips any
    # scope whose parse_status is not succeeded, so it cannot pin this generation.
    assert document["parse_status"] == "running"
    assert scheduled == [(project["id"], public_id)]


# Smallest structurally valid PDF pypdf will open. The content is irrelevant — the assertions
# are about which parser is credited, not about extraction quality.
_MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n"
    b"%%EOF\n"
)


def test_backfill_repairs_projects_enabled_before_the_protocol_grew() -> None:
    """Old cloud projects do not heal on their own.

    Nothing re-touches an entity that has not changed, so a project enabled before anchors
    were syncable keeps a cloud copy with no anchors and a truncated trace_link — forever.
    The backfill re-enqueues both with the current payload builders.
    """

    from fastapi.testclient import TestClient

    from app.main import app

    workspace_id = "77777777-7777-4777-8777-777777777777"
    device_id = "88888888-8888-4888-8888-888888888888"
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "old cloud project"}).json()
        client.post(
            f"/api/v1/projects/{project['id']}/sync/enable",
            json={
                "workspace_id": workspace_id,
                "device_id": device_id,
                "agent_history_sync": False,
            },
        )
        repaired = client.post(
            "/api/v1/local-sync/backfill", params={"workspace_id": workspace_id}
        )
        missing = client.post(
            "/api/v1/local-sync/backfill",
            params={"workspace_id": "99999999-9999-4999-8999-999999999999"},
        )

    assert repaired.status_code == 200
    assert repaired.json()["projects"] == 1
    # A workspace this device was never bound to must not be silently reported as repaired.
    assert missing.status_code == 404


def test_machine_derived_types_do_not_raise_human_conflicts() -> None:
    """Anchors are recomputed from the same artifact, so a version race has no decision in it.

    Routing them to the conflict centre would bury the real conflicts (trace decisions, file
    versions) under regenerated-anchor noise.
    """

    from app.api.routes.local_sync import MACHINE_DERIVED_TYPES

    assert MACHINE_DERIVED_TYPES == {"paper_target", "code_target"}
    assert "trace_link" not in MACHINE_DERIVED_TYPES


def test_repair_rescues_papers_imported_by_the_old_broken_path() -> None:
    """Already-imported papers do not heal on their own.

    ``import_cloud_file`` skips any incoming version that is not newer, so a paper written by
    the old path stays stamped ``parser="cloud-import"`` with an empty ``content_hash`` — and
    therefore stuck on fallback markdown — even after the device gains a working MinerU
    configuration. Only an explicit repair can re-derive it.
    """

    from fastapi.testclient import TestClient
    from sqlmodel import select as sql_select

    from app.db.session import get_session
    from app.main import app
    from app.models.entities import PaperDocument as Doc

    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "legacy import"}).json()
        session = next(iter(app.dependency_overrides[get_session]()))
        # Simulate a paper written by the old import path, with its PDF present on disk.
        storage = Path(settings.upload_root) / f"project-{project['id']}" / "legacy.pdf"
        storage.parent.mkdir(parents=True, exist_ok=True)
        storage.write_bytes(b"%PDF-1.4\ntrailer<</Root 1 0 R>>\n%%EOF\n")
        session.add(
            Doc(
                public_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                project_id=project["id"],
                filename="legacy.pdf",
                storage_path=str(storage),
                parser="cloud-import",
                parser_version="pypdf-compat-v1",
                content_hash="",
                sections_json=[],
                paragraphs_json=[],
                pages_json=[],
            )
        )
        session.commit()

        repaired = client.post("/api/v1/local-sync/repair-imported-papers").json()
        after = session.exec(
            sql_select(Doc).where(Doc.public_id == "cccccccc-cccc-4ccc-8ccc-cccccccccccc")
        ).first()
        session.refresh(after)

    assert repaired["found"] == 1
    assert repaired["scheduled"] == 1
    # The stale marker must be cleared, otherwise a repeat repair would re-find the same row.
    assert after.parser != "cloud-import"
