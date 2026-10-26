
from sheetmusic.parts import NEW_PART, Section, merge_with_next, move_pages, parse_pages, split_section, unassigned_pages


def sections():
    """A = pages 0-3, B = pages 4-7, C = pages 8-11"""
    return [Section(0, 3, "A"), Section(4, 7, "B"), Section(8, 11, "C")]


def test_parse_pages():
    assert parse_pages("3-5, 9", 12) == [2, 3, 4, 8]
    assert parse_pages("2, 1", 12) == [1, 0]                  # the typed order is kept
    assert parse_pages("0-3", 12) is None and parse_pages("13", 12) is None and parse_pages("a", 12) is None


def test_move_to_another_section_at_a_position():
    a, b, c = secs = sections()
    assert move_pages(secs, [7], a, 1) is a
    assert a.page_list() == [0, 7, 1, 2, 3] and b.page_list() == [4, 5, 6]


def test_move_to_the_end_by_default():
    a, b, c = secs = sections()
    move_pages(secs, [0, 1], c)
    assert c.page_list() == [8, 9, 10, 11, 0, 1] and a.page_list() == [2, 3]


def test_reorder_inside_one_section():
    a, b, c = secs = sections()
    move_pages(secs, [0], a, 4)                                # first page behind the last
    assert a.page_list() == [1, 2, 3, 0]
    move_pages(secs, [3], a, 0)                                # and a page to the front
    assert a.page_list() == [3, 1, 2, 0] and a.order is not None


def test_moving_a_page_forward_inside_a_section_lands_where_the_marker_was():
    a, b, c = secs = sections()
    move_pages(secs, [0], a, 2)           # dropped between the 2nd and 3rd thumbnail; page 0 itself leaves first
    assert a.page_list() == [1, 0, 2, 3]
    move_pages(secs, [1, 2], a, 4)        # two pages to the end
    assert a.page_list() == [0, 3, 1, 2]


def test_a_section_left_empty_disappears():
    a, b, c = secs = sections()
    move_pages(secs, [4, 5, 6, 7], a)
    assert secs == [a, c] and a.page_list() == [0, 1, 2, 3, 4, 5, 6, 7]


def test_new_section_and_removal():
    a, b, c = secs = sections()
    new = move_pages(secs, [9, 2], NEW_PART)
    assert new in secs and new.name == "New part" and new.page_list() == [9, 2]
    assert 9 not in c.page_list() and 2 not in a.page_list()
    assert move_pages(secs, [9, 2], None) is None              # out of every section
    assert new not in secs and unassigned_pages(secs, 12) == [2, 9]


def test_merge_and_split():
    a, b, c = secs = sections()
    assert merge_with_next(secs, a) and secs == [a, c] and a.page_list() == list(range(8))
    assert not merge_with_next(secs, c)                        # nothing after the last one
    new = split_section(secs, a, 5)
    assert new.page_list() == [5, 6, 7] and a.page_list() == [0, 1, 2, 3, 4] and new in secs
    assert split_section(secs, a, 0) is None and split_section(secs, a, 99) is None
