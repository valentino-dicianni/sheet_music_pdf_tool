import pypdfium2 as pdfium
import pytest

from sheetmusic.a3 import A3Options, plan_jobs, process_pdf
from sheetmusic.names import build_stem, clean_name


def test_options_validation():
    A3Options().validate()
    for bad in (A3Options(black=200, white=100), A3Options(gamma=0), A3Options(header=2.0)):
        with pytest.raises(ValueError):
            bad.validate()


def test_names():
    assert clean_name("NOAH'S ARK") == "Noah's Ark"
    assert clean_name('a/b:c?"d"') == "a b c d"
    assert build_stem("Evita", "Flute 1", "scan") == "Evita - Flute 1"
    assert build_stem(None, None, "scan") == "scan"


def test_plan_jobs_for_a_file_and_a_folder(make_pdf, tmp_path):
    one = make_pdf([(200, 300)], "one.pdf")
    assert plan_jobs(one)[0].dst.name == "one_A4.pdf" and plan_jobs(one)[0].rename
    assert not plan_jobs(one, tmp_path / "chosen.pdf")[0].rename               # an explicit name is kept
    sub = tmp_path / "scores"
    sub.mkdir()
    (sub / "a.pdf").write_bytes(one.read_bytes())
    (sub / "b_A4.pdf").write_bytes(one.read_bytes())                           # our own output is skipped
    jobs = plan_jobs(sub)
    assert [j.src.name for j in jobs] == ["a.pdf"] and jobs[0].dst == sub / "A4" / "a.pdf"


def test_a3_to_a4_doubles_landscape_pages_only(make_pdf, tmp_path):
    src = make_pdf([(400, 300), (200, 300)])
    dst, pages, note = process_pdf(src, tmp_path / "out.pdf", False, A3Options(dpi=72), set())
    out = pdfium.PdfDocument(str(dst))
    assert pages == 3 and len(out) == 3
    assert [round(out[i].get_size()[0]) for i in range(3)] == [200, 200, 200]
    # a second run into the same name does not overwrite
    again, _, _ = process_pdf(src, tmp_path / "out.pdf", False, A3Options(dpi=72), {dst.resolve()})
    assert again.name == "out (2).pdf"
