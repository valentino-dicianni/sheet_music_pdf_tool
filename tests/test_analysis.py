"""Score or part? Counted from the instrument names beside the staves, which notation cannot imitate."""

import pytest

from sheetmusic.parts import analysis
from sheetmusic.parts.instruments import is_staff_label
from sheetmusic.parts.model import PageInfo


@pytest.mark.parametrize("token, expected", [
    ("Fl.", True), ("Bsn.", True), ("Clarinet", True), ("Flutes", True), ("Oboes", True), ("Tpt.", True), ("Hn.", True),
    ("Grandioso", False), ("mf", False), ("cresc.", False), ("Latin", False), ("Maestoso", False), ("13", False),
])
def test_staff_labels_are_instrument_names_not_dynamics_or_tempo_words(token, expected):
    assert is_staff_label(token) is expected


def test_the_threshold_sits_between_a_part_page_and_a_score_page():
    # measured on real sets: a part page shows <= 4 instrument names in its margin, a score page >= 5 (usually 8-20)
    assert 4 < analysis.SCORE_MIN_LABELS <= 6


def pages(flags):
    return [PageInfo(i, is_score=f) for i, f in enumerate(flags)]


def test_short_gaps_between_score_pages_are_score_pages():
    ps = pages([1, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 1])
    analysis.smooth_scores(ps)
    # 1 and 2 pages between scores are filled; the 6-page gap (a real run of parts) is not
    assert [p.is_score for p in ps] == [True] * 6 + [False] * 6 + [True]


def test_pages_before_the_first_and_after_the_last_score_page_stay_as_they_are():
    ps = pages([0, 0, 1, 1, 0, 0])
    analysis.smooth_scores(ps)
    assert [p.is_score for p in ps] == [False, False, True, True, False, False]
