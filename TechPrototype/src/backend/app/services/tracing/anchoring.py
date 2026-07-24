"""Fragment-level anchoring utilities shared by trace validation and persistence.

A trace target's real identity is (coarse location + quote + occurrence + quote_hash),
not a block ID or line number. These helpers locate the *n*-th occurrence of a quote
inside a container (paper block text or code file), compute a stable content hash, and
expose the concrete character range so hover highlighting lands on the correct spot even
when the same quote appears several times.
"""

from __future__ import annotations

import hashlib


def normalize_quote(value: str) -> str:
    """Collapse all runs of whitespace to single spaces and strip ends."""

    return " ".join(value.split())


def _alnum(value: str) -> str:
    """Keep only lowercase alphanumerics — tolerates unicode math, punctuation, spacing."""

    return "".join(ch for ch in value.lower() if ch.isalnum())


def quote_hash(value: str) -> str:
    """sha256 of the normalized quote, used for cross-reparse consistency checks."""

    return hashlib.sha256(normalize_quote(value).encode("utf-8")).hexdigest()


def find_occurrence(haystack: str, needle: str, occurrence: int) -> tuple[int, int] | None:
    """Return the (start, end) char offsets of the *occurrence*-th (1-based) exact match.

    Returns ``None`` when the needle is empty, ``occurrence`` is invalid, or there are
    fewer than ``occurrence`` matches.
    """

    if occurrence < 1 or not needle:
        return None
    start = -1
    for _ in range(occurrence):
        start = haystack.find(needle, start + 1)
        if start < 0:
            return None
    return start, start + len(needle)


def count_occurrences(haystack: str, needle: str) -> int:
    if not needle:
        return 0
    return haystack.count(needle)


class AnchorError(ValueError):
    """Raised when a quote cannot be anchored to its declared occurrence."""


def resolve_anchor(container: str, quote: str, occurrence: int) -> dict[str, object]:
    """Resolve a quote to a concrete char range + hash inside ``container``.

    Degrading strategy (never fabricates — the quote must genuinely occur in the container):

    1. exact raw match → precise char offsets (`level="exact"`);
    2. whitespace-normalized match → existence confirmed, offsets unset (`level="normalized"`);
    3. alphanumeric-only match of the quote (or its meaningful prefix) → tolerates unicode
       math / punctuation / rendering differences (`level="approximate"`, offsets unset).

    Only when even the relaxed form is absent do we raise :class:`AnchorError`; the caller
    then records the target as unresolved rather than mis-anchoring it.
    """

    raw = find_occurrence(container, quote, occurrence)
    if raw is not None:
        start, end = raw
        return {
            "occurrence": occurrence,
            "char_start": start,
            "char_end": end,
            "quote_hash": quote_hash(quote),
            "exact": True,
            "level": "exact",
        }
    if find_occurrence(normalize_quote(container), normalize_quote(quote), occurrence) is not None:
        return {
            "occurrence": occurrence,
            "char_start": None,
            "char_end": None,
            "quote_hash": quote_hash(quote),
            "exact": False,
            "level": "normalized",
        }
    haystack = _alnum(container)
    needle = _alnum(quote)
    probe = needle[:60] if len(needle) > 60 else needle
    if probe and probe in haystack:
        return {
            "occurrence": 1,
            "char_start": None,
            "char_end": None,
            "quote_hash": quote_hash(quote),
            "exact": False,
            "level": "approximate",
        }
    raise AnchorError("quote_occurrence_not_found")
