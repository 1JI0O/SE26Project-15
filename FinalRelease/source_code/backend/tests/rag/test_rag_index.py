"""Index build, invalidation, and ranking for the three retrieval scopes."""

from collections.abc import Callable
from pathlib import Path

from sqlmodel import Session, select

from app.models.entities import (
    CodeRepository,
    IntegrationConfig,
    PaperDocument,
    Project,
    RagChunk,
    TraceLink,
)
from app.services.rag import build_index, index_status, invalidate, search, trace_examples
from app.services.rag.embeddings import (
    LocalHashingEmbedder,
    cosine,
    decode_vector,
    encode_vector,
)


def test_local_embedder_ranks_semantic_match_above_unrelated_text() -> None:
    embedder = LocalHashingEmbedder(512)
    query = embedder.embed(["loss that down-weights easy examples"])[0]
    related, unrelated = embedder.embed(
        [
            "focal loss down-weights easy negatives during training",
            "the dataloader shuffles batches across worker processes",
        ]
    )
    assert cosine(query, related) > cosine(query, unrelated)


def test_vector_roundtrip_is_lossless_within_float32() -> None:
    vector = LocalHashingEmbedder(128).embed(["attention over keys"])[0]
    restored = decode_vector(encode_vector(vector))
    assert len(restored) == len(vector)
    assert all(abs(a - b) < 1e-6 for a, b in zip(vector, restored, strict=True))


def test_cosine_of_mismatched_dimensions_is_zero_not_an_error() -> None:
    # A chunk embedded by a previous generation must not crash a search.
    assert cosine([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


def test_paper_index_build_then_semantic_search_finds_method_block(
    rag_session: Session,
    project_with_paper: Callable[[Session], Project],
) -> None:
    project = project_with_paper(rag_session)
    project_id = project.id or 0
    result = build_index(rag_session, project_id, "paper")
    assert result["status"] == "ready"
    assert result["chunk_count"] == 3

    found = search(rag_session, project_id, "paper", "loss down-weighting easy examples")
    assert found["ok"] is True
    assert found["items"][0]["ref"] == "p1-b1"
    assert found["items"][0]["page"] == 1
    assert found["items"][0]["section_path"] == ["Method", "Loss"]

    attention = search(rag_session, project_id, "paper", "query key value projections")
    assert attention["items"][0]["ref"] == "p2-b1"


def test_paper_index_is_reused_until_content_hash_changes(
    rag_session: Session,
    project_with_paper: Callable[[Session], Project],
) -> None:
    project = project_with_paper(rag_session)
    project_id = project.id or 0
    build_index(rag_session, project_id, "paper")
    assert build_index(rag_session, project_id, "paper").get("reused") is True

    paper = rag_session.exec(select(PaperDocument)).one()
    paper.content_hash = "hash-v2"
    rag_session.add(paper)
    rag_session.commit()
    rebuilt = build_index(rag_session, project_id, "paper")
    assert rebuilt.get("reused") is not True
    assert rebuilt["chunk_count"] == 3
    # The previous generation is replaced, not accumulated.
    chunks = rag_session.exec(select(RagChunk).where(RagChunk.scope == "paper")).all()
    assert {chunk.source_key for chunk in chunks} == {"hash-v2"}


def test_code_index_ranks_real_implementation_above_config_symbol(
    rag_session: Session,
    project_with_paper: Callable[[Session], Project],
    add_repository: Callable[[Session, Project, Path], CodeRepository],
    tmp_path: Path,
) -> None:
    project = project_with_paper(rag_session)
    project_id = project.id or 0
    add_repository(rag_session, project, tmp_path)
    result = build_index(rag_session, project_id, "code")
    assert result["status"] == "ready"

    found = search(rag_session, project_id, "code", "focal loss down-weighting computation")
    assert found["ok"] is True
    assert found["items"][0]["ref"] == "losses.py::FocalLoss.forward"
    assert found["items"][0]["path"] == "losses.py"
    assert found["items"][0]["line_start"] == 4


def test_search_on_missing_source_reports_reason_instead_of_raising(
    rag_session: Session,
) -> None:
    project = Project(name="Empty")
    rag_session.add(project)
    rag_session.commit()
    rag_session.refresh(project)
    result = search(rag_session, project.id or 0, "paper", "anything")
    assert result["ok"] is False
    assert result["reason"] == "rag_index_empty"
    assert result["items"] == []


def test_disabled_rag_short_circuits_build_and_search(
    rag_session: Session,
    project_with_paper: Callable[[Session], Project],
) -> None:
    project = project_with_paper(rag_session)
    project_id = project.id or 0
    rag_session.add(IntegrationConfig(id=1, rag_enabled=False))
    rag_session.commit()
    assert build_index(rag_session, project_id, "paper")["status"] == "disabled"
    result = search(rag_session, project_id, "paper", "focal loss")
    assert result["ok"] is False
    assert result["reason"] == "rag_disabled"


def test_index_status_reports_every_scope(
    rag_session: Session,
    project_with_paper: Callable[[Session], Project],
) -> None:
    project = project_with_paper(rag_session)
    project_id = project.id or 0
    build_index(rag_session, project_id, "paper")
    status = index_status(rag_session, project_id)
    assert status["enabled"] is True
    scopes = {item["scope"]: item for item in status["scopes"]}
    assert set(scopes) == {"paper", "code", "trace"}
    assert scopes["paper"]["status"] == "ready"
    assert scopes["paper"]["chunk_count"] == 3
    assert scopes["code"]["status"] == "pending"


def test_trace_scope_indexes_only_reviewed_links_and_recalls_precedents(
    rag_session: Session,
    project_with_paper: Callable[[Session], Project],
    reviewed_link: Callable[..., TraceLink],
) -> None:
    project = project_with_paper(rag_session)
    project_id = project.id or 0
    rag_session.add(
        reviewed_link(
            project_id,
            "accepted",
            "focal loss down-weights easy negatives",
            "losses.py::FocalLoss.forward",
        )
    )
    rag_session.add(
        reviewed_link(
            project_id,
            "rejected",
            "two-stage proposal generation",
            "losses.py::DataLoaderConfig.batch_size",
        )
    )
    # A still-proposed link is not precedent: nobody has judged it yet.
    rag_session.add(
        reviewed_link(project_id, "proposed", "attention over keys", "losses.py::Attn.forward")
    )
    rag_session.commit()

    result = build_index(rag_session, project_id, "trace")
    assert result["chunk_count"] == 2

    examples = trace_examples(rag_session, project_id, "focal loss easy negatives", limit=2)
    assert examples
    assert examples[0]["status"] == "accepted"
    assert "focal loss" in examples[0]["paper_quote"]
    assert all(example["status"] in {"accepted", "rejected"} for example in examples)


def test_new_review_verdict_invalidates_the_trace_index(
    rag_session: Session,
    project_with_paper: Callable[[Session], Project],
    reviewed_link: Callable[..., TraceLink],
) -> None:
    project = project_with_paper(rag_session)
    project_id = project.id or 0
    rag_session.add(
        reviewed_link(project_id, "accepted", "focal loss", "losses.py::FocalLoss.forward")
    )
    rag_session.commit()
    build_index(rag_session, project_id, "trace")

    rag_session.add(
        reviewed_link(project_id, "rejected", "unrelated claim", "losses.py::Other.method")
    )
    rag_session.commit()
    invalidate(rag_session, project_id, "trace")
    # An auto-building search picks up the new verdict without an explicit rebuild.
    result = search(rag_session, project_id, "trace", "focal loss")
    assert result["ok"] is True
    chunks = rag_session.exec(select(RagChunk).where(RagChunk.scope == "trace")).all()
    assert len(chunks) == 2
