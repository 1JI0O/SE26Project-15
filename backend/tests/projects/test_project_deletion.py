import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.api.routes.projects import router
from app.core.config import settings
from app.db.session import get_session
from app.models.entities import (
    AgentToolRequest,
    CodeRepository,
    PaperDocument,
    Project,
    TraceLink,
    utc_now,
)


def test_batch_delete_removes_related_rows_and_project_files(tmp_path: Path, monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setenv("TRACELAB_PAPER_JOB_ROOT", str(tmp_path / "paper-jobs"))

    with Session(engine) as session:
        project = Project(name="delete me")
        kept = Project(name="keep me")
        session.add(project)
        session.add(kept)
        session.commit()
        session.refresh(project)
        project_id = project.id or 0
        paper = PaperDocument(
            project_id=project_id,
            filename="paper.pdf",
            storage_path="paper.pdf",
            sections_json=[],
            paragraphs_json=[],
        )
        code = CodeRepository(
            project_id=project_id,
            filename="code.zip",
            storage_path="code.zip",
            file_tree_json=[],
            symbols_json=[],
            imports_json=[],
            pytorch_candidates_json=[],
        )
        session.add(paper)
        session.add(code)
        session.commit()
        session.refresh(paper)
        session.refresh(code)
        session.add(
            TraceLink(
                project_id=project_id,
                paper_document_id=paper.id,
                paper_ref="paragraph:1",
                code_repository_id=code.id,
                code_ref="model.py:Model",
                relation_type="implements",
            )
        )
        session.add(
            AgentToolRequest(
                project_id=project_id,
                tool_name="rerun_analysis",
                private_arguments_json={},
                parameter_summary_json={},
                expires_at=utc_now() + timedelta(minutes=5),
            )
        )
        session.commit()

    project_upload = tmp_path / "uploads" / f"project-{project_id}" / "paper"
    project_upload.mkdir(parents=True)
    (project_upload / "paper.pdf").write_bytes(b"pdf")
    jobs_root = tmp_path / "paper-jobs" / "jobs"
    jobs_root.mkdir(parents=True)
    (jobs_root / "job.json").write_text(json.dumps({"project_id": project_id}), encoding="utf-8")

    def session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/projects/batch-delete",
            json={"project_ids": [project_id, 999999, project_id]},
        )

    assert response.status_code == 200
    assert response.json() == {"deleted_ids": [project_id], "missing_ids": [999999]}
    assert not (tmp_path / "uploads" / f"project-{project_id}").exists()
    assert not (jobs_root / "job.json").exists()
    with Session(engine) as session:
        assert session.get(Project, project_id) is None
        assert session.exec(select(Project).where(Project.name == "keep me")).first() is not None
        assert session.exec(select(PaperDocument)).first() is None
        assert session.exec(select(CodeRepository)).first() is None
        assert session.exec(select(TraceLink)).first() is None
        assert session.exec(select(AgentToolRequest)).first() is None
