from sheetmusic.parts.model import PageInfo
from sheetmusic.parts.titles import detect_title, is_title_page, strip_running_words


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


def test_title_page_when_ocr_merged_title_and_instrument_into_one_line():
    page = PageInfo(3, header_instrument="Flute I WATERMARK Orient Express")
    assert is_title_page(page, "Orient Express")
    assert not is_title_page(PageInfo(4, header_instrument="Flute I"), "Orient Express")
