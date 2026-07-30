import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.api.routes.projects import get_project_or_404
from app.core.config import settings
from app.db.session import get_session
from app.models.entities import (
    AgentConversation,
    AgentMemory,
    AgentMessage,
    AgentRun,
    AgentRunEvent,
    CodeRepository,
    CodeTarget,
    LocalArtifactVersion,
    PaperDocument,
    PaperTarget,
    Project,
    TraceLink,
    utc_now,
)
from app.models.sync import (
    LocalSyncConflict,
    LocalSyncInbox,
    LocalSyncOutbox,
    LocalSyncState,
)
from app.schemas.local_sync import (
    LocalAgentHistoryPatch,
    LocalArtifactSelect,
    LocalCloudEntityImport,
    LocalCloudProjectImport,
    LocalConflictResolve,
    LocalDeviceAdopt,
    LocalSyncEnable,
    LocalSyncModePatch,
    LocalSyncResults,
    RemoteSyncEvents,
)
from app.services.cloud_import import (
    schedule_paper_reparse,
    schedule_repository_analysis,
)
from app.services.code_analysis.analyzer import scan_code_archive
from app.services.code_analyzer import save_repository_file
from app.services.local_sync import (
    agent_event_payload,
    code_target_payload,
    paper_payload,
    paper_target_payload,
    project_payload,
    record_local_operation,
    repository_payload,
    scrub_forbidden_keys,
    trace_payload,
)
from app.services.paper_parser import parse_pdf

router = APIRouter(tags=["local-sync"])

# Entities the analysis pipeline derives deterministically rather than a human authoring.
# A push conflict on these is resolved by taking the server's copy, not by asking the user.
MACHINE_DERIVED_TYPES = {"paper_target", "code_target"}


@router.post("/local-sync/projects/import")
def import_cloud_project(
    payload: LocalCloudProjectImport,
    session: Session = Depends(get_session),
) -> dict:
    state = session.get(LocalSyncState, payload.workspace_id)
    if state is None:
        state = LocalSyncState(workspace_id=payload.workspace_id, device_id=payload.device_id)
    elif state.device_id != payload.device_id:
        # Device ids rotate across logins; adopt the current device for this
        # workspace instead of refusing the cloud import.
        _adopt_workspace_device(session, payload.workspace_id, payload.device_id)
    project = session.exec(select(Project).where(Project.public_id == payload.public_id)).first()
    if project is None:
        project = Project(
            public_id=payload.public_id,
            cloud_workspace_id=payload.workspace_id,
            name=payload.name,
            description=payload.description,
            version=payload.version,
            sync_mode="cloud_enabled",
            agent_history_sync=payload.agent_history_sync,
            agent_deep_thinking=payload.agent_deep_thinking,
        )
    else:
        project.cloud_workspace_id = payload.workspace_id
        project.name = payload.name
        project.description = payload.description
        project.version = payload.version
        project.sync_mode = "cloud_enabled"
        project.agent_history_sync = payload.agent_history_sync
        project.agent_deep_thinking = payload.agent_deep_thinking
    session.add(state)
    session.add(project)
    session.commit()
    session.refresh(project)
    return {"id": project.id, "public_id": project.public_id}


@router.put("/local-sync/projects/{project_id}/imports/{entity_type}/{public_id}")
async def import_cloud_file(
    project_id: int,
    entity_type: str,
    public_id: str,
    request: Request,
    filename: str,
    version: int,
    blob_id: str,
    artifact_version_id: str | None = None,
    session: Session = Depends(get_session),
) -> dict:
    get_project_or_404(project_id, session)
    if entity_type not in {"paper_document", "code_repository"}:
        raise HTTPException(status_code=422, detail="Unsupported imported file type")
    existing_model = PaperDocument if entity_type == "paper_document" else CodeRepository
    existing = session.exec(
        select(existing_model).where(existing_model.public_id == public_id)
    ).first()
    if existing is not None and version <= existing.version:
        return {"public_id": public_id, "status": "existing"}
    reparse_paper = False
    analyze_revision: int | None = None
    safe_filename = Path(filename).name
    destination = (
        Path(settings.upload_root)
        / f"project-{project_id}"
        / "cloud-imports"
        / public_id
        / f"v{version}-{safe_filename}"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.incoming")
    temporary.write_bytes(await request.body())
    os.replace(temporary, destination)
    if existing is not None:
        known_version = session.exec(
            select(LocalArtifactVersion).where(
                LocalArtifactVersion.entity_type == entity_type,
                LocalArtifactVersion.entity_public_id == public_id,
                LocalArtifactVersion.version_number == existing.version,
            )
        ).first()
        if known_version is None:
            session.add(
                LocalArtifactVersion(
                    project_id=project_id,
                    entity_type=entity_type,
                    entity_public_id=public_id,
                    version_number=existing.version,
                    blob_id=existing.blob_id,
                    cloud_version_id=None,
                    filename=existing.filename,
                    storage_path=existing.storage_path,
                    is_current=False,
                )
            )
        for row in session.exec(
            select(LocalArtifactVersion).where(
                LocalArtifactVersion.entity_type == entity_type,
                LocalArtifactVersion.entity_public_id == public_id,
                LocalArtifactVersion.is_current.is_(True),
            )
        ).all():
            row.is_current = False
            session.add(row)
    if entity_type == "paper_document":
        # ``parse_pdf`` is only a placeholder so the reader has text immediately. It reuses
        # this device's parse cache when the same PDF was already parsed here, otherwise it
        # falls back to pypdf. Either way the configured parser (MinerU) then runs in the
        # background and overwrites this with the real structure + content_hash.
        parsed = _placeholder_parse(destination)
        # Named so it can never be mistaken for a finished parse in the UI or in support
        # questions like "why does my synced paper say pypdf?".
        placeholder_parser = str(parsed.get("parser", "pending-import"))
        placeholder_version = str(parsed.get("parser_version", "placeholder"))
        entity = existing or PaperDocument(
            public_id=public_id,
            project_id=project_id,
            filename=safe_filename,
            storage_path=str(destination),
            title=str(parsed.get("title", "")),
            abstract=str(parsed.get("abstract", "")),
            parser=placeholder_parser,
            parser_version=placeholder_version,
            content_hash="",
            sections_json=parsed.get("sections", []),
            paragraphs_json=parsed.get("paragraphs", []),
            pages_json=parsed.get("pages", []),
        )
        entity.version = version
        entity.blob_id = blob_id
        entity.filename = safe_filename
        entity.storage_path = str(destination)
        entity.title = str(parsed.get("title", ""))
        entity.abstract = str(parsed.get("abstract", ""))
        entity.parser = placeholder_parser
        entity.parser_version = placeholder_version
        # The real cache key is written by the background parse. Leaving it empty until
        # then is what keeps markdown_for_cache from serving a stale archive.
        entity.content_hash = ""
        # "running" keeps the reader from treating the placeholder as the final answer and
        # keeps the RAG paper index from pinning a generation we are about to replace
        # (_source_key skips scopes whose parse_status is not "succeeded").
        entity.parse_status = "running"
        entity.sections_json = parsed.get("sections", [])
        entity.paragraphs_json = parsed.get("paragraphs", [])
        entity.pages_json = parsed.get("pages", [])
        reparse_paper = True
    else:
        analysis = scan_code_archive(destination)
        entity = existing or CodeRepository(
            public_id=public_id,
            project_id=project_id,
            filename=safe_filename,
            storage_path=str(destination),
            file_tree_json=analysis["file_tree"],
            symbols_json=[],
            imports_json=[],
            pytorch_candidates_json=[],
            tensor_graph_json=analysis["tensor_graph"],
            analysis_json={},
            analysis_status="pending",
        )
        entity.version = version
        entity.blob_id = blob_id
        entity.filename = safe_filename
        entity.storage_path = str(destination)
        entity.file_tree_json = analysis["file_tree"]
        entity.tensor_graph_json = analysis["tensor_graph"]
        entity.analysis_status = "queued"
        entity.updated_at = utc_now()
        analyze_revision = entity.revision
    session.add(entity)
    session.add(
        LocalArtifactVersion(
            project_id=project_id,
            entity_type=entity_type,
            entity_public_id=public_id,
            version_number=version,
            blob_id=blob_id,
            cloud_version_id=artifact_version_id,
            filename=safe_filename,
            storage_path=str(destination),
            is_current=True,
        )
    )
    session.commit()
    # Dispatched after commit so the background worker reads a persisted row.
    if reparse_paper:
        schedule_paper_reparse(project_id, public_id)
    elif analyze_revision is not None:
        schedule_repository_analysis(project_id, analyze_revision)
    return {"public_id": public_id, "status": "imported"}


@router.get("/local-sync/projects/{project_id}/artifacts/{entity_type}/{public_id}/versions")
def list_local_artifact_versions(
    project_id: int,
    entity_type: str,
    public_id: str,
    session: Session = Depends(get_session),
) -> list[dict]:
    get_project_or_404(project_id, session)
    rows = session.exec(
        select(LocalArtifactVersion)
        .where(
            LocalArtifactVersion.project_id == project_id,
            LocalArtifactVersion.entity_type == entity_type,
            LocalArtifactVersion.entity_public_id == public_id,
        )
        .order_by(LocalArtifactVersion.version_number.desc())
    ).all()
    return [
        {
            "local_version_id": row.id,
            "version_number": row.version_number,
            "blob_id": row.blob_id,
            "filename": row.filename,
            "is_current": row.is_current,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/local-sync/projects/{project_id}/artifact-versions")
def list_project_artifact_versions(
    project_id: int,
    session: Session = Depends(get_session),
) -> list[dict]:
    get_project_or_404(project_id, session)
    rows = session.exec(
        select(LocalArtifactVersion)
        .where(LocalArtifactVersion.project_id == project_id)
        .order_by(
            LocalArtifactVersion.entity_type,
            LocalArtifactVersion.entity_public_id,
            LocalArtifactVersion.version_number.desc(),
        )
    ).all()
    return [
        {
            "local_version_id": row.id,
            "entity_type": row.entity_type,
            "entity_public_id": row.entity_public_id,
            "version_number": row.version_number,
            "blob_id": row.blob_id,
            "filename": row.filename,
            "is_current": row.is_current,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.post("/local-sync/projects/{project_id}/artifacts/{entity_type}/{public_id}/select")
def select_local_artifact_version(
    project_id: int,
    entity_type: str,
    public_id: str,
    payload: LocalArtifactSelect,
    session: Session = Depends(get_session),
) -> dict:
    project = get_project_or_404(project_id, session)
    if project.sync_mode != "cloud_enabled":
        raise HTTPException(status_code=409, detail="Resume this device before selecting a version")
    model = {
        "paper_document": PaperDocument,
        "code_repository": CodeRepository,
    }.get(entity_type)
    if model is None:
        raise HTTPException(status_code=422, detail="Unsupported artifact type")
    entity = session.exec(select(model).where(model.public_id == public_id)).first()
    selected = session.get(LocalArtifactVersion, payload.local_version_id)
    if (
        entity is None
        or selected is None
        or selected.project_id != project_id
        or selected.entity_type != entity_type
        or selected.entity_public_id != public_id
    ):
        raise HTTPException(status_code=404, detail="Artifact version not found")
    if not selected.cloud_version_id:
        raise HTTPException(status_code=409, detail="Version is not available in cloud history")
    for row in session.exec(
        select(LocalArtifactVersion).where(
            LocalArtifactVersion.project_id == project_id,
            LocalArtifactVersion.entity_type == entity_type,
            LocalArtifactVersion.entity_public_id == public_id,
        )
    ).all():
        row.is_current = row.id == selected.id
        session.add(row)
    entity.storage_path = selected.storage_path
    entity.filename = selected.filename
    entity.blob_id = selected.blob_id
    if isinstance(entity, CodeRepository):
        entity.updated_at = utc_now()
    session.add(entity)
    record_local_operation(
        session,
        project,
        entity_type,
        public_id,
        {
            "project_public_id": project.public_id,
            "version_id": selected.cloud_version_id,
        },
        operation="select_version",
        base_version=entity.version,
    )
    session.commit()
    return {"public_id": public_id, "version_number": selected.version_number}


def _placeholder_parse(destination: Path) -> dict:
    """Best-effort immediate text for a downloaded PDF.

    This only exists so the reader is not blank while the configured parser runs in the
    background. pypdf raises on PDFs it cannot open (a malformed xref, an encrypted file),
    and letting that propagate would fail the whole import — losing the downloaded bytes and
    the sync event — over a preview we are about to discard anyway.
    """

    try:
        return parse_pdf(destination)
    except Exception:
        return {}


def _target_fingerprint(session: Session, model, data: dict, public_id: str) -> str:
    """Same UNIQUE-constraint guard as _importable_fingerprint, for anchor tables."""

    incoming = str(data.get("fingerprint", "") or "")
    if not incoming:
        return f"cloud-{public_id}"
    clash = session.exec(select(model).where(model.fingerprint == incoming)).first()
    if clash is None or clash.public_id == public_id:
        return incoming
    return f"cloud-{public_id}"


def _import_paper_target(
    session: Session, project_id: int, payload: LocalCloudEntityImport
) -> None:
    data = payload.payload
    existing = session.exec(
        select(PaperTarget).where(PaperTarget.public_id == payload.public_id)
    ).first()
    if existing is not None and payload.version <= existing.version:
        return
    document_id = _resolve_local_id(
        session, PaperDocument, data.get("paper_document_public_id"), "id"
    )
    if document_id is None:
        # The anchor is meaningless without the paper it points into. The frontend imports
        # paper_document first, so this only happens when that download failed; skipping
        # leaves the event to be retried rather than writing a dangling row.
        return
    target = existing or PaperTarget(
        project_id=project_id,
        public_id=payload.public_id,
        paper_document_id=document_id,
        # Opaque origin provenance: the artifact chain is not synced and SQLite does not
        # enforce foreign keys, so this is carried for traceability only.
        artifact_id=str(data.get("artifact_id", "") or f"cloud-{payload.public_id}")[:72],
        target_type=str(data.get("target_type", "method_text"))[:32],
        block_id=str(data.get("block_id", ""))[:255],
        quote=str(data.get("quote", "")),
        quote_hash=str(data.get("quote_hash", ""))[:64],
        fingerprint=_target_fingerprint(session, PaperTarget, data, payload.public_id),
    )
    target.version = payload.version
    target.paper_document_id = document_id
    target.target_type = str(data.get("target_type", target.target_type))[:32]
    target.block_id = str(data.get("block_id", target.block_id))[:255]
    target.section_path_json = list(data.get("section_path", []) or [])
    target.quote = str(data.get("quote", target.quote))
    target.occurrence = int(data.get("occurrence", 1) or 1)
    target.char_start = data.get("char_start")
    target.char_end = data.get("char_end")
    target.quote_hash = str(data.get("quote_hash", target.quote_hash))[:64]
    bbox = data.get("bbox")
    target.bbox_json = bbox if isinstance(bbox, list) else None
    asset_path = data.get("asset_path")
    target.asset_path = None if asset_path is None else str(asset_path)[:1000]
    target.salience = float(data.get("salience", 0) or 0)
    target.salience_reason = str(data.get("salience_reason", ""))
    target.anchor_status = str(data.get("anchor_status", "validated"))[:32]
    session.add(target)


def _import_code_target(session: Session, project_id: int, payload: LocalCloudEntityImport) -> None:
    data = payload.payload
    existing = session.exec(
        select(CodeTarget).where(CodeTarget.public_id == payload.public_id)
    ).first()
    if existing is not None and payload.version <= existing.version:
        return
    repository_id = _resolve_local_id(
        session, CodeRepository, data.get("code_repository_public_id"), "id"
    )
    if repository_id is None:
        return
    line_start = max(int(data.get("line_start", 1) or 1), 1)
    line_end = max(int(data.get("line_end", line_start) or line_start), line_start)
    target = existing or CodeTarget(
        project_id=project_id,
        public_id=payload.public_id,
        code_repository_id=repository_id,
        artifact_id=str(data.get("artifact_id", "") or f"cloud-{payload.public_id}")[:72],
        code_revision=int(data.get("code_revision", 1) or 1),
        path=str(data.get("path", ""))[:1000],
        line_start=line_start,
        line_end=line_end,
        quote=str(data.get("quote", "")),
        code_quote_hash=str(data.get("code_quote_hash", ""))[:64],
        role=str(data.get("role", "model_component"))[:64],
        fingerprint=_target_fingerprint(session, CodeTarget, data, payload.public_id),
    )
    target.version = payload.version
    target.code_repository_id = repository_id
    target.code_revision = int(data.get("code_revision", target.code_revision) or 1)
    target.path = str(data.get("path", target.path))[:1000]
    symbol_id = data.get("symbol_id")
    target.symbol_id = None if symbol_id is None else str(symbol_id)[:500]
    target.line_start = line_start
    target.line_end = line_end
    target.column_start = data.get("column_start")
    target.column_end = data.get("column_end")
    target.quote = str(data.get("quote", target.quote))
    target.occurrence = int(data.get("occurrence", 1) or 1)
    target.code_quote_hash = str(data.get("code_quote_hash", target.code_quote_hash))[:64]
    target.role = str(data.get("role", target.role))[:64]
    target.salience = float(data.get("salience", 0) or 0)
    target.salience_reason = str(data.get("salience_reason", ""))
    target.anchor_status = str(data.get("anchor_status", "validated"))[:32]
    session.add(target)


def _importable_fingerprint(session: Session, data: dict, public_id: str) -> str:
    """Keep the origin's fingerprint when it is free, otherwise mint a unique one.

    ``trace_link.fingerprint`` is UNIQUE. Reusing the origin value preserves cross-device
    dedup identity, but two devices can independently generate the same relation before
    ever syncing — then the incoming fingerprint is already taken by a *different*
    public_id and a plain insert would fail the constraint and abort the whole pull.
    """

    incoming = str(data.get("fingerprint", "") or "")
    if not incoming:
        return f"cloud-{public_id}"
    clash = session.exec(select(TraceLink).where(TraceLink.fingerprint == incoming)).first()
    if clash is None or clash.public_id == public_id:
        return incoming
    return f"cloud-{public_id}"


def _resolve_local_id(session: Session, model, public_id: object, attribute: str) -> object | None:
    """Map a synced public id back to this device's local primary key."""

    if not isinstance(public_id, str) or not public_id:
        return None
    row = session.exec(select(model).where(model.public_id == public_id)).first()
    return getattr(row, attribute) if row is not None else None


def _apply_trace_fields(session: Session, link: TraceLink, data: dict) -> None:
    """Copy the synced scoring/provenance fields onto a local TraceLink.

    Only keys present in the payload are applied, so an operation pushed by an older
    client does not reset fields it never knew about.
    """

    if "relation_type" in data:
        link.relation_type = str(data["relation_type"])
    if "confidence" in data:
        link.confidence = float(data["confidence"])
    if "evidence" in data:
        link.evidence_json = data["evidence"] or []
    if "rationale" in data:
        link.rationale = str(data["rationale"])
    if "status" in data:
        link.status = str(data["status"])
    if "relevance" in data:
        link.relevance = float(data["relevance"] or 0)
    if "source" in data:
        link.source = str(data["source"])
    if "static_confidence" in data:
        link.static_confidence = float(data["static_confidence"] or 0)
    if "llm_confidence" in data:
        value = data["llm_confidence"]
        link.llm_confidence = None if value is None else float(value)
    if isinstance(data.get("uncertainty"), dict):
        link.uncertainty_json = data["uncertainty"]
    if "model_info" in data:
        value = data["model_info"]
        link.model_info_json = value if isinstance(value, dict) else None
    if isinstance(data.get("score_basis"), dict):
        link.score_basis_json = data["score_basis"]
    if isinstance(data.get("provenance"), dict):
        link.provenance_json = data["provenance"]
    if "stale_reason" in data:
        value = data["stale_reason"]
        link.stale_reason = None if value is None else str(value)[:128]
    if "supersedes_trace_id" in data:
        value = data["supersedes_trace_id"]
        link.supersedes_trace_id = None if value is None else str(value)[:64]
    if "artifact_id" in data:
        value = data["artifact_id"]
        link.artifact_id = None if value is None else str(value)[:72]

    paper_id = _resolve_local_id(
        session, PaperDocument, data.get("paper_document_public_id"), "id"
    )
    if paper_id is not None:
        link.paper_document_id = paper_id
    repository_id = _resolve_local_id(
        session, CodeRepository, data.get("code_repository_public_id"), "id"
    )
    if repository_id is not None:
        link.code_repository_id = repository_id
    paper_target = _resolve_local_id(
        session, PaperTarget, data.get("paper_target_public_id"), "target_id"
    )
    if paper_target is not None:
        link.paper_target_id = paper_target
    code_target = _resolve_local_id(
        session, CodeTarget, data.get("code_target_public_id"), "target_id"
    )
    if code_target is not None:
        link.code_target_id = code_target


@router.post("/local-sync/projects/{project_id}/imports/entity", status_code=204)
def import_cloud_entity(
    project_id: int,
    payload: LocalCloudEntityImport,
    session: Session = Depends(get_session),
) -> None:
    get_project_or_404(project_id, session)
    if payload.entity_type == "trace_link":
        data = payload.payload
        existing_trace = session.exec(
            select(TraceLink).where(TraceLink.public_id == payload.public_id)
        ).first()
        if existing_trace is not None:
            project = session.get(Project, project_id)
            unresolved = (
                session.exec(
                    select(LocalSyncConflict).where(
                        LocalSyncConflict.workspace_id == project.cloud_workspace_id,
                        LocalSyncConflict.entity_type == "trace_link",
                        LocalSyncConflict.entity_public_id == payload.public_id,
                        LocalSyncConflict.status == "unresolved",
                    )
                ).first()
                if project and project.cloud_workspace_id
                else None
            )
            if unresolved is None and payload.version > existing_trace.version:
                _apply_trace_fields(session, existing_trace, data)
                existing_trace.version = payload.version
                existing_trace.updated_at = utc_now()
                session.add(existing_trace)
        else:
            link = TraceLink(
                public_id=payload.public_id,
                version=payload.version,
                project_id=project_id,
                trace_id=str(data.get("trace_id", f"trace-{uuid4().hex}")),
                paper_ref=str(data.get("paper_ref", "")),
                code_ref=str(data.get("code_ref", "")),
                code_revision=int(data.get("code_revision", 1)),
                relation_type=str(data.get("relation_type", "supports")),
                confidence=float(data.get("confidence", 0)),
                evidence_json=data.get("evidence", []),
                rationale=str(data.get("rationale", "")),
                # "proposed" is the contract's initial status (ALLOWED_TRACE_STATUSES);
                # "pending" is only tolerated for legacy rows and is not a value the
                # workbench filters on.
                status=str(data.get("status", "proposed")),
                fingerprint=_importable_fingerprint(session, data, payload.public_id),
            )
            _apply_trace_fields(session, link, data)
            session.add(link)
    elif payload.entity_type == "paper_target":
        _import_paper_target(session, project_id, payload)
    elif payload.entity_type == "code_target":
        _import_code_target(session, project_id, payload)
    elif payload.entity_type == "agent_conversation":
        data = payload.payload
        existing_conversation = session.exec(
            select(AgentConversation).where(AgentConversation.public_id == payload.public_id)
        ).first()
        if existing_conversation is None:
            session.add(
                AgentConversation(
                    public_id=payload.public_id,
                    version=payload.version,
                    project_id=project_id,
                    title=str(data.get("title", "云端会话")),
                    status=str(data.get("status", "active")),
                    summary=str(data.get("summary", "")),
                )
            )
    elif payload.entity_type == "agent_message":
        data = payload.payload
        conversation_public_id = str(data.get("conversation_public_id", uuid4()))
        conversation = session.exec(
            select(AgentConversation).where(AgentConversation.public_id == conversation_public_id)
        ).first()
        if conversation is None:
            conversation = AgentConversation(
                public_id=conversation_public_id,
                project_id=project_id,
                title="云端会话",
            )
            session.add(conversation)
            session.flush()
        if not session.exec(
            select(AgentMessage).where(AgentMessage.public_id == payload.public_id)
        ).first():
            session.add(
                AgentMessage(
                    public_id=payload.public_id,
                    version=payload.version,
                    conversation_id=conversation.conversation_id,
                    project_id=project_id,
                    role=str(data.get("role", "assistant")),
                    content=str(data.get("content", "")),
                    citations_json=data.get("citations", []),
                    metadata_json=data.get("metadata", {}),
                )
            )
    elif payload.entity_type == "agent_run":
        data = payload.payload
        conversation_public_id = str(data.get("conversation_public_id", uuid4()))
        conversation = session.exec(
            select(AgentConversation).where(AgentConversation.public_id == conversation_public_id)
        ).first()
        if conversation is None:
            conversation = AgentConversation(
                public_id=conversation_public_id,
                project_id=project_id,
                title="云端会话",
            )
            session.add(conversation)
            session.flush()
        if not session.exec(
            select(AgentRun).where(AgentRun.public_id == payload.public_id)
        ).first():
            session.add(
                AgentRun(
                    public_id=payload.public_id,
                    version=payload.version,
                    conversation_id=conversation.conversation_id,
                    project_id=project_id,
                    status=str(data.get("status", "completed")),
                    provider_name=str(data.get("provider_name", "")),
                    model_name=str(data.get("model_name", "")),
                    step_count=int(data.get("step_count", 0)),
                )
            )
    elif payload.entity_type == "agent_run_event":
        data = payload.payload
        conversation_public_id = str(data.get("conversation_public_id", uuid4()))
        conversation = session.exec(
            select(AgentConversation).where(AgentConversation.public_id == conversation_public_id)
        ).first()
        if conversation is None:
            conversation = AgentConversation(
                public_id=conversation_public_id,
                project_id=project_id,
                title="云端会话",
            )
            session.add(conversation)
            session.flush()
        run_public_id = str(data.get("run_public_id", uuid4()))
        run = session.exec(select(AgentRun).where(AgentRun.public_id == run_public_id)).first()
        if run is None:
            run = AgentRun(
                public_id=run_public_id,
                conversation_id=conversation.conversation_id,
                project_id=project_id,
                status="completed",
            )
            session.add(run)
            session.flush()
        if not session.exec(
            select(AgentRunEvent).where(AgentRunEvent.public_id == payload.public_id)
        ).first():
            session.add(
                AgentRunEvent(
                    public_id=payload.public_id,
                    version=payload.version,
                    run_id=run.run_id,
                    conversation_id=conversation.conversation_id,
                    project_id=project_id,
                    sequence=int(data.get("sequence", 1)),
                    event_type=str(data.get("event_type", "cloud.event")),
                    payload_json=data.get("payload", {}),
                )
            )
    elif payload.entity_type == "agent_memory":
        data = payload.payload
        content = str(data.get("content", ""))
        memory_conversation_id = data.get("conversation_public_id")
        conversation = None
        if isinstance(memory_conversation_id, str):
            conversation = session.exec(
                select(AgentConversation).where(
                    AgentConversation.public_id == memory_conversation_id
                )
            ).first()
            if conversation is None:
                conversation = AgentConversation(
                    public_id=memory_conversation_id,
                    project_id=project_id,
                    title="云端会话",
                )
                session.add(conversation)
            session.flush()
        if not session.exec(
            select(AgentMemory).where(AgentMemory.public_id == payload.public_id)
        ).first():
            session.add(
                AgentMemory(
                    public_id=payload.public_id,
                    version=payload.version,
                    project_id=project_id,
                    conversation_id=conversation.conversation_id if conversation else None,
                    scope=str(data.get("scope", "project")),
                    kind=str(data.get("kind", "fact")),
                    content=content,
                    importance=float(data.get("importance", 0.5)),
                    source_json=data.get("source", {}),
                    fingerprint=hashlib.sha256(
                        f"cloud:{project_id}:{payload.public_id}:{content}".encode()
                    ).hexdigest(),
                )
            )
    session.commit()


@router.put("/local-sync/projects/{project_id}/imports/code-edit/{public_id}", status_code=204)
async def import_cloud_code_edit(
    project_id: int,
    public_id: str,
    request: Request,
    repository_public_id: str,
    file_path: str,
    repository_revision: int,
    session: Session = Depends(get_session),
) -> None:
    get_project_or_404(project_id, session)
    project = session.get(Project, project_id)
    unresolved = (
        session.exec(
            select(LocalSyncConflict).where(
                LocalSyncConflict.workspace_id == project.cloud_workspace_id,
                LocalSyncConflict.entity_type == "code_edit",
                LocalSyncConflict.entity_public_id == public_id,
                LocalSyncConflict.status == "unresolved",
            )
        ).first()
        if project and project.cloud_workspace_id
        else None
    )
    if unresolved is not None:
        return
    repository = session.exec(
        select(CodeRepository).where(
            CodeRepository.project_id == project_id,
            CodeRepository.public_id == repository_public_id,
        )
    ).first()
    if repository is None:
        raise HTTPException(status_code=409, detail="Repository must be imported first")
    content = (await request.body()).decode("utf-8")
    repository_key = repository.id or Path(repository.storage_path).stem
    edits_root = (
        Path(settings.upload_root) / f"project-{project_id}" / "code-edits" / str(repository_key)
    )
    save_repository_file(repository.storage_path, edits_root, file_path, content)
    repository.revision = max(repository.revision, repository_revision)
    repository.analysis_status = "stale"
    repository.analysis_error = None
    repository.updated_at = utc_now()
    session.add(repository)
    session.commit()


def _apply_remote_conflict_value(
    session: Session, conflict: LocalSyncConflict, remote: dict
) -> None:
    version = int(remote.get("version", 1))
    if conflict.entity_type == "project":
        entity = session.exec(
            select(Project).where(Project.public_id == conflict.entity_public_id)
        ).first()
        if entity is not None:
            entity.name = str(remote.get("name", entity.name))
            entity.description = str(remote.get("description", entity.description))
            entity.sync_mode = str(remote.get("sync_mode", entity.sync_mode))
            entity.agent_history_sync = bool(
                remote.get("agent_history_sync", entity.agent_history_sync)
            )
            entity.agent_deep_thinking = bool(
                remote.get("agent_deep_thinking", entity.agent_deep_thinking)
            )
            entity.version = version
            entity.updated_at = utc_now()
            session.add(entity)
    elif conflict.entity_type == "trace_link":
        entity = session.exec(
            select(TraceLink).where(TraceLink.public_id == conflict.entity_public_id)
        ).first()
        if entity is not None:
            for field in ("relation_type", "rationale", "status"):
                if field in remote:
                    setattr(entity, field, remote[field])
            if "confidence" in remote:
                entity.confidence = float(remote["confidence"])
            if "evidence" in remote and isinstance(remote["evidence"], list):
                entity.evidence_json = remote["evidence"]
            entity.version = version
            entity.updated_at = utc_now()
            session.add(entity)
    elif conflict.entity_type in {"paper_document", "code_repository"}:
        model = PaperDocument if conflict.entity_type == "paper_document" else CodeRepository
        entity = session.exec(
            select(model).where(model.public_id == conflict.entity_public_id)
        ).first()
        if entity is not None:
            entity.version = version
            entity.blob_id = remote.get("blob_id")
            session.add(entity)


def _adopt_workspace_device(session: Session, workspace_id: str, device_id: str) -> bool:
    """Re-point a workspace's local sync state (and any pending outbox ops) to the
    given device.

    ``LocalSyncState.device_id`` is per-install-local: an install must always sync
    as its CURRENT auth device. Device ids rotate across logins (a fresh login
    without a persisted id mints a new device), which would otherwise strand a
    previously-enabled workspace on a dead device — the cloud then rejects blob
    uploads (409 unbound device) and pushes (403 invalid sync device). Realigning
    the state and the pending outbox to the current device keeps sync working and
    is always safe because this state is local to a single install.
    """
    state = session.get(LocalSyncState, workspace_id)
    if state is None or state.device_id == device_id:
        return False
    state.device_id = device_id
    session.add(state)
    pending = session.exec(
        select(LocalSyncOutbox).where(
            LocalSyncOutbox.workspace_id == workspace_id,
            LocalSyncOutbox.status == "pending",
        )
    ).all()
    for operation in pending:
        operation.device_id = device_id
        session.add(operation)
    return True


@router.post("/local-sync/device/adopt")
def adopt_workspace_device(
    payload: LocalDeviceAdopt, session: Session = Depends(get_session)
) -> dict:
    changed = _adopt_workspace_device(session, payload.workspace_id, payload.device_id)
    session.commit()
    return {"changed": changed}


@router.post("/local-sync/backfill")
def backfill_incomplete_sync(
    workspace_id: str,
    session: Session = Depends(get_session),
) -> dict:
    """Repair projects that synced before the protocol covered the current domain.

    Two things are wrong with any project enabled before this release, and neither heals on
    its own because nothing re-touches an entity that has not changed:

    * ``paper_target`` / ``code_target`` were never pushed — the cloud copy has no anchors.
    * ``trace_link`` was pushed with 8 of its ~20 fields, so the cloud copy is missing
      relevance, the confidence split, uncertainty, model info, score basis and provenance.
      Any device downloading it gets ``relevance=0`` / ``source="static"``.

    Re-enqueuing with the current payload builders fixes both. Anchors go in at
    ``base_version=0`` (they are new to the cloud); trace_links go in at their current local
    version, which is the cloud version for anything that previously pushed successfully
    (``apply_push_results`` writes the server's version back), so the optimistic lock holds
    instead of conflicting.

    Idempotent in the sense that matters: running it twice enqueues the same upserts again,
    and a duplicate upsert of identical content is a no-op server-side.
    """

    state = session.get(LocalSyncState, workspace_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Workspace has no local sync state")
    projects = session.exec(
        select(Project).where(
            Project.cloud_workspace_id == workspace_id,
            Project.sync_mode == "cloud_enabled",
        )
    ).all()

    counts = {"projects": 0, "paper_target": 0, "code_target": 0, "trace_link": 0}
    for project in projects:
        counts["projects"] += 1
        for paper_target in session.exec(
            select(PaperTarget).where(PaperTarget.project_id == project.id)
        ).all():
            record_local_operation(
                session,
                project,
                "paper_target",
                paper_target.public_id,
                paper_target_payload(project, paper_target, session=session),
                base_version=0,
            )
            counts["paper_target"] += 1
        for code_target in session.exec(
            select(CodeTarget).where(CodeTarget.project_id == project.id)
        ).all():
            record_local_operation(
                session,
                project,
                "code_target",
                code_target.public_id,
                code_target_payload(project, code_target, session=session),
                base_version=0,
            )
            counts["code_target"] += 1
        for link in session.exec(
            select(TraceLink).where(TraceLink.project_id == project.id)
        ).all():
            record_local_operation(
                session,
                project,
                "trace_link",
                link.public_id,
                trace_payload(project, link, session=session),
                base_version=link.version,
            )
            counts["trace_link"] += 1
    session.commit()
    return counts


@router.post("/local-sync/repair-imported-papers")
def repair_imported_papers(session: Session = Depends(get_session)) -> dict:
    """Re-parse papers that were imported before the import path used the real parser.

    ``import_cloud_file`` returns early when the incoming version is not newer, so a paper
    already on disk is never re-imported and never re-parsed — it would stay stamped
    ``parser="cloud-import"`` with an empty ``content_hash`` forever, permanently serving
    fallback markdown even after this device gained a working MinerU configuration.

    Identified by the old marker rather than by an empty ``content_hash`` alone, so a paper
    still mid-parse (``pending-import``, hash not written yet) is not restarted.
    """

    broken = session.exec(
        select(PaperDocument).where(PaperDocument.parser == "cloud-import")
    ).all()
    scheduled = []
    for document in broken:
        if not Path(document.storage_path).exists():
            # The PDF is gone; a re-parse has nothing to read. Re-downloading is the
            # cloud-import path's job, not this repair's.
            continue
        document.parse_status = "running"
        document.parser = "pending-import"
        document.parser_version = "placeholder"
        document.content_hash = ""
        session.add(document)
        scheduled.append((document.project_id, document.public_id))
    session.commit()
    for project_id, public_id in scheduled:
        schedule_paper_reparse(project_id, public_id)
    return {"found": len(broken), "scheduled": len(scheduled)}


@router.get("/local-sync/state")
def read_sync_state(workspace_id: str, session: Session = Depends(get_session)) -> dict:
    state = session.get(LocalSyncState, workspace_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Local sync state not found")
    return {
        "workspace_id": state.workspace_id,
        "device_id": state.device_id,
        "last_pulled_seq": state.last_pulled_seq,
    }


@router.post("/projects/{project_id}/sync/enable")
def enable_project_sync(
    project_id: int,
    payload: LocalSyncEnable,
    session: Session = Depends(get_session),
) -> dict:
    project = get_project_or_404(project_id, session)
    if project.sync_mode not in {"local_only", "cloud_paused"}:
        raise HTTPException(status_code=409, detail="Project already has a cloud binding")
    state = session.get(LocalSyncState, payload.workspace_id)
    if state is None:
        state = LocalSyncState(workspace_id=payload.workspace_id, device_id=payload.device_id)
    elif state.device_id != payload.device_id:
        # The workspace was previously bound to a different local device id. Since
        # device ids rotate across logins, adopt the current device (realigning
        # any pending outbox ops) instead of hard-failing the enable.
        _adopt_workspace_device(session, payload.workspace_id, payload.device_id)
    project.cloud_workspace_id = payload.workspace_id
    project.sync_mode = "cloud_enabled"
    project.agent_history_sync = payload.agent_history_sync
    session.add(state)
    session.add(project)
    session.flush()
    record_local_operation(
        session,
        project,
        "project",
        project.public_id,
        project_payload(project),
        base_version=0,
    )
    for document in session.exec(
        select(PaperDocument).where(PaperDocument.project_id == project.id)
    ).all():
        record_local_operation(
            session,
            project,
            "paper_document",
            document.public_id,
            paper_payload(project, document),
            base_version=0,
        )
    for repository in session.exec(
        select(CodeRepository).where(CodeRepository.project_id == project.id)
    ).all():
        record_local_operation(
            session,
            project,
            "code_repository",
            repository.public_id,
            repository_payload(project, repository),
            base_version=0,
        )
    # Anchors before relations: a trace_link's target references resolve through the
    # target's public id, so the targets must already exist on the receiving device.
    for paper_target in session.exec(
        select(PaperTarget).where(PaperTarget.project_id == project.id)
    ).all():
        record_local_operation(
            session,
            project,
            "paper_target",
            paper_target.public_id,
            paper_target_payload(project, paper_target, session=session),
            base_version=0,
        )
    for code_target in session.exec(
        select(CodeTarget).where(CodeTarget.project_id == project.id)
    ).all():
        record_local_operation(
            session,
            project,
            "code_target",
            code_target.public_id,
            code_target_payload(project, code_target, session=session),
            base_version=0,
        )
    for link in session.exec(select(TraceLink).where(TraceLink.project_id == project.id)).all():
        record_local_operation(
            session,
            project,
            "trace_link",
            link.public_id,
            trace_payload(project, link, session=session),
            base_version=0,
        )
    if project.agent_history_sync:
        conversations = list(
            session.exec(
                select(AgentConversation).where(AgentConversation.project_id == project.id)
            ).all()
        )
        conversation_public_ids = {
            conversation.conversation_id: conversation.public_id for conversation in conversations
        }
        for conversation in conversations:
            record_local_operation(
                session,
                project,
                "agent_conversation",
                conversation.public_id,
                {
                    "project_public_id": project.public_id,
                    "title": conversation.title,
                    "status": conversation.status,
                    "summary": conversation.summary,
                    "created_at": conversation.created_at.isoformat(),
                },
                base_version=0,
            )
        for message in session.exec(
            select(AgentMessage).where(AgentMessage.project_id == project.id)
        ).all():
            record_local_operation(
                session,
                project,
                "agent_message",
                message.public_id,
                {
                    "project_public_id": project.public_id,
                    "conversation_public_id": conversation_public_ids.get(message.conversation_id),
                    "role": message.role,
                    "content": (
                        message.content if len(message.content.encode("utf-8")) <= 32 * 1024 else ""
                    ),
                    "citations": message.citations_json,
                    "metadata": message.metadata_json,
                    "requires_blob": len(message.content.encode("utf-8")) > 32 * 1024,
                    "filename": f"{message.public_id}.txt",
                    "created_at": message.created_at.isoformat(),
                },
                base_version=0,
            )
        runs = list(session.exec(select(AgentRun).where(AgentRun.project_id == project.id)).all())
        run_public_ids = {run.run_id: run.public_id for run in runs}
        for run in runs:
            record_local_operation(
                session,
                project,
                "agent_run",
                run.public_id,
                {
                    "project_public_id": project.public_id,
                    "conversation_public_id": conversation_public_ids.get(run.conversation_id),
                    "status": run.status,
                    "provider_name": run.provider_name,
                    "model_name": run.model_name,
                    "step_count": run.step_count,
                    "created_at": run.created_at.isoformat(),
                },
                base_version=0,
            )
        for event in session.exec(
            select(AgentRunEvent).where(AgentRunEvent.project_id == project.id)
        ).all():
            record_local_operation(
                session,
                project,
                "agent_run_event",
                event.public_id,
                {
                    "project_public_id": project.public_id,
                    "run_public_id": run_public_ids.get(event.run_id),
                    "conversation_public_id": conversation_public_ids.get(event.conversation_id),
                    "sequence": event.sequence,
                    "event_type": event.event_type,
                    "payload": agent_event_payload(event.payload_json),
                    "created_at": event.created_at.isoformat(),
                },
                base_version=0,
            )
        for memory in session.exec(
            select(AgentMemory).where(AgentMemory.project_id == project.id)
        ).all():
            record_local_operation(
                session,
                project,
                "agent_memory",
                memory.public_id,
                {
                    "project_public_id": project.public_id,
                    "conversation_public_id": conversation_public_ids.get(
                        memory.conversation_id or ""
                    ),
                    "scope": memory.scope,
                    "kind": memory.kind,
                    "content": memory.content,
                    "importance": memory.importance,
                    "source": memory.source_json,
                },
                base_version=0,
            )
    session.commit()
    return {"public_id": project.public_id, "sync_mode": project.sync_mode}


@router.patch("/projects/{project_id}/sync")
def patch_project_sync(
    project_id: int,
    payload: LocalSyncModePatch,
    session: Session = Depends(get_session),
) -> dict:
    project = get_project_or_404(project_id, session)
    if payload.sync_mode != "local_only" and not project.cloud_workspace_id:
        raise HTTPException(status_code=409, detail="Project has no cloud binding")
    # Pausing is device-local. It must never mutate the cloud project's global state.
    if payload.sync_mode in {"cloud_detached", "local_only"}:
        if project.cloud_workspace_id:
            pending = session.exec(
                select(LocalSyncOutbox).where(
                    LocalSyncOutbox.workspace_id == project.cloud_workspace_id,
                    LocalSyncOutbox.status == "pending",
                )
            ).all()
            for operation in pending:
                belongs_to_project = (
                    operation.entity_public_id == project.public_id
                    if operation.entity_type == "project"
                    else operation.payload_json.get("project_public_id") == project.public_id
                )
                if belongs_to_project:
                    operation.status = "suppressed"
                    session.add(operation)
        project.sync_mode = "local_only"
        project.cloud_workspace_id = None
    else:
        project.sync_mode = payload.sync_mode
    session.add(project)
    session.commit()
    return {"public_id": project.public_id, "sync_mode": project.sync_mode}


@router.patch("/projects/{project_id}/agent-history-sync")
def patch_agent_history_sync(
    project_id: int,
    payload: LocalAgentHistoryPatch,
    session: Session = Depends(get_session),
) -> dict:
    project = get_project_or_404(project_id, session)
    previous_version = project.version
    project.agent_history_sync = payload.enabled
    project.version += 1
    if not payload.enabled and project.cloud_workspace_id:
        pending_agent_operations = session.exec(
            select(LocalSyncOutbox).where(
                LocalSyncOutbox.workspace_id == project.cloud_workspace_id,
                LocalSyncOutbox.status == "pending",
                LocalSyncOutbox.entity_type.like("agent_%"),
            )
        ).all()
        for operation in pending_agent_operations:
            operation.status = "suppressed"
            session.add(operation)
    record_local_operation(
        session,
        project,
        "project",
        project.public_id,
        {"agent_history_sync": payload.enabled},
        base_version=previous_version,
    )
    session.add(project)
    session.commit()
    return {"agent_history_sync": project.agent_history_sync}


@router.get("/local-sync/outbox")
def read_outbox(workspace_id: str, session: Session = Depends(get_session)) -> dict:
    rows = list(
        session.exec(
            select(LocalSyncOutbox)
            .where(
                LocalSyncOutbox.workspace_id == workspace_id, LocalSyncOutbox.status == "pending"
            )
            .order_by(LocalSyncOutbox.created_at)
            .limit(100)
        ).all()
    )
    enabled_projects = {
        project.public_id
        for project in session.exec(
            select(Project).where(
                Project.cloud_workspace_id == workspace_id,
                Project.sync_mode == "cloud_enabled",
            )
        ).all()
    }
    rows = [
        item
        for item in rows
        if (
            item.entity_public_id in enabled_projects
            if item.entity_type == "project"
            else item.payload_json.get("project_public_id") in enabled_projects
        )
    ]
    return {
        "operations": [
            {
                "workspace_id": item.workspace_id,
                "device_id": item.device_id,
                "client_operation_id": item.client_operation_id,
                "supersedes_operation_id": item.supersedes_operation_id,
                "entity_type": item.entity_type,
                "entity_public_id": item.entity_public_id,
                "operation": item.operation,
                "base_version": item.base_version,
                "payload": scrub_forbidden_keys(item.payload_json),
            }
            for item in rows
        ]
    }


@router.post("/local-sync/outbox/results", status_code=204)
def apply_push_results(payload: LocalSyncResults, session: Session = Depends(get_session)) -> None:
    for result in payload.results:
        item = session.get(LocalSyncOutbox, result.client_operation_id)
        if item is None:
            continue
        duplicate_of_applied = result.status == "duplicate" and result.workspace_seq is not None
        if result.status == "applied" or duplicate_of_applied:
            item.status = "completed"
            model_by_type = {
                "project": Project,
                "paper_document": PaperDocument,
                "code_repository": CodeRepository,
                "paper_target": PaperTarget,
                "code_target": CodeTarget,
                "trace_link": TraceLink,
                "agent_conversation": AgentConversation,
                "agent_message": AgentMessage,
                "agent_run": AgentRun,
                "agent_run_event": AgentRunEvent,
                "agent_memory": AgentMemory,
            }
            model = model_by_type.get(item.entity_type)
            if model is not None and result.entity_version:
                entity = session.exec(
                    select(model).where(model.public_id == item.entity_public_id)
                ).first()
                if entity is not None:
                    entity.version = result.entity_version
                    session.add(entity)
        elif item.entity_type in MACHINE_DERIVED_TYPES:
            # Anchors are recomputed deterministically from the same artifact, so a version
            # race between two devices has no human decision in it. Surfacing it in the
            # conflict centre would bury the real ones (trace decisions, file versions)
            # under noise. Drop our operation and let the next pull deliver the server's.
            item.status = "superseded"
        else:
            item.status = "conflict"
            session.add(
                LocalSyncConflict(
                    client_operation_id=item.client_operation_id,
                    workspace_id=item.workspace_id,
                    entity_type=item.entity_type,
                    entity_public_id=item.entity_public_id,
                    local_payload_json=item.payload_json,
                    remote_payload_json=result.remote or {},
                )
            )
        session.add(item)
    session.commit()


@router.post("/local-sync/events", status_code=204)
def apply_remote_events(payload: RemoteSyncEvents, session: Session = Depends(get_session)) -> None:
    state = session.get(LocalSyncState, payload.workspace_id)
    if state is None or state.device_id != payload.device_id:
        raise HTTPException(status_code=403, detail="Unknown local sync binding")
    for event in payload.events:
        if session.get(LocalSyncInbox, event.event_id):
            continue
        unresolved = session.exec(
            select(LocalSyncConflict).where(
                LocalSyncConflict.workspace_id == payload.workspace_id,
                LocalSyncConflict.entity_type == event.entity_type,
                LocalSyncConflict.entity_public_id == event.entity_public_id,
                LocalSyncConflict.status == "unresolved",
            )
        ).first()
        if event.operation == "delete" and event.entity_type != "project" and unresolved is None:
            model_by_type = {
                "paper_document": PaperDocument,
                "code_repository": CodeRepository,
                "paper_target": PaperTarget,
                "code_target": CodeTarget,
                "trace_link": TraceLink,
                "agent_message": AgentMessage,
                "agent_run_event": AgentRunEvent,
                "agent_memory": AgentMemory,
                "agent_run": AgentRun,
                "agent_conversation": AgentConversation,
            }
            model = model_by_type.get(event.entity_type)
            if model is not None:
                key_field = {
                    "paper_document": PaperDocument.public_id,
                    "code_repository": CodeRepository.public_id,
                    "paper_target": PaperTarget.public_id,
                    "code_target": CodeTarget.public_id,
                    "trace_link": TraceLink.public_id,
                    "agent_message": AgentMessage.public_id,
                    "agent_run_event": AgentRunEvent.public_id,
                    "agent_memory": AgentMemory.public_id,
                    "agent_run": AgentRun.public_id,
                    "agent_conversation": AgentConversation.public_id,
                }[event.entity_type]
                entity = session.exec(
                    select(model).where(key_field == event.entity_public_id)
                ).first()
                if entity is not None:
                    session.delete(entity)
        if event.entity_type == "project":
            project = session.exec(
                select(Project).where(Project.public_id == event.entity_public_id)
            ).first()
            if (
                project is not None
                and event.entity_version > project.version
                and unresolved is None
            ):
                if event.operation == "delete":
                    # Cloud deletion affects every bound device, but must never
                    # destroy the Desktop copy. Preserve it as an ordinary local
                    # project and remove only this machine's cloud binding.
                    project.sync_mode = "local_only"
                    project.cloud_workspace_id = None
                    project.deleted_at = None
                else:
                    project.name = str(event.payload.get("name", project.name))
                    project.description = str(event.payload.get("description", project.description))
                    # sync_mode is a property of this Desktop binding. A Web or
                    # second-device metadata event must not resume this device.
                    project.agent_history_sync = bool(
                        event.payload.get("agent_history_sync", project.agent_history_sync)
                    )
                    project.agent_deep_thinking = bool(
                        event.payload.get("agent_deep_thinking", project.agent_deep_thinking)
                    )
                project.version = event.entity_version
                project.updated_at = utc_now()
                session.add(project)
        session.add(
            LocalSyncInbox(
                event_id=event.event_id,
                workspace_id=payload.workspace_id,
                workspace_seq=event.workspace_seq,
                entity_type=event.entity_type,
                entity_public_id=event.entity_public_id,
                operation=event.operation,
                entity_version=event.entity_version,
                payload_json=event.payload,
            )
        )
        state.last_pulled_seq = max(state.last_pulled_seq, event.workspace_seq)
    state.updated_at = utc_now()
    session.add(state)
    session.commit()


@router.get("/local-sync/conflicts")
def list_conflicts(workspace_id: str, session: Session = Depends(get_session)) -> list[dict]:
    rows = session.exec(
        select(LocalSyncConflict).where(
            LocalSyncConflict.workspace_id == workspace_id,
            LocalSyncConflict.status == "unresolved",
        )
    ).all()
    return [
        {
            "conflict_id": item.conflict_id,
            "entity_type": item.entity_type,
            "entity_public_id": item.entity_public_id,
            "local": item.local_payload_json,
            "remote": item.remote_payload_json,
        }
        for item in rows
    ]


@router.put("/local-sync/conflicts/{conflict_id}/blob", status_code=204)
async def replace_conflicted_local_blob(
    conflict_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> None:
    conflict = session.get(LocalSyncConflict, conflict_id)
    if conflict is None or conflict.status != "unresolved":
        raise HTTPException(status_code=404, detail="Conflict not found")
    if conflict.entity_type == "paper_document":
        entity = session.exec(
            select(PaperDocument).where(PaperDocument.public_id == conflict.entity_public_id)
        ).first()
    elif conflict.entity_type == "code_repository":
        entity = session.exec(
            select(CodeRepository).where(CodeRepository.public_id == conflict.entity_public_id)
        ).first()
    else:
        raise HTTPException(status_code=409, detail="Conflict has no file content")
    if entity is None:
        raise HTTPException(status_code=404, detail="Local artifact not found")
    content = await request.body()
    if not content:
        raise HTTPException(status_code=422, detail="Replacement file is empty")
    destination = Path(entity.storage_path)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.incoming")
    temporary.write_bytes(content)
    os.replace(temporary, destination)


@router.post("/local-sync/conflicts/{conflict_id}/resolve", status_code=204)
def resolve_conflict(
    conflict_id: str,
    payload: LocalConflictResolve,
    session: Session = Depends(get_session),
) -> None:
    conflict = session.get(LocalSyncConflict, conflict_id)
    if conflict is None or conflict.status != "unresolved":
        raise HTTPException(status_code=404, detail="Conflict not found")
    outbox = session.get(LocalSyncOutbox, conflict.client_operation_id)
    if outbox is None:
        raise HTTPException(status_code=409, detail="Conflicted operation is unavailable")
    remote_version = int(conflict.remote_payload_json.get("version", 0))
    if payload.resolution == "use_remote":
        _apply_remote_conflict_value(session, conflict, conflict.remote_payload_json)
        outbox.status = "completed"
    else:
        replacement = LocalSyncOutbox(
            supersedes_operation_id=outbox.client_operation_id,
            workspace_id=outbox.workspace_id,
            device_id=outbox.device_id,
            entity_type=outbox.entity_type,
            entity_public_id=outbox.entity_public_id,
            operation=outbox.operation,
            base_version=remote_version,
            payload_json=payload.merged_payload or conflict.local_payload_json,
        )
        if payload.resolution == "keep_both":
            if conflict.entity_type not in {"paper_document", "code_repository"}:
                raise HTTPException(status_code=409, detail="keep_both is only valid for files")
            model = PaperDocument if conflict.entity_type == "paper_document" else CodeRepository
            entity = session.exec(
                select(model).where(model.public_id == conflict.entity_public_id)
            ).first()
            if entity is None:
                raise HTTPException(status_code=404, detail="Local artifact not found")
            entity.public_id = str(uuid4())
            entity.version = 1
            replacement.entity_public_id = entity.public_id
            replacement.base_version = 0
            session.add(entity)
        outbox.status = "superseded"
        session.add(replacement)
    conflict.status = f"resolved_{payload.resolution}"
    session.add(outbox)
    session.add(conflict)
    session.commit()


@router.put("/local-sync/projects/{project_id}/diagram-imports/{public_id}", status_code=204)
async def import_cloud_diagram(
    project_id: int,
    public_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> None:
    """Restore a synced flow diagram onto a downloaded code repository.

    Overwrites the locally re-scanned base graph with the structured diagram
    (tensor graph + Agent-refined analysis) that travelled through the cloud, so
    the downloading device shows the same diagram without re-running analysis.
    """

    get_project_or_404(project_id, session)
    repository = session.exec(
        select(CodeRepository).where(CodeRepository.public_id == public_id)
    ).first()
    if repository is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    try:
        document = json.loads(await request.body())
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid diagram payload") from exc
    tensor_graph = document.get("tensor_graph")
    if isinstance(tensor_graph, dict):
        repository.tensor_graph_json = tensor_graph
    analysis = document.get("analysis")
    if isinstance(analysis, dict):
        repository.analysis_json = analysis
    repository.analysis_revision = int(document.get("analysis_revision", 0) or 0)
    repository.analysis_version = str(document.get("analysis_version", "") or "")
    repository.analysis_status = str(document.get("analysis_status", "succeeded") or "succeeded")
    repository.analysis_updated_at = utc_now()
    repository.updated_at = utc_now()
    session.add(repository)
    session.commit()


@router.get("/local-sync/diagram/{public_id}")
def read_local_sync_diagram(public_id: str, session: Session = Depends(get_session)) -> Response:
    """Serve a repository's generated flow diagram as a structured JSON blob.

    Bundles the tensor graph and the Agent-refined analysis so the diagram
    survives a round trip through the cloud without re-running analysis on the
    downloading device.
    """

    repository = session.exec(
        select(CodeRepository).where(CodeRepository.public_id == public_id)
    ).first()
    if repository is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    document = {
        "schema_version": "diagram-v1",
        "tensor_graph": repository.tensor_graph_json or {"nodes": [], "edges": []},
        "analysis": repository.analysis_json or {},
        "analysis_revision": repository.analysis_revision,
        "analysis_version": repository.analysis_version,
        "analysis_status": repository.analysis_status,
    }
    return Response(
        content=json.dumps(document, ensure_ascii=False).encode("utf-8"),
        media_type="application/json",
    )


@router.get("/local-sync/blobs/{entity_type}/{public_id}")
def read_local_sync_blob(
    entity_type: str, public_id: str, session: Session = Depends(get_session)
) -> Response:
    if entity_type == "paper_document":
        entity = session.exec(
            select(PaperDocument).where(PaperDocument.public_id == public_id)
        ).first()
    elif entity_type == "code_repository":
        entity = session.exec(
            select(CodeRepository).where(CodeRepository.public_id == public_id)
        ).first()
    elif entity_type == "code_edit":
        outbox = session.exec(
            select(LocalSyncOutbox).where(
                LocalSyncOutbox.entity_type == "code_edit",
                LocalSyncOutbox.entity_public_id == public_id,
                LocalSyncOutbox.status == "pending",
            )
        ).first()
        if outbox is None or not isinstance(outbox.payload_json.get("_upload_content"), str):
            raise HTTPException(status_code=404, detail="Local blob not found")
        return Response(
            content=outbox.payload_json["_upload_content"].encode("utf-8"),
            media_type="application/octet-stream",
        )
    elif entity_type == "agent_message":
        message = session.exec(
            select(AgentMessage).where(AgentMessage.public_id == public_id)
        ).first()
        if message is None:
            raise HTTPException(status_code=404, detail="Local blob not found")
        return Response(content=message.content.encode("utf-8"), media_type="text/plain")
    else:
        raise HTTPException(status_code=404, detail="Local blob not found")
    if entity is None:
        raise HTTPException(status_code=404, detail="Local blob not found")
    return FileResponse(entity.storage_path, filename=entity.filename)
