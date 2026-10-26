import pypdfium2 as pdfium

from sheetmusic.bot.jobs import RUNNERS, run_a4, safe_name


def test_safe_name():
    assert safe_name("Noah's Ark / Flute: 1.pdf") == "Noah's Ark _ Flute_ 1.pdf"


def test_run_a4_halves_landscape_pages(make_pdf, tmp_path):
    src = make_pdf([(400, 300), (200, 300)])
    dst, caption = run_a4(src, tmp_path, lambda done, total: None)
    assert dst.name == "in_A4.pdf" and caption == "3 pages" and len(pdfium.PdfDocument(str(dst))) == 3


def test_every_mode_has_a_runner():
    from sheetmusic.bot.jobs import MODES
    assert set(MODES) == set(RUNNERS)
