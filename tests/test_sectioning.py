from sheetmusic.parts.model import PageInfo
from sheetmusic.parts.sectioning import build_sections

TITLE = "Orient Express"


def part(first, n, instrument, header=None):
    """A title page followed by n-1 continuation pages with a centered instrument header."""
    pages = [PageInfo(first, title_text=TITLE, title_instrument=instrument)]
    pages += [PageInfo(first + k, header_instrument=header or instrument) for k in range(1, n)]
    return pages


def numbered(pages):
    return [PageInfo(i, p.is_score, p.title_text, p.title_instrument, p.header_instrument) for i, p in enumerate(pages)]


def summary(sections):
    return [(s.name, s.start, s.end) for s in sections]


def test_score_then_parts_with_cover_pages_joining_the_score():
    pages = [PageInfo(0), PageInfo(1)] + [PageInfo(i, is_score=True) for i in range(2, 6)]
    pages += part(6, 3, "Flute I") + part(9, 3, "Oboe")
    assert summary(build_sections(numbered(pages), TITLE)) == [
        ("Score", 0, 5), ("Flute 1", 6, 8), ("Oboe", 9, 11)]


def test_noisy_headers_do_not_split_a_part_when_title_pages_mark_the_parts():
    pages = part(0, 4, "Flute II", header="Flute If") + part(4, 4, "Oboe", header="Oboe")
    pages[2] = PageInfo(2, header_instrument="Flute Ill")          # OCR noise on a continuation page
    pages += part(8, 2, "Clarinet")
    assert summary(build_sections(numbered(pages), TITLE)) == [("Flute 2", 0, 3), ("Oboe", 4, 7), ("Clarinet", 8, 9)]


def test_header_change_splits_parts_in_sets_without_title_pages():
    pages = [PageInfo(i, header_instrument="Flute") for i in range(3)]
    pages += [PageInfo(i, header_instrument="Trumpet") for i in range(3, 6)]
    assert summary(build_sections(pages, "")) == [("Flute", 0, 2), ("Trumpet", 3, 5)]


def test_missing_numeral_is_inferred_from_the_siblings():
    pages = part(0, 2, "Bb Trumpet I") + part(2, 2, "Bb Trumpet II") + part(4, 2, "Bb Trumpet")   # III unreadable
    pages += part(6, 2, "Eb Clarinet")                                                              # a different family
    names = [s.name for s in build_sections(numbered(pages), TITLE)]
    assert names == ["Bb Trumpet 1", "Bb Trumpet 2", "Bb Trumpet 3", "Eb Clarinet"]


def test_percussion_pairs_and_duplicate_names():
    pages = part(0, 2, "Percussion I I") + part(2, 2, "Percussion III IV") + part(4, 2, "Basses") + part(6, 2, "Basses")
    names = [s.name for s in build_sections(numbered(pages), TITLE)]
    assert names == ["Percussion 1 & 2", "Percussion 3 & 4", "Basses (1)", "Basses (2)"]
