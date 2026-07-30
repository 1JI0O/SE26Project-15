"""Embedding providers for the retrieval layer.

Two providers, one interface:

* :class:`LocalHashingEmbedder` — deterministic, offline, no API key. It projects character
  n-grams and word tokens into a fixed-dimension vector with signed feature hashing and
  sublinear term weighting. This is not a neural embedding: it captures lexical and
  morphological overlap (including CJK, where it n-grams characters directly), which is a
  real improvement over exact token matching for paper↔code retrieval, and it costs nothing.
  It is the default so retrieval works on a fresh install with no configuration.
* :class:`RemoteEmbedder` — any OpenAI-compatible ``/embeddings`` endpoint, configured
  through the integration settings. Used when the user supplies a base URL, key, and model.

Both return L2-normalized vectors, so cosine similarity is a plain dot product.
"""

from __future__ import annotations

import base64
import hashlib
import math
import re
import struct
from collections import Counter
from typing import Protocol

import httpx

WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*|\d+")
CJK_RE = re.compile(r"[一-鿿]")
CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
# Batch size for remote embedding calls. Providers cap request size; 32 keeps payloads
# well inside common limits while still amortizing round-trips over a large corpus.
REMOTE_BATCH_SIZE = 32
MAX_CHARS_PER_INPUT = 8000


class EmbeddingError(RuntimeError):
    """Raised when an embedding backend cannot produce vectors."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Embedder(Protocol):
    name: str
    model: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def encode_vector(vector: list[float]) -> str:
    """Pack a float vector as base64 float32 for the TEXT column."""

    return base64.b64encode(struct.pack(f"<{len(vector)}f", *vector)).decode("ascii")


def decode_vector(payload: str) -> list[float]:
    raw = base64.b64decode(payload.encode("ascii"))
    return list(struct.unpack(f"<{len(raw) // 4}f", raw))


def cosine(left: list[float], right: list[float]) -> float:
    """Dot product of two vectors, guarding against dimension drift.

    Stored vectors are already normalized, so this is cosine similarity. A stored chunk from
    a previous embedder generation can have a different length; comparing those is
    meaningless, so it scores 0 rather than raising.
    """

    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True))


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [value / norm for value in vector]


def tokenize(text: str) -> list[str]:
    """Lexical features: split identifiers, lowercase words, and CJK bigrams.

    ``FocalLoss`` yields ``focalloss``, ``focal``, ``loss`` so a paper mentioning "focal
    loss" and code defining ``FocalLoss`` share features. CJK has no word boundaries, so
    characters are emitted as unigrams and bigrams.
    """

    expanded = CAMEL_RE.sub(" ", text.replace("_", " ").replace(".", " ").replace("/", " "))
    tokens: list[str] = []
    for match in WORD_RE.findall(expanded):
        lowered = match.lower()
        tokens.append(lowered)
        if len(lowered) > 3:
            # Character trigrams give partial-match recall (conv/convolution).
            tokens.extend(lowered[index : index + 3] for index in range(len(lowered) - 2))
    chinese = "".join(CJK_RE.findall(text))
    tokens.extend(chinese)
    tokens.extend(chinese[index : index + 2] for index in range(max(len(chinese) - 1, 0)))
    return tokens


class LocalHashingEmbedder:
    """Offline signed-feature-hashing embedder. Deterministic across processes."""

    def __init__(self, dimensions: int = 512) -> None:
        self.name = "local"
        self.model = f"local-hashing-{dimensions}"
        self.dimensions = max(64, min(4096, dimensions))

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        counts = Counter(tokenize(text[:MAX_CHARS_PER_INPUT]))
        if not counts:
            return vector
        for token, count in counts.items():
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            # Sublinear term frequency: a term repeated 100x must not dominate the vector.
            vector[index] += sign * (1.0 + math.log(count))
        return _normalize(vector)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]


class RemoteEmbedder:
    """OpenAI-compatible ``POST {base_url}/embeddings`` client."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        dimensions: int = 0,
    ) -> None:
        self.name = "remote"
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self._timeout = timeout_seconds
        # 0 means "whatever the model returns"; discovered from the first response.
        self.dimensions = dimensions

    def _request(self, client: httpx.Client, batch: list[str]) -> list[list[float]]:
        payload: dict[str, object] = {"model": self.model, "input": batch}
        if self.dimensions:
            # Only models that support Matryoshka truncation honour this; providers that do
            # not simply ignore it, and we re-read the true size from the response below.
            payload["dimensions"] = self.dimensions
        response = client.post(
            f"{self.base_url}/embeddings",
            json=payload,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        if response.status_code == 401:
            raise EmbeddingError("embedding_unauthorized")
        if response.status_code == 429:
            raise EmbeddingError("embedding_rate_limited")
        if response.status_code >= 400:
            raise EmbeddingError(f"embedding_http_{response.status_code}")
        vectors: list[list[float]] = []
        try:
            data = response.json()["data"]
            if not isinstance(data, list):
                raise TypeError("embedding data must be a list")
            # Providers may reorder; ``index`` is authoritative when present.
            ordered = sorted(data, key=lambda item: int(item.get("index", 0)))
            for item in ordered:
                values = item.get("embedding")
                if not isinstance(values, list) or not values:
                    raise TypeError("embedding vector must be a non-empty list")
                vectors.append(_normalize([float(value) for value in values]))
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise EmbeddingError("embedding_response_invalid") from exc
        if len(vectors) != len(batch):
            raise EmbeddingError("embedding_count_mismatch")
        return vectors

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        clipped = [text[:MAX_CHARS_PER_INPUT] or " " for text in texts]
        vectors: list[list[float]] = []
        try:
            with httpx.Client(timeout=self._timeout) as client:
                for start in range(0, len(clipped), REMOTE_BATCH_SIZE):
                    batch = clipped[start : start + REMOTE_BATCH_SIZE]
                    vectors.extend(self._request(client, batch))
        except EmbeddingError:
            raise
        except httpx.TimeoutException as exc:
            raise EmbeddingError("embedding_timeout") from exc
        except httpx.HTTPError as exc:
            raise EmbeddingError("embedding_unreachable") from exc
        if vectors:
            self.dimensions = len(vectors[0])
        return vectors
