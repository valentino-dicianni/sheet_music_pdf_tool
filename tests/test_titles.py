from sheetmusic.parts.model import PageInfo
from sheetmusic.parts.titles import detect_title, has_title_in_header, is_title_page, strip_running_words


def pages_with_watermark():
    """A watermark heads every page, the title only the first page of each 3-page part."""
    pages = []
    for i in range(12):
        text = "WATERMARK" + (" Orient Express" if i % 3 == 0 else "")
        pages.append(PageInfo(i, title_text=text))
    return pages


def test_running_words_are_not_the_title():
    pages = pages_with_watermark()
    strip_running_words(pages)
    assert [p.title_text for p in pages[:4]] == ["Orient Express", "", "", "Orient Express"]
    assert detect_title(pages) == "Orient Express"


def test_title_on_every_page_is_also_a_running_word():
    pages = [PageInfo(i, title_text="Orient Express") for i in range(8)]
    strip_running_words(pages)
    assert detect_title(pages) == ""            # sets like this are split by their instrument headers instead


def test_title_in_the_header_line_is_told_from_a_plain_header():
    assert has_title_in_header(PageInfo(3, header_instrument="Flute I WATERMARK Orient Express"), "Orient Express")
    assert not has_title_in_header(PageInfo(4, header_instrument="Flute I"), "Orient Express")
    assert not is_title_page(PageInfo(3, header_instrument="Flute I WATERMARK Orient Express"), "Orient Express")


def test_publisher_words_next_to_the_title_are_dropped_and_noise_is_trimmed():
    texts = ["NOAH'S ARK", "UNIO. NOAH'S ARK", "NOAH'S ARK", "NOAH'S ARK", "UNIO. NOAH'S ARK", "NOAH'S ARK It of", "NOAH'S ARK"]
    pages = [PageInfo(i, title_text=t) for i, t in enumerate(texts)]
    assert detect_title(pages) == "NOAH'S ARK"


def test_a_longer_movement_heading_that_contains_the_title_word_is_not_a_title_page():
    assert is_title_page(PageInfo(0, title_text="Pinocho Gepeto"), "Pinocho Gepeto")
    assert is_title_page(PageInfo(1, title_text="Pinocho"), "Pinocho Gepeto")                           # one of the two words
    assert not is_title_page(PageInfo(2, title_text="IV. Pinocho; Historia dunha Marioneta"), "Pinocho Gepeto")
    assert is_title_page(PageInfo(3, title_text="NOAH'S ARK Bert Appermont Maestoso J 65"), "NOAH'S ARK")   # still a title page


def test_a_header_line_with_a_credit_after_the_title_still_counts():
    line = "Timpani ARCHIVOCUCOSAX and (Steam) Train Whistle Orient Express"
    assert has_title_in_header(PageInfo(0, header_instrument=line), "Orient Express")
    assert not has_title_in_header(PageInfo(0, header_instrument="Timpani and (Steam) Train Whistle"), "Orient Express")
