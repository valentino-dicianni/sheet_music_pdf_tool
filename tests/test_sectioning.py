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


def test_percussion_pairs_when_the_title_page_shows_two_numerals():
    pages = part(0, 2, "Percussion I I", header="Percussion I") + part(2, 2, "Percussion III IV", header="Percussion III")
    assert [s.name for s in build_sections(numbered(pages), TITLE)] == ["Percussion 1 & 2", "Percussion 3 & 4"]


def test_percussion_1_2_3_stay_separate_parts():
    pages = part(0, 2, "Percussion") + part(2, 2, "Percussion 2") + part(4, 2, "Percussion 3")
    assert [s.name for s in build_sections(numbered(pages), TITLE)] == ["Percussion 1", "Percussion 2", "Percussion 3"]


def test_identically_named_parts_are_numbered_in_page_order():
    pages = part(0, 2, "Bb Clarinet") + part(2, 2, "Bb Clarinet") + part(4, 2, "Bb Clarinet") + part(6, 2, "Eb Clarinet")
    assert [s.name for s in build_sections(numbered(pages), TITLE)] == [
        "Bb Clarinet 1", "Bb Clarinet 2", "Bb Clarinet 3", "Eb Clarinet"]


def test_part_ranges_are_kept():
    pages = part(0, 2, "French Horns 2-4") + part(2, 2, "French Horns 1-3")
    assert [s.name for s in build_sections(numbered(pages), TITLE)] == ["Horns 2-4", "Horns 1-3"]


def noah_like(lengths=(4,) * 8, score_pages=6):
    """Score pages whose margin is full of staff names, then parts whose first page has the instrument at the
    top left (the piece title is readable on every other one only)."""
    pages = [PageInfo(i, is_score=True, margin_instruments=9) for i in range(score_pages)]
    names = ["Piccolo", "Flute", "Oboe", "Bassoon", "Bb Clarinet", "Eb Alto Saxophone", "Horn", "Harp"]
    at = score_pages
    for k, length in enumerate(lengths):
        pages.append(PageInfo(at, title_text="NOAH'S ARK" if k % 2 == 0 else "", title_instrument=names[k]))
        pages += [PageInfo(at + j) for j in range(1, length)]
        at += length
    return pages


def test_parts_that_open_with_an_instrument_name_split_without_a_readable_title():
    secs = build_sections(noah_like(), "NOAH'S ARK")
    assert [(s.name, s.pages) for s in secs] == [
        ("Score", "1-6"), ("Piccolo", "7-10"), ("Flute", "11-14"), ("Oboe", "15-18"), ("Bassoon", "19-22"),
        ("Bb Clarinet", "23-26"), ("Eb Alto Saxophone", "27-30"), ("Horn", "31-34"), ("Harp", "35-38")]
    assert not any(s.inferred for s in secs)


def test_a_part_with_no_readable_instrument_is_found_from_the_even_spacing():
    pages = noah_like()
    flute = next(p for p in pages if p.title_instrument == "Flute")
    flute.title_instrument, flute.title_text = "", "DALDAIA"        # the instrument is unreadable, a heading is there
    secs = build_sections(pages, "NOAH'S ARK")
    assert [(s.name, s.pages) for s in secs][:4] == [
        ("Score", "1-6"), ("Piccolo 1", "7-10"), ("Piccolo 2", "11-14"), ("Oboe", "15-18")]
    assert [s.inferred for s in secs][:4] == [False, False, True, False]


def test_even_spacing_alone_is_not_enough_a_heading_must_be_there():
    pages = noah_like()
    flute = next(p for p in pages if p.title_instrument == "Flute")
    flute.title_instrument = ""                                       # no heading text at all at that spot
    secs = build_sections(pages, "NOAH'S ARK")
    assert [s.pages for s in secs][:3] == ["1-6", "7-14", "15-18"] and not any(s.inferred for s in secs)


def test_no_even_spacing_no_guessing():
    pages = noah_like(lengths=(4, 4, 6, 3, 5, 4, 7, 4))        # parts of all sorts of lengths
    pages[12].title_text = "DALDAIA"                             # a heading inside a part must not split it
    secs = build_sections(pages, "NOAH'S ARK")
    assert not any(s.inferred for s in secs) and len(secs) == 9


def test_uneven_parts_do_not_count_as_evenly_spaced_even_if_the_commonest_gap_repeats():
    # gaps 4,4,8,6,10,5: the most common gap (4) covers only a third of them, so nothing is inferred
    pages = noah_like(lengths=(4, 4, 8, 6, 10, 5))
    pages[6 + 4 + 4 + 4].title_text = "DALDAIA"                  # a heading right where a 4-page rhythm would cut
    assert not any(s.inferred for s in build_sections(pages, "NOAH'S ARK"))


def test_unnamed_front_matter_before_the_score_joins_the_score():
    front = [PageInfo(0), PageInfo(1), PageInfo(2), PageInfo(3)]
    pages = front + [PageInfo(i, is_score=True) for i in range(4, 9)] + part(9, 3, "Flute") + part(12, 3, "Oboe") + part(15, 3, "Bassoon")
    secs = build_sections(numbered(pages), TITLE)
    assert [(s.name, s.pages) for s in secs] == [("Score", "1-9"), ("Flute", "10-12"), ("Oboe", "13-15"), ("Bassoon", "16-18")]


def merged(i, instrument):
    """A page whose header line is '<instrument> <title>' (a title page whose lines were merged by OCR, or a running header)."""
    return PageInfo(i, header_instrument=f"{instrument} {TITLE}")


def test_a_running_header_with_the_title_does_not_start_a_part_but_a_new_instrument_does():
    # Pirates-like: [title page, continuation with 'TITLE Instrument' header] x N: 2 pages per part
    pages = []
    for k, name in enumerate(["Piccolo", "Flute 1", "Flute 2", "Oboe"]):
        pages += [PageInfo(2 * k, title_text=TITLE, title_instrument=name), merged(2 * k + 1, name)]
    assert [(s.name, s.pages) for s in build_sections(pages, TITLE)] == [
        ("Piccolo", "1-2"), ("Flute 1", "3-4"), ("Flute 2", "5-6"), ("Oboe", "7-8")]


def test_a_garbled_key_letter_in_a_running_header_does_not_split_the_part():
    pages = [PageInfo(0, title_text=TITLE, title_instrument="Eb Alto Sax 2"), merged(1, "Fb Alto Sax 2"),
             PageInfo(2, title_text=TITLE, title_instrument="Bb Tenor Sax"), merged(3, "Bb Tenor Sax"),
             PageInfo(4, title_text=TITLE, title_instrument="Bb Trumpet 1"), merged(5, "Bb Trumpet")]
    assert [s.pages for s in build_sections(pages, TITLE)] == ["1-2", "3-4", "5-6"]


def test_a_title_in_the_header_line_with_a_new_instrument_opens_a_part_even_without_a_title_page():
    pages = [merged(0, "Flute"), PageInfo(1, header_instrument="Flute"), merged(2, "Oboe"), PageInfo(3, header_instrument="Oboe"),
             merged(4, "Bassoon"), PageInfo(5, header_instrument="Bassoon")]
    assert [(s.name, s.pages) for s in build_sections(pages, TITLE)] == [("Flute", "1-2"), ("Oboe", "3-4"), ("Bassoon", "5-6")]


def test_a_leftover_page_before_a_part_of_the_same_instrument_joins_it():
    pages = [PageInfo(0, header_instrument="Flute 1")] + part(1, 4, "Flute 1") + part(5, 4, "Flute 2")
    assert [(s.name, s.pages) for s in build_sections(numbered(pages), TITLE)] == [("Flute 1", "1-5"), ("Flute 2", "6-9")]
    # the leftover keeps its place in the part's page order: first
    assert build_sections(numbered(pages), TITLE)[0].page_list() == [0, 1, 2, 3, 4]


def test_a_running_header_of_the_same_instrument_does_not_start_an_inferred_part():
    # 4-page rhythm, but one clarinet part is 8 pages: its 5th page has the running header 'Bb Clarinet 1', no heading
    pages = []
    at = 0
    for name, length in [("Flute", 4), ("Oboe", 4), ("Bb Clarinet 1", 8), ("Bassoon", 4), ("Horn", 4)]:
        pages += [PageInfo(at, title_text=TITLE, title_instrument=name)] + [PageInfo(at + j, header_instrument=name) for j in range(1, length)]
        at += length
    assert [(s.name, s.pages) for s in build_sections(pages, TITLE)] == [
        ("Flute", "1-4"), ("Oboe", "5-8"), ("Bb Clarinet 1", "9-16"), ("Bassoon", "17-20"), ("Horn", "21-24")]


def booklet(names, length=4):
    """Folded A3 booklets halved: each part's pages come as 4, 1, 2, 3 (the page before a title page belongs to it)."""
    pages, at = [], 0
    for name in names:
        pages.append(PageInfo(at, header_instrument=name))                                      # page 4 of the booklet
        pages.append(PageInfo(at + 1, title_text=TITLE, title_instrument=name))                 # page 1: the title page
        pages += [PageInfo(at + j, header_instrument=name) for j in range(2, length)]
        at += length
    return pages


def test_booklet_order_puts_the_last_page_with_its_own_part_and_reads_in_order():
    secs = build_sections(booklet(["Flute 1", "Flute 2", "Oboe", "Bassoon", "Horn"]), TITLE)
    assert [(s.name, s.start + 1, s.end + 1) for s in secs] == [
        ("Flute 1", 1, 4), ("Flute 2", 5, 8), ("Oboe", 9, 12), ("Bassoon", 13, 16), ("Horn", 17, 20)]
    assert secs[1].page_list() == [5, 6, 7, 4]                      # title page first, the booklet's page 4 last


def test_eight_page_parts_in_booklet_order_are_read_per_sheet_pair():
    pages = []
    for k, name in enumerate(["Flute", "Oboe", "Bassoon", "Horn", "Tuba"]):
        at = 8 * k
        pages.append(PageInfo(at, header_instrument=name))
        pages.append(PageInfo(at + 1, title_text=TITLE, title_instrument=name))
        pages += [PageInfo(at + j, header_instrument=name) for j in range(2, 8)]
    secs = build_sections(pages, TITLE)
    assert [s.pages for s in secs][:3] == ["2-4, 1, 6-8, 5", "10-12, 9, 14-16, 13", "18-20, 17, 22-24, 21"]
    assert [len(s.page_list()) for s in secs] == [8] * 5


def test_normal_order_is_not_mistaken_for_a_booklet_even_when_numbered_parts_follow_each_other():
    # Clarinet 1 -> Clarinet 2: the page before 'Clarinet 2's title page has the 'Clarinet 1' header (previous part)
    names = ["Clarinet 1", "Clarinet 2", "Clarinet 3", "Oboe 1", "Oboe 2"]
    pages, at = [], 0
    for name in names:
        pages += [PageInfo(at, title_text=TITLE, title_instrument=name)] + [PageInfo(at + j, header_instrument=name) for j in range(1, 4)]
        at += 4
    secs = build_sections(pages, TITLE)
    assert [(s.name, s.start + 1, s.end + 1) for s in secs] == [
        ("Clarinet 1", 1, 4), ("Clarinet 2", 5, 8), ("Clarinet 3", 9, 12), ("Oboe 1", 13, 16), ("Oboe 2", 17, 20)]
    assert all(s.order is None for s in secs)


def test_in_booklet_sets_a_boundary_that_is_a_page_out_is_snapped_to_the_sheet_grid():
    # 5 parts of 4 pages in booklet order, but the OCR started the 3rd part one page late (5 + 3 pages)
    pages = booklet(["Flute 1", "Flute 2", "Oboe", "Bassoon", "Horn"])
    pages[8] = PageInfo(8, header_instrument="Oboe")            # the page-4 of the Oboe booklet looks like plain text now ...
    pages[9] = PageInfo(9, title_text=TITLE, title_instrument="Oboe")
    pages[8].header_instrument = "Flute 2"                       # ... and reads as the previous part's header
    secs = build_sections(pages, TITLE)
    assert all(len(s.page_list()) % 4 == 0 for s in secs), [(s.name, s.pages) for s in secs]


def test_a_parenthesised_note_at_the_left_names_a_part_but_does_not_open_one():
    pages = part(0, 4, "Flute") + part(4, 4, "(Doubling Oboe II") + part(8, 4, "Bassoon")
    pages[2] = PageInfo(2, title_instrument="(Flute)")               # a note inside the first part: not a new part
    secs = build_sections(numbered(pages), TITLE)
    assert [(s.name, s.pages) for s in secs] == [("Flute", "1-4"), ("Oboe 2", "5-8"), ("Bassoon", "9-12")]
