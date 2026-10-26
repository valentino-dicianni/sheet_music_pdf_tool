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
from .instruments import SCORE_WORDS, has_instrument, word
from .model import PageInfo, Section
from .sectioning import build_sections
from .titles import detect_title, strip_running_words

HEADER = 0.22                 # fraction of the page height that holds the title block
MARGIN = 0.14                 # fraction of the page width that holds score staff labels
SCORE_MIN_LABELS = 7          # margin text tokens needed to call a page a score page


def analyze_page(index: int, img) -> PageInfo:
    img = adjust_contrast(img, *OCR_LEVELS)
    W, H = img.size
    info = PageInfo(index)
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

    if not info.is_score:
        # score pages have the staff names in the left margin: many text tokens there, where a
        # part page has hardly any (footer and header bands are left out)
        margin = img.crop((0, int(H * 0.08), int(W * MARGIN), int(H * 0.93)))
        d = ocr_data(margin, psm=11)
        info.margin_labels = sum(1 for t, c in zip(d["text"], d["conf"])
                                 if float(c) > 50 and sum(ch.isalpha() for ch in t) >= 2)
        info.is_score = info.margin_labels >= SCORE_MIN_LABELS
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
    """A page with a few margin labels between two score pages is a (sparse) score page too."""
    for prev, page, nxt in zip(pages, pages[1:], pages[2:]):
        if not page.is_score and prev.is_score and nxt.is_score and page.margin_labels >= SCORE_MIN_LABELS // 2:
            page.is_score = True


def analyze(src: Path, progress=None) -> tuple[str, list[Section]]:
    """PDF -> (title, sections). `progress(done, total)` is called after every page."""
    pages = analyze_pages(src, progress)
    strip_running_words(pages)
    smooth_scores(pages)
    title = detect_title(pages)
    return title, build_sections(pages, title)
