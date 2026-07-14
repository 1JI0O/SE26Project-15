from typing import Any

from sqlmodel import Session, select

from app.db.session import engine
from app.models.entities import CodeRepository, utc_now
from app.services import workspace_service


def run_repository_analysis(
    project_id: int,
    targets: list[str],
    idempotency_key: str,
) -> dict[str, Any]:
    """Run the current repository analyzer for an approved Agent request."""

    with Session(engine) as session:
        repository = session.exec(
            select(CodeRepository)
            .where(CodeRepository.project_id == project_id)
            .order_by(CodeRepository.created_at.desc(), CodeRepository.id.desc())
        ).first()
        if repository is None:
            raise ValueError("code_repository_not_found")

        analysis = workspace_service.get_code_analysis(session, project_id)
        if analysis is None:
            raise ValueError("code_analysis_unavailable")

        repository.file_tree_json = analysis["file_tree"]
        repository.symbols_json = analysis["symbols"]
        repository.imports_json = analysis["imports"]
        repository.pytorch_candidates_json = analysis["pytorch_candidates"]
        repository.tensor_graph_json = analysis["tensor_graph"]
        repository.updated_at = utc_now()
        session.add(repository)
        session.commit()

    return {
        "job_id": f"analysis-{idempotency_key}",
        "status": "completed",
        "targets": targets,
        "summary": analysis["summary"],
    }
