"""Shared fixtures for the retrieval-layer tests."""

import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from app.models.entities import CodeRepository, PaperDocument, Project, TraceLink


@pytest.fixture
def rag_session() -> Iterator[Session]:
    """An isolated in-memory database for one retrieval test."""

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _blocks() -> list[dict]:
    """Three blocks with deliberately distinct topics.

    Two are method content that should be retrievable ("focal loss", "attention"), one is
    related work that must not outrank them for a method query.
    """

    return [
        {
            "id": "p1-b1",
            "kind": "paragraph",
            "page": 1,
            "section_path": ["Method", "Loss"],
            "text": (
                "We adopt a focal loss that down-weights easy negatives so training is not "
                "dominated by the overwhelming number of background anchors in dense detection."
            ),
        },
        {
            "id": "p1-b2",
            "kind": "paragraph",
            "page": 1,
            "section_path": ["Related Work"],
            "text": (
                "Earlier detectors relied on two-stage proposal generation followed by a region "
                "classifier, which limits inference throughput on embedded hardware platforms."
            ),
        },
        {
            "id": "p2-b1",
            "kind": "paragraph",
            "page": 2,
            "section_path": ["Method", "Attention"],
            "text": (
                "Each attention head computes scaled dot-product similarity between query and "
                "key projections, then aggregates value vectors with the resulting weights."
            ),
        },
    ]


@pytest.fixture
def project_with_paper() -> Callable[[Session], Project]:
    def build(session: Session) -> Project:
        project = Project(name="RAG fixture")
        session.add(project)
        session.commit()
        session.refresh(project)
        blocks = _blocks()
        paper = PaperDocument(
            project_id=project.id or 0,
            filename="paper.pdf",
            storage_path="paper.pdf",
            title="Dense detection with focal loss",
            abstract="We propose a focal loss for dense object detection.",
            content_hash="hash-v1",
            parse_status="succeeded",
            sections_json=[],
            paragraphs_json=blocks,
            pages_json=[
                {"page_number": 1, "blocks": blocks[:2]},
                {"page_number": 2, "blocks": blocks[2:]},
            ],
        )
        session.add(paper)
        session.commit()
        return project

    return build


@pytest.fixture
def add_repository() -> Callable[[Session, Project, Path], CodeRepository]:
    """Analyzed repository with one real implementation and one config decoy."""

    def build(session: Session, project: Project, tmp_path: Path) -> CodeRepository:
        source = (
            "import torch\n"
            "\n"
            "class FocalLoss(torch.nn.Module):\n"
            "    def forward(self, pred, target):\n"
            "        p = torch.sigmoid(pred)\n"
            "        w = (1 - p) ** self.gamma\n"
            "        return -(w * target * torch.log(p)).mean()\n"
            "\n"
            "class DataLoaderConfig:\n"
            "    def batch_size(self):\n"
            "        return 16\n"
        )
        archive_path = tmp_path / "repo.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("repo/losses.py", source)
        repository = CodeRepository(
            project_id=project.id or 0,
            filename="repo.zip",
            storage_path=str(archive_path),
            analysis_status="succeeded",
            analysis_revision=1,
            file_tree_json=[{"path": "losses.py", "language": "python", "editable": True}],
            symbols_json=[
                {
                    "id": "losses.py::FocalLoss.forward",
                    "path": "losses.py",
                    "name": "forward",
                    "qualified_name": "FocalLoss.forward",
                    "kind": "method",
                    "docstring": "Down-weight easy examples when computing the loss.",
                    "line_start": 4,
                    "line_end": 7,
                },
                {
                    "id": "losses.py::DataLoaderConfig.batch_size",
                    "path": "losses.py",
                    "name": "batch_size",
                    "qualified_name": "DataLoaderConfig.batch_size",
                    "kind": "method",
                    "line_start": 10,
                    "line_end": 11,
                },
            ],
            imports_json=[],
            pytorch_candidates_json=[],
            analysis_json={"calls": []},
        )
        session.add(repository)
        session.commit()
        session.refresh(repository)
        return repository

    return build


@pytest.fixture
def reviewed_link() -> Callable[..., TraceLink]:
    def build(project_id: int, status: str, paper_quote: str, code_ref: str) -> TraceLink:
        return TraceLink(
            project_id=project_id,
            paper_ref="p1-b1",
            code_ref=code_ref,
            relation_type="implements",
            confidence=0.8,
            status=status,
            rationale=f"{status} because the computation matches",
            evidence_json=[
                {"side": "paper", "ref": "p1-b1", "quote": paper_quote},
                {"side": "code", "ref": code_ref, "quote": "w = (1 - p) ** self.gamma"},
            ],
        )

    return build
