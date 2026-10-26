"""Reading and writing PDFs for the parts tool: halving landscape pages, writing one PDF per section."""

from pathlib import Path

import pypdfium2 as pdfium

from ..names import clean_name
from .model import Section


def landscape_pages(src: Path) -> list[int]:
    """0-based indices of pages that are wider than tall as displayed (rotation applied),
    e.g. A3 sheets holding two A4 pages side by side."""
    pdf = pdfium.PdfDocument(str(src))
    return [i for i in range(len(pdf)) if pdf[i].get_size()[0] > pdf[i].get_size()[1]]


def _halves(box: tuple[float, float, float, float], rotation: int) -> list[tuple[float, ...]]:
    """Crop boxes (user space) of the visual left and right half of a page."""
    l, b, r, t = box
    mx, my = (l + r) / 2, (b + t) / 2
    left_right = [(l, b, mx, t), (mx, b, r, t)]      # rotation 0
    bottom_top = [(l, b, r, my), (l, my, r, t)]      # rotation 90: visual left = user bottom
    return {0: left_right, 180: left_right[::-1], 90: bottom_top, 270: bottom_top[::-1]}[rotation % 360]


def split_landscape(src: Path, dst: Path) -> int:
    """Write a copy of src where every landscape page is replaced by its left and right
    half. Lossless: each half is the original page with a smaller crop box. Returns the
    new page count."""
    pdf = pdfium.PdfDocument(str(src))
    wide = set(landscape_pages(src))
    order = [i for i in range(len(pdf)) for _ in range(2 if i in wide else 1)]
    new = pdfium.PdfDocument.new()
    new.import_pages(pdf, order)
    j = 0
    for i in range(len(pdf)):
        if i in wide:
            page = pdf[i]
            for k, box in enumerate(_halves(page.get_cropbox(), page.get_rotation())):
                half = new[j + k]
                half.set_mediabox(*box)
                half.set_cropbox(*box)
            j += 2
        else:
            j += 1
    new.save(str(dst))
    return len(new)


def halved_path(src: Path) -> Path:
    """'<stem>_A4.pdf' next to src, never overwriting an existing file."""
    dst, n = src.with_name(src.stem + "_A4.pdf"), 1
    while dst.exists():
        n += 1
        dst = src.with_name(f"{src.stem}_A4 ({n}).pdf")
    return dst


def export_sections(src: Path, sections: list[Section], title: str, out_dir: Path) -> list[Path]:
    """One '<title> - <name>.pdf' per section, pages copied losslessly in the section's order."""
    pdf = pdfium.PdfDocument(str(src))
    out_dir.mkdir(parents=True, exist_ok=True)
    title = clean_name(title) if title else src.stem
    written = []
    for s in sections:
        dst = out_dir / f"{title} - {clean_name(s.name) or 'Part'}.pdf"
        n = 1
        while dst.exists() and dst in written or dst.resolve() == src.resolve():
            n += 1
            dst = dst.with_name(f"{title} - {clean_name(s.name)} ({n}).pdf")
        new = pdfium.PdfDocument.new()
        new.import_pages(pdf, s.page_list())
        new.save(str(dst))
        written.append(dst)
    return written
