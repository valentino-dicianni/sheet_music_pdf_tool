import pypdfium2 as pdfium

from sheetmusic.parts import Section, export_sections, halved_path, landscape_pages, split_landscape


def widths(path):
    pdf = pdfium.PdfDocument(str(path))
    return [round(pdf[i].get_size()[0]) for i in range(len(pdf))]


def test_landscape_pages_are_halved_losslessly(make_pdf, tmp_path):
    src = make_pdf([(200, 300), (400, 300), (200, 300)])          # the middle page is an A3-like spread
    assert landscape_pages(src) == [1]
    dst = tmp_path / "halved.pdf"
    assert split_landscape(src, dst) == 4
    assert widths(dst) == [200, 200, 200, 200]                    # the spread became two portrait pages


def test_halved_path_never_overwrites(tmp_path):
    src = tmp_path / "set.pdf"
    assert halved_path(src).name == "set_A4.pdf"
    (tmp_path / "set_A4.pdf").write_bytes(b"x")
    assert halved_path(src).name == "set_A4 (2).pdf"


def test_export_one_pdf_per_section_in_the_sections_page_order(numbered_pdf, tmp_path):
    flute = Section(0, 2, "Flute")
    flute.set_pages([0, 5, 1, 2])                                  # page 5 moved in by hand
    oboe = Section(3, 4, "Oboe")
    files = export_sections(numbered_pdf, [flute, oboe], "Orient Express", tmp_path / "out")
    assert [f.name for f in files] == ["Orient Express - Flute.pdf", "Orient Express - Oboe.pdf"]
    assert widths(files[0]) == [100, 105, 101, 102]
    assert widths(files[1]) == [103, 104]


def test_export_names_never_collide(numbered_pdf, tmp_path):
    files = export_sections(numbered_pdf, [Section(0, 1, "Basses"), Section(2, 3, "Basses")], "T", tmp_path)
    assert sorted(f.name for f in files) == ["T - Basses (2).pdf", "T - Basses.pdf"]
