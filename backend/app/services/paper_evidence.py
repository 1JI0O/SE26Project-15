from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter
from functools import cache
from typing import Any

_SENTENCE_BOUNDARY = re.compile(r"[.!?;。！？；](?:\s+|$)|\n+")
_LATEX_FRACTION = re.compile(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}")
_LATEX_TIMES = re.compile(r"\\times\b")
_WORD_OR_OPERATOR = re.compile(r"[^\W_]+|[/=+\-*<>×]", re.UNICODE)
_SPAN_ID = re.compile(
    r"^paper-span-([0-9a-f]{10})-([0-9a-f]+)-([0-9a-f]+)-([0-9a-f]{12})$"
)
_SEARCH_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "these",
    "this",
    "to",
    "with",
}


class PaperEvidenceResolutionError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _quote_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _span_payload(block_id: str, text: str, start: int, end: int) -> dict[str, Any]:
    quote = text[start:end]
    digest = _quote_hash(quote)
    block_digest = hashlib.sha256(block_id.encode()).hexdigest()[:10]
    return {
        "span_id": f"paper-span-{block_digest}-{start:x}-{end:x}-{digest[:12]}",
        "quote": quote,
        "char_start": start,
        "char_end": end,
        "quote_hash": digest,
    }


def _trimmed_range(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None


def _split_oversized_range(
    text: str,
    start: int,
    end: int,
    *,
    min_chars: int,
    max_chars: int,
) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    cursor = start
    while end - cursor > max_chars:
        preferred = cursor + max_chars
        floor = min(cursor + min_chars, preferred)
        split = max(
            text.rfind(" ", floor, preferred),
            text.rfind(",", floor, preferred),
            text.rfind("，", floor, preferred),
            text.rfind(":", floor, preferred),
            text.rfind("：", floor, preferred),
        )
        if split < floor:
            split = preferred
        else:
            split += 1
        trimmed = _trimmed_range(text, cursor, split)
        if trimmed is not None:
            ranges.append(trimmed)
        cursor = split
    trimmed = _trimmed_range(text, cursor, end)
    if trimmed is not None:
        ranges.append(trimmed)
    return ranges


def build_evidence_spans(
    block: dict[str, Any],
    *,
    min_chars: int = 80,
    max_chars: int = 480,
) -> list[dict[str, Any]]:
    block_id = str(block.get("id") or "")
    text = str(block.get("text") or "")
    if not block_id or not text:
        return []

    boundaries = [0, *(match.end() for match in _SENTENCE_BOUNDARY.finditer(text)), len(text)]
    raw_ranges: list[tuple[int, int]] = []
    for left, right in zip(boundaries, boundaries[1:], strict=False):
        trimmed = _trimmed_range(text, left, right)
        if trimmed is not None and trimmed not in raw_ranges:
            raw_ranges.append(trimmed)
    if not raw_ranges:
        raw_ranges = [(0, len(text))]

    combined: list[tuple[int, int]] = []
    pending: tuple[int, int] | None = None
    for start, end in raw_ranges:
        if pending is None:
            pending = (start, end)
        elif pending[1] - pending[0] < min_chars:
            pending = (pending[0], end)
        else:
            combined.append(pending)
            pending = (start, end)
    if pending is not None:
        if combined and pending[1] - pending[0] < min_chars:
            combined[-1] = (combined[-1][0], pending[1])
        else:
            combined.append(pending)

    final_ranges: list[tuple[int, int]] = []
    for start, end in combined:
        final_ranges.extend(
            _split_oversized_range(
                text,
                start,
                end,
                min_chars=min_chars,
                max_chars=max_chars,
            )
        )
    return [_span_payload(block_id, text, start, end) for start, end in final_ranges]


def _normalized_parts(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return [
        part
        for part in re.findall(r"[^\W\d_]+|\d+(?:\.\d+)?", normalized, re.UNICODE)
        if part
    ]


def _tokens_with_offsets(value: str) -> list[tuple[str, int, int]]:
    tokens: list[tuple[str, int, int]] = []
    cursor = 0
    while cursor < len(value):
        fraction = _LATEX_FRACTION.match(value, cursor)
        if fraction is not None:
            start, end = fraction.span()
            numerator = _normalized_parts(fraction.group(1))
            denominator = _normalized_parts(fraction.group(2))
            tokens.extend((token, start, end) for token in numerator)
            tokens.append(("/", start, end))
            tokens.extend((token, start, end) for token in denominator)
            cursor = end
            continue
        times = _LATEX_TIMES.match(value, cursor)
        if times is not None:
            tokens.append(("times", times.start(), times.end()))
            cursor = times.end()
            continue
        match = _WORD_OR_OPERATOR.match(value, cursor)
        if match is None:
            cursor += 1
            continue
        raw = match.group(0)
        if raw == "×":
            tokens.append(("times", match.start(), match.end()))
        elif raw in {"/", "=", "+", "-", "*", "<", ">"}:
            tokens.append((raw, match.start(), match.end()))
        else:
            parts = _normalized_parts(raw)
            tokens.extend((part, match.start(), match.end()) for part in parts)
        cursor = match.end()

    values = [token[0] for token in tokens]
    for index, current in enumerate(values):
        if (
            current == "x"
            and 0 < index < len(values) - 1
            and values[index - 1].replace(".", "", 1).isdigit()
            and values[index + 1].replace(".", "", 1).isdigit()
        ):
            token, start, end = tokens[index]
            tokens[index] = ("times", start, end)
    return tokens


def canonical_tokens(value: str) -> list[str]:
    return [token for token, _start, _end in _tokens_with_offsets(value)]


def _exact_occurrences(container: str, quote: str) -> list[tuple[int, int]]:
    if not quote:
        return []
    occurrences: list[tuple[int, int]] = []
    cursor = 0
    while True:
        start = container.find(quote, cursor)
        if start < 0:
            return occurrences
        occurrences.append((start, start + len(quote)))
        cursor = start + 1


def _canonical_occurrences(container: str, quote: str) -> list[tuple[int, int]]:
    source = _tokens_with_offsets(container)
    needle = canonical_tokens(quote)
    if not source or not needle or len(needle) > len(source):
        return []
    values = [token for token, _start, _end in source]
    matches: list[tuple[int, int]] = []
    for index in range(len(values) - len(needle) + 1):
        if values[index : index + len(needle)] == needle:
            matches.append((source[index][1], source[index + len(needle) - 1][2]))
    # PDF extraction can remove a word boundary ("test set" -> "testset"). Permit only
    # full alphabetic-token concatenations on either side; all letters still have to match
    # exactly and the final source range still has to be unique.
    for start in range(len(values)):
        @cache
        def matched_ends(source_index: int, needle_index: int) -> tuple[int, ...]:
            if needle_index == len(needle):
                return (source_index,)
            if source_index >= len(values):
                return ()
            ends: set[int] = set()
            if values[source_index] == needle[needle_index]:
                ends.update(matched_ends(source_index + 1, needle_index + 1))
            if values[source_index].isalpha() and needle[needle_index].isalpha():
                joined = needle[needle_index]
                for next_needle in range(needle_index + 1, min(len(needle), needle_index + 4)):
                    if not needle[next_needle].isalpha():
                        break
                    joined += needle[next_needle]
                    if joined == values[source_index]:
                        ends.update(matched_ends(source_index + 1, next_needle + 1))
                joined = values[source_index]
                for next_source in range(source_index + 1, min(len(values), source_index + 4)):
                    if not values[next_source].isalpha():
                        break
                    joined += values[next_source]
                    if joined == needle[needle_index]:
                        ends.update(matched_ends(next_source + 1, needle_index + 1))
            return tuple(sorted(ends))

        for end in matched_ends(start, 0):
            if end > start:
                matches.append((source[start][1], source[end - 1][2]))
    return list(dict.fromkeys(matches))


def resolve_paper_evidence(
    block: dict[str, Any],
    *,
    span_id: str | None = None,
    quote: str | None = None,
    occurrence: int | None = None,
) -> dict[str, Any]:
    block_id = str(block.get("id") or "")
    text = str(block.get("text") or "")
    if not block_id or not text:
        raise PaperEvidenceResolutionError("paper_block_text_missing")

    selected: dict[str, Any] | None = None
    if span_id:
        selected = next(
            (span for span in build_evidence_spans(block) if span["span_id"] == span_id),
            None,
        )
        encoded = _SPAN_ID.fullmatch(span_id)
        if selected is None and encoded is not None:
            expected_block = hashlib.sha256(block_id.encode()).hexdigest()[:10]
            start = int(encoded.group(2), 16)
            end = int(encoded.group(3), 16)
            if (
                encoded.group(1) == expected_block
                and 0 <= start < end <= len(text)
            ):
                candidate = _span_payload(block_id, text, start, end)
                if candidate["span_id"] == span_id:
                    selected = candidate
        if selected is None:
            raise PaperEvidenceResolutionError("paper_span_not_found")

    quote_match: tuple[int, int] | None = None
    if quote:
        occurrences = _exact_occurrences(text, quote)
        if not occurrences:
            occurrences = _canonical_occurrences(text, quote)
        if occurrence is not None:
            if occurrence < 1 or occurrence > len(occurrences):
                raise PaperEvidenceResolutionError("paper_quote_occurrence_not_found")
            quote_match = occurrences[occurrence - 1]
        elif len(occurrences) > 1:
            selected_occurrences = (
                [
                    candidate
                    for candidate in occurrences
                    if selected is not None
                    and candidate
                    == (selected["char_start"], selected["char_end"])
                ]
            )
            if len(selected_occurrences) == 1:
                quote_match = selected_occurrences[0]
            else:
                raise PaperEvidenceResolutionError("paper_quote_ambiguous")
        elif not occurrences:
            raise PaperEvidenceResolutionError("paper_quote_not_found")
        else:
            quote_match = occurrences[0]

    if selected is None and quote_match is None:
        raise PaperEvidenceResolutionError("paper_evidence_missing")
    if selected is not None and quote_match is not None:
        if (
            selected["char_start"] != quote_match[0]
            or selected["char_end"] != quote_match[1]
        ):
            raise PaperEvidenceResolutionError("paper_span_quote_mismatch")
    if selected is None and quote_match is not None:
        selected = _span_payload(block_id, text, quote_match[0], quote_match[1])

    assert selected is not None
    return {
        **selected,
        "block_id": block_id,
        "page": block.get("page_number") or block.get("page"),
    }


def _search_token_values(value: str) -> list[str]:
    return [
        token
        for token in canonical_tokens(value)
        if token not in _SEARCH_STOPWORDS and (len(token) >= 2 or token.isdigit())
    ]


def search_paper_blocks(
    blocks: list[dict[str, Any]],
    query: str,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    query_tokens = _search_token_values(query)
    if not query_tokens:
        return []
    spans = [
        (block, span)
        for block in blocks
        for span in build_evidence_spans(block)
    ]
    if not spans:
        return []

    span_tokens = [_search_token_values(str(span["quote"])) for _block, span in spans]
    document_frequency: Counter[str] = Counter()
    for tokens in span_tokens:
        document_frequency.update(set(tokens))
    total = len(spans)
    query_counts = Counter(query_tokens)
    ranked: list[tuple[float, dict[str, Any]]] = []
    for (block, span), tokens in zip(spans, span_tokens, strict=True):
        counts = Counter(tokens)
        score = 0.0
        for token, query_count in query_counts.items():
            exact = counts.get(token, 0)
            if exact:
                inverse_frequency = math.log((total + 1) / (document_frequency[token] + 1)) + 1
                score += inverse_frequency * min(exact, query_count)
                continue
            if len(token) >= 4 and any(
                len(candidate) >= 4 and (token in candidate or candidate in token)
                for candidate in counts
            ):
                score += 0.35
        if score <= 0:
            continue
        values = canonical_tokens(str(span["quote"]))
        needle = canonical_tokens(query)
        if needle and any(
            values[index : index + len(needle)] == needle
            for index in range(max(len(values) - len(needle) + 1, 0))
        ):
            score += 2.0
        ranked.append(
            (
                score,
                {
                    "block_id": str(block.get("id") or ""),
                    "kind": block.get("kind"),
                    "page": block.get("page_number") or block.get("page"),
                    "section_path": list(block.get("section_path") or []),
                    "score": round(score, 4),
                    "snippet": str(span["quote"])[:200],
                    "evidence_span": span,
                },
            )
        )
    ranked.sort(key=lambda item: (-item[0], item[1]["block_id"], item[1]["snippet"]))
    results: list[dict[str, Any]] = []
    seen_blocks: set[str] = set()
    for _score, item in ranked:
        if item["block_id"] in seen_blocks:
            continue
        seen_blocks.add(item["block_id"])
        results.append(item)
        if len(results) >= limit:
            break
    return results
