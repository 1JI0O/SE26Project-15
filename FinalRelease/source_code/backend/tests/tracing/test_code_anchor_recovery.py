"""Code-side anchoring: a quote that only matches approximately must still yield a *verified*
line range, instead of keeping the line numbers the model claimed."""

from types import SimpleNamespace

from app.services.agent.analysis_tools import _resolve_code_anchor
from app.services.tracing.anchoring import locate_approximate_span

SOURCE = """import torch
import torch.nn as nn

class Keypoint2DLoss(nn.Module):

    def __init__(self, loss_type: str = 'l1'):
        super(Keypoint2DLoss, self).__init__()


class Keypoint3DLoss(nn.Module):

    def __init__(self, loss_type: str = 'l1'):
        \"\"\"
        3D keypoint loss module.
        Args:
            loss_type (str): Choose between l1 and l2 losses.
        \"\"\"
        super(Keypoint3DLoss, self).__init__()
"""

# Reformatted the way a model paraphrases source it read: the blank line and the ``Args:`` block
# are gone, so neither the raw nor the whitespace-normalized quote matches the file.
QUOTE = (
    "class Keypoint3DLoss(nn.Module):\n"
    "    def __init__(self, loss_type: str = 'l1'):\n"
    '        """\n'
    "        3D keypoint loss module.\n"
    '        """\n'
    "        super(Keypoint3DLoss, self).__init__()"
)


def _evidence(line_start: int, line_end: int) -> SimpleNamespace:
    return SimpleNamespace(
        path="hamer/models/losses.py",
        quote=QUOTE,
        occurrence=1,
        line_start=line_start,
        line_end=line_end,
        role="model_component",
    )


def _repository(monkeypatch) -> object:
    monkeypatch.setattr(
        "app.services.agent.analysis_tools._read_file",
        lambda repository, path: SOURCE,
    )
    return object()


def test_locate_approximate_span_finds_reformatted_quote() -> None:
    span = locate_approximate_span(SOURCE, QUOTE)
    assert span is not None
    assert SOURCE[span[0] :].startswith("class Keypoint3DLoss(nn.Module):")


def test_approximate_anchor_narrows_match_to_verified_lines(monkeypatch) -> None:
    """A declared range that contains the match is kept as context, but the match range
    reported to the UI shrinks to the lines that were actually verified."""

    repository = _repository(monkeypatch)
    anchor = _resolve_code_anchor(repository, _evidence(10, 18))

    assert anchor["level"] == "approximate"
    assert anchor["char_start"] is None
    # ``class Keypoint3DLoss`` is on line 10 of SOURCE.
    assert anchor["match_line_start"] == 10
    assert anchor["match_line_end"] <= 18
    # Declared range still contains the match, so it survives as surrounding context.
    assert (anchor["line_start"], anchor["line_end"]) == (10, 18)


def test_approximate_anchor_replaces_a_wrong_declared_range(monkeypatch) -> None:
    """When the claimed range does not even contain the verified match, it is discarded —
    otherwise the code pane highlights and centres on unrelated lines."""

    repository = _repository(monkeypatch)
    anchor = _resolve_code_anchor(repository, _evidence(1, 8))

    assert anchor["match_line_start"] == 10
    assert anchor["line_start"] == 10
    assert anchor["line_end"] >= 10
