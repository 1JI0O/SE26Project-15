"""Small vector-boundary checks kept separate from provider behavior tests."""

import pytest

from app.services.rag import embeddings


def test_vector_encoding_cosine_and_zero_normalization_boundaries() -> None:
    vector = [0.25, -0.5, 1.0]
    restored = embeddings.decode_vector(embeddings.encode_vector(vector))

    assert restored == pytest.approx(vector)
    assert embeddings.cosine([], []) == 0.0
    assert embeddings.cosine([1.0], [1.0, 2.0]) == 0.0
    assert embeddings.cosine([0.5, 0.5], [1.0, -1.0]) == 0.0
    assert embeddings._normalize([0.0, 0.0]) == [0.0, 0.0]
