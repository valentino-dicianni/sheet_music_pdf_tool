"""OCR of every page, and the whole pipeline from a PDF to its sections.

How sections are found:
  * score page  -> many text labels in the left margin (staff names), or a "Conductor"/"Score"
                   label in the header
  * title page  -> the large piece title appears at the top: a new part starts
  * other pages -> continuation; in sets without title pages a changed centered instrument header
                   starts a new part"""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pypdfium2 as pdfium

from ..imaging import OCR_LEVELS, adjust_contrast, render_gray
from ..ocr import OCR_DPI, ocr_data, ocr_words, text_segments
from .instruments import SCORE_WORDS, has_instrument, is_staff_label, word
from .model import PageInfo, Section
from .sectioning import build_sections
from .titles import detect_title, strip_running_words

HEADER = 0.22                 # fraction of the page height that holds the title block
MARGIN = 0.14                 # fraction of the page width that holds score staff labels
SCORE_MIN_LABELS = 5          # instrument names in the margin that make a page a score page (parts have <= 4)
SCORE_GAP = 3                 # pages between two score pages that are score pages too (sparse systems, rests)
LABEL_BOX = (0.0, 0.02, 0.35, 0.16)   # where a title page prints the part's name: (x0, y0, x1, y1) as page fractions
LABEL_LOW = 0.135             # a label found lower than this (page fraction) is probably a note ('Bombo'), not the name


def read_label(img) -> str:
    """The part's name at the top left of a title page, read from a close-up of just that corner. The
    whole-header pass sometimes loses a word there ('Percusion' next to its '1'); a crop reads it fine."""
    W, H = img.size
    x0, y0, x1, y1 = LABEL_BOX
    box = img.crop((int(W * x0), int(H * y0), int(W * x1), int(H * y1)))
    d = ocr_data(box.resize((box.width * 2, box.height * 2)), psm=6)
    lines: dict[tuple, list[str]] = {}
    for t, c, b, p, l in zip(d["text"], d["conf"], d["block_num"], d["par_num"], d["line_num"]):
        if t.strip() and float(c) > 40:
            lines.setdefault((b, p, l), []).append(t)
    for words in lines.values():                    # top to bottom: the first line that names an instrument
        text = " ".join(words)
        if has_instrument(text):
            return text
    return ""


def analyze_page(index: int, img) -> PageInfo:
    img = adjust_contrast(img, *OCR_LEVELS)
    W, H = img.size
    info = PageInfo(index)
    label_top = 0.0
    strip = img.crop((0, 0, W, int(H * HEADER)))
    segs = text_segments(ocr_words(strip))

    big = [s for s in segs if s["height"] >= 0.022 * W and sum(c.isalpha() for c in s["text"]) >= 4]
    big.sort(key=lambda s: (s["top"], s["left"]))
    info.title_text = " ".join(s["text"] for s in big)

    for s in sorted(segs, key=lambda s: (s["top"], s["left"])):
        words = {word(w) for w in s["words"]}
        if words & SCORE_WORDS and s["height"] < 0.022 * W:
            info.is_score = True
        if not has_instrument(s["text"]):
            continue
        center = (s["left"] + s["right"]) / 2
        if not info.header_instrument and abs(center - W / 2) < 0.15 * W and s["top"] < 0.12 * H:
            info.header_instrument = s["text"]
        elif not info.title_instrument and s["left"] < 0.12 * W:
            info.title_instrument = s["text"]
            label_top = s["top"] / H

    if info.title_instrument and label_top > LABEL_LOW:
        # read lower down than a part's name is printed: a note ('Bombo', '(Flute)'), not the name. On a title
        # page look at the corner closely instead; elsewhere there is no name.
        info.title_instrument = read_label(img) if info.title_text and not info.is_score else ""
    elif info.title_text and not info.is_score and not info.title_instrument:
        info.title_instrument = read_label(img)     # no name found by the header pass: look at the corner closely

    if not info.is_score:
        # a score has the instrument names beside its staves: several of them in the left margin, where a
        # part page has at most its own name. (Counting any text there does not work: notation reads as text.)
        margin = img.crop((0, int(H * 0.08), int(W * MARGIN), int(H * 0.93)))
        d = ocr_data(margin, psm=11)
        info.margin_instruments = sum(1 for t, c in zip(d["text"], d["conf"])
                                      if float(c) > 50 and sum(ch.isalpha() for ch in t) >= 2 and is_staff_label(t))
        info.is_score = info.margin_instruments >= SCORE_MIN_LABELS
    return info


def analyze_pages(src: Path, progress=None) -> list[PageInfo]:
    """OCR every page. pdfium is not thread safe, so pages are rendered sequentially and
    the (subprocess-based) Tesseract calls run in parallel."""
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")   # one thread per Tesseract process
    workers = max(1, (os.cpu_count() or 2) - 1)
    pdf = pdfium.PdfDocument(str(src))
    n = len(pdf)
    results: list[PageInfo] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = []
        for i in range(n):
            pending.append(pool.submit(analyze_page, i, render_gray(pdf[i], OCR_DPI)))
            # keep only a few rendered pages in memory
            while len(pending) > 2 * workers or (i == n - 1 and pending):
                results.append(pending.pop(0).result())
                if progress:
                    progress(len(results), n)
    return results


def smooth_scores(pages: list[PageInfo]) -> None:
    """A few pages between two score pages are score pages too (a sparse page of rests, a page whose
    labels were not read): a part never starts inside a score."""
    marks = [p.index for p in pages if p.is_score]
    for a, b in zip(marks, marks[1:]):
        if 1 < b - a <= SCORE_GAP + 1:
            for p in pages[a + 1:b]:
                p.is_score = True


def analyze(src: Path, progress=None) -> tuple[str, list[Section]]:
    """PDF -> (title, sections). `progress(done, total)` is called after every page."""
    pages = analyze_pages(src, progress)
    strip_running_words(pages)
    smooth_scores(pages)
    title = detect_title(pages)
    return title, build_sections(pages, title)
