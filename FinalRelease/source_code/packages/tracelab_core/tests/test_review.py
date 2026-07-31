from dataclasses import dataclass
from pathlib import Path

from tracelab_core.review import (
    _parse_code_target,
    candidates_to_links,
    load_links,
    mark_stale,
    save_links,
    update_link_status,
    update_links_batch,
)
from tracelab_core.workspace import ensure_layout, read_json


def test_parse_code_target_line_range() -> None:
    path, start, end = _parse_code_target("nn.py:10-20", "nn.py::Foo")
    assert path == "nn.py"
    assert start == 10
    assert end == 20


def test_parse_code_target_symbol_fallback() -> None:
    path, start, end = _parse_code_target("nn.py::MultiHeadAttention", "nn.py::MultiHeadAttention")
    assert path == "nn.py"
    assert start == 1
    assert end == 1


def test_parse_code_target_other_fallbacks() -> None:
    assert _parse_code_target("pkg/model.py", "Model") == ("pkg/model.py", 1, 1)
    assert _parse_code_target("pkg/model.py::Model", "Model") == ("pkg/model.py", 1, 1)
    assert _parse_code_target("Model", "pkg/model.py::Model") == ("pkg/model.py", 1, 1)
    assert _parse_code_target("", "") == ("unknown.py", 1, 1)


def test_candidates_to_links_tolerates_llm_symbol_refs() -> None:
    links = candidates_to_links(
        [
            {
                "paper_block_id": "p1",
                "code_symbol_id": "nn.py::MultiHeadAttention",
                "relation_type": "implements",
                "confidence": 0.9,
                "rationale": "match",
                "evidence": [
                    {"side": "paper", "ref": "p1", "quote": "attention"},
                    {"side": "code", "ref": "nn.py::MultiHeadAttention", "quote": "class"},
                ],
            }
        ],
        source="llm",
    )
    assert len(links) == 1
    assert links[0]["code_target"]["path"] == "nn.py"
    assert links[0]["code_target"]["line_start"] == 1


@dataclass
class Candidate:
    paper_block_id: str
    code_symbol_id: str
    relation_type: str
    confidence: float
    rationale: str
    evidence: list[dict[str, str]]


def test_candidates_to_links_supports_dataclasses_and_defaults() -> None:
    dataclass_link, default_link = candidates_to_links(
        [
            Candidate(
                "paper-1",
                "model.py::Model",
                "implements",
                0.8,
                "same operation",
                [
                    {"side": "paper", "quote": "attention equation"},
                    {"side": "code", "ref": "model.py:4", "quote": "attention()"},
                ],
            ),
            {"paper_block_id": "paper-2", "code_symbol_id": "train.py::step"},
        ],
        source="agent",
    )
    assert dataclass_link["source"] == "agent"
    assert dataclass_link["paper_target"]["quote"] == "attention equation"
    assert dataclass_link["code_target"]["line_start"] == 4
    assert dataclass_link["code_target"]["line_end"] == 4
    assert default_link["relation_type"] == "mentions"
    assert default_link["confidence"] == 0.0
    assert default_link["rationale"] == ""
    assert default_link["paper_target"]["quote"] == ""


def _links_fixture(tmp_path: Path):
    paths = ensure_layout(tmp_path)
    links = [
        {"id": "one", "status": "proposed", "revision": "old"},
        {"id": "two", "status": "accepted", "revision": "old"},
        {"id": "three", "status": "proposed"},
    ]
    save_links(paths, links)
    return paths


def test_load_and_save_links_handle_missing_and_empty_payload(tmp_path: Path) -> None:
    paths = ensure_layout(tmp_path)
    paths.links_json.unlink()
    assert load_links(paths) == []
    paths.links_json.write_text("null", encoding="utf-8")
    assert load_links(paths) == []

    save_links(paths, [{"id": "one"}])
    payload = read_json(paths.links_json)
    assert payload["links"] == [{"id": "one"}]
    assert payload["updated_at"].endswith("Z")


def test_update_link_status_updates_match(tmp_path: Path) -> None:
    paths = _links_fixture(tmp_path)
    updated = update_link_status(paths, "one", "accepted")

    assert updated is not None
    assert updated["status"] == "accepted"
    assert updated["reviewed_at"].endswith("Z")
    assert load_links(paths)[1]["status"] == "accepted"


def test_update_link_status_returns_none_without_rewriting(tmp_path: Path) -> None:
    paths = _links_fixture(tmp_path)
    before = paths.links_json.read_text(encoding="utf-8")

    assert update_link_status(paths, "missing", "rejected") is None
    assert paths.links_json.read_text(encoding="utf-8") == before


def test_update_links_batch_by_trimmed_ids(tmp_path: Path) -> None:
    paths = _links_fixture(tmp_path)
    result = update_links_batch(paths, "rejected", link_ids=[" one ", "", "missing"])

    assert result["updated_count"] == 1
    assert result["skipped_count"] == 0
    assert result["updated"][0]["id"] == "one"
    assert result["updated"][0]["reviewed_at"].endswith("Z")


def test_update_links_batch_all_proposed(tmp_path: Path) -> None:
    paths = _links_fixture(tmp_path)
    result = update_links_batch(paths, "accepted", link_ids=["two"], all_proposed=True)

    assert result["updated_count"] == 2
    assert {item["id"] for item in result["updated"]} == {"one", "three"}


def test_update_links_batch_reports_all_unknown_ids(tmp_path: Path) -> None:
    paths = _links_fixture(tmp_path)
    result = update_links_batch(paths, "accepted", link_ids=["missing", "also-missing"])

    assert result == {"updated_count": 0, "skipped_count": 2, "updated": []}


def test_mark_stale_changes_only_old_proposals_and_sets_revision(tmp_path: Path) -> None:
    paths = _links_fixture(tmp_path)
    assert mark_stale(paths, "new") == 1

    links = load_links(paths)
    assert [item["status"] for item in links] == ["stale", "accepted", "proposed"]
    assert {item["revision"] for item in links} == {"new"}


def test_mark_stale_does_not_create_file_for_empty_workspace(tmp_path: Path) -> None:
    paths = ensure_layout(tmp_path)
    paths.links_json.unlink()

    assert mark_stale(paths, "new") == 0
    assert not paths.links_json.exists()
