"""Boundary and failure-path tests for RAG chunking and embedding providers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.services.rag import chunking, embeddings
from app.services.rag.chunking import code_chunks, paper_chunks, trace_chunks
from app.services.rag.embeddings import EmbeddingError, LocalHashingEmbedder, RemoteEmbedder


def test_paper_chunks_fall_back_to_paragraphs_and_split_long_blocks() -> None:
    text = "x" * (chunking.MAX_CHUNK_CHARS + 5)
    paper = SimpleNamespace(
        pages_json=[],
        paragraphs_json=[
            {
                "id": "long",
                "text": text,
                "section_title": "Results",
                "type": "paragraph",
                "page": 3,
            },
            {"id": "short", "text": "Figure 1."},
            {"text": "ignored because it has no identifier"},
        ],
    )

    chunks = paper_chunks(paper)

    assert len(chunks) == 2
    assert chunks[0]["text"].startswith("Results\n")
    assert chunks[0]["metadata"]["window"] == 0
    assert chunks[1]["metadata"]["window"] == 1
    assert chunks[1]["text"].endswith("x" * 205)


def test_paper_chunks_prefer_page_blocks_and_normalize_section_path() -> None:
    paper = SimpleNamespace(
        pages_json=[
            {
                "blocks": [
                    {
                        "id": "page-block",
                        "text": "A sufficiently descriptive page-level paragraph.",
                        "section_path": ["Method", None, 7],
                    },
                    "not-a-dict",
                ]
            }
        ],
        paragraphs_json=[{"id": "flat", "text": "This fallback must not be selected at all."}],
    )

    chunks = paper_chunks(paper)

    assert [item["ref"] for item in chunks] == ["page-block"]
    assert chunks[0]["metadata"]["section_path"] == ["Method", "7"]
    assert chunks[0]["metadata"]["kind"] == "text"


def test_code_chunks_filter_symbols_and_tolerate_unreadable_source() -> None:
    repository = SimpleNamespace(
        symbols_json=[
            {},
            {"id": "import", "kind": "import", "name": "os"},
            {"id": "tiny", "kind": "function", "name": "x"},
            {
                "id": "callable",
                "path": "model.py",
                "kind": "method",
                "qualified_name": "Model.forward",
                "signature": "(input)",
                "docstring": "Runs inference.",
                "calls": [{"name": "encode"}, "decode", {}, None],
                "line": 4,
                "line_end": 6,
            },
        ]
    )

    chunks = code_chunks(repository, lambda *_args: (_ for _ in ()).throw(OSError("missing")))

    assert [item["ref"] for item in chunks] == ["callable"]
    assert "Model.forward" in chunks[0]["text"]
    assert "encode decode None" in chunks[0]["text"]
    assert chunks[0]["metadata"]["line_start"] == 4


def test_code_chunks_include_source_and_limit_embedding_surface() -> None:
    repository = SimpleNamespace(
        symbols_json=[
            {
                "id": "pkg.py::run",
                "path": "pkg.py",
                "kind": "function",
                "name": "run",
                "line_start": 2,
                "line_end": 3,
            }
        ]
    )

    chunks = code_chunks(
        repository, lambda path, start, end: f"{path}:{start}-{end}\n" + "z" * 3000
    )

    assert len(chunks[0]["text"]) == chunking.MAX_CHUNK_CHARS
    assert "pkg.py:2-3" in chunks[0]["text"]


def test_trace_chunks_ignore_invalid_evidence_and_empty_links() -> None:
    empty = SimpleNamespace(evidence_json=[None, {"side": "other", "quote": "x"}])
    reviewed = SimpleNamespace(
        trace_id="trace-1",
        evidence_json=[
            None,
            {"side": "paper", "quote": "  paper evidence  "},
            {"side": "paper", "quote": "later paper evidence"},
            {"side": "code", "quote": " code evidence "},
        ],
        code_ref="model.py::run",
        rationale="matches behavior",
        status="accepted",
        relation_type="implements",
        paper_ref="block-1",
        confidence=0.9,
    )

    chunks = trace_chunks([empty, reviewed])

    assert len(chunks) == 1
    assert chunks[0]["ref"] == "trace-1"
    assert chunks[0]["metadata"]["paper_quote"] == "paper evidence"
    assert chunks[0]["metadata"]["code_quote"] == "code evidence"


def test_tokenize_and_local_embedder_cover_empty_camel_case_and_cjk() -> None:
    tokens = embeddings.tokenize("FocalLoss.forward_2 中文")
    assert {"focal", "loss", "forward", "2", "中", "文", "中文"} <= set(tokens)

    embedder = LocalHashingEmbedder(dimensions=1)
    assert embedder.dimensions == 64
    assert embedder.embed([""])[0] == [0.0] * 64
    vector = embedder.embed(["token token token"])[0]
    assert sum(value * value for value in vector) == pytest.approx(1.0)
    assert LocalHashingEmbedder(5000).dimensions == 4096


class _Response:
    def __init__(
        self, status_code: int = 200, payload: Any = None, json_error: Exception | None = None
    ):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self) -> Any:
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class _Client:
    responses: list[Any] = []
    requests: list[dict[str, Any]] = []

    def __init__(self, *, timeout: float):
        self.timeout = timeout

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.requests.append({"url": url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def fake_remote_client(monkeypatch: pytest.MonkeyPatch) -> type[_Client]:
    _Client.responses = []
    _Client.requests = []
    monkeypatch.setattr(embeddings.httpx, "Client", _Client)
    return _Client


def test_remote_embedder_orders_vectors_batches_and_clips_input(
    fake_remote_client: type[_Client],
) -> None:
    first_count = embeddings.REMOTE_BATCH_SIZE
    first_data = [
        {"index": index, "embedding": [float(index + 1), 0.0]}
        for index in reversed(range(first_count))
    ]
    fake_remote_client.responses = [
        _Response(payload={"data": first_data}),
        _Response(payload={"data": [{"embedding": [0.0, 2.0]}]}),
    ]
    remote = RemoteEmbedder("https://example.test/", "secret", "embed-v1", dimensions=2)
    texts = ["x" * (embeddings.MAX_CHARS_PER_INPUT + 1), ""] + ["value"] * 31

    vectors = remote.embed(texts)

    assert len(vectors) == 33
    assert vectors[0] == [1.0, 0.0]
    assert vectors[-1] == [0.0, 1.0]
    assert remote.dimensions == 2
    assert len(fake_remote_client.requests) == 2
    assert len(fake_remote_client.requests[0]["json"]["input"][0]) == embeddings.MAX_CHARS_PER_INPUT
    assert fake_remote_client.requests[0]["json"]["input"][1] == " "
    assert fake_remote_client.requests[0]["json"]["dimensions"] == 2
    assert fake_remote_client.requests[0]["headers"] == {"Authorization": "Bearer secret"}


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (_Response(status_code=401), "embedding_unauthorized"),
        (_Response(status_code=429), "embedding_rate_limited"),
        (_Response(status_code=503), "embedding_http_503"),
        (_Response(payload={}), "embedding_response_invalid"),
        (_Response(payload={"data": {}}), "embedding_response_invalid"),
        (_Response(payload={"data": [{"embedding": []}]}), "embedding_response_invalid"),
        (
            _Response(payload={"data": [{"embedding": ["not-a-number"]}]}),
            "embedding_response_invalid",
        ),
        (_Response(payload={"data": []}), "embedding_count_mismatch"),
        (_Response(json_error=ValueError("bad json")), "embedding_response_invalid"),
    ],
)
def test_remote_embedder_maps_invalid_responses(
    fake_remote_client: type[_Client], response: _Response, reason: str
) -> None:
    fake_remote_client.responses = [response]

    with pytest.raises(EmbeddingError, match=reason) as raised:
        RemoteEmbedder("https://example.test", "key", "model").embed(["query"])

    assert raised.value.reason == reason


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (httpx.ReadTimeout("slow"), "embedding_timeout"),
        (httpx.ConnectError("offline"), "embedding_unreachable"),
    ],
)
def test_remote_embedder_maps_transport_failures(
    fake_remote_client: type[_Client], failure: Exception, reason: str
) -> None:
    fake_remote_client.responses = [failure]

    with pytest.raises(EmbeddingError, match=reason):
        RemoteEmbedder("https://example.test", "key", "model").embed(["query"])


def test_remote_embedder_empty_input_does_not_create_client(
    fake_remote_client: type[_Client],
) -> None:
    assert RemoteEmbedder("https://example.test", "key", "model").embed([]) == []
    assert fake_remote_client.requests == []
