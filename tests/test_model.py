from sheetmusic.parts import Section, coverage, format_ranges, ranges


def test_ranges_and_format():
    assert ranges([5, 0, 1, 2]) == [(0, 2), (5, 5)]
    assert format_ranges(ranges([0, 1, 2, 5])) == "1-3, 6"


def test_section_pages_keep_output_order():
    s = Section(0, 0, "Flute")
    s.set_pages([60, 142, 61, 62, 63])
    assert s.pages == "61, 143, 62-64"                  # a hand-placed page shows where it sits
    assert s.page_list() == [60, 142, 61, 62, 63]
    s.set_pages([5, 6, 7])
    assert (s.start, s.end, s.order, s.pages) == (5, 7, None, "6-8")      # a plain run needs no explicit order


def test_coverage_reports_missing_and_duplicated_pages():
    a, b = Section(0, 2, "A"), Section(2, 4, "B")
    b.set_pages([2, 3, 4])
    assert coverage([a, b], 8) == ([(5, 7)], [(2, 2)])
