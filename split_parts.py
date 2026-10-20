#!/usr/bin/env python3
"""Split a PDF that contains a full score and/or instrument parts into one PDF per
part, named "<Title> - <Instrument>.pdf" (the score becomes "<Title> - Score.pdf").
Intended for scanned band / orchestra sets. Pages are copied losslessly.

How sections are found (with OCR on every page):
  * score page  -> many instrument abbreviations in the left margin (Fl., Ob., Bsn., ...)
                   or a "Conductor"/"Score" label in the header (cover page)
  * title page  -> the large piece title appears at the top: a new part starts
  * landscape pages (two A4 side by side) can be halved first, losslessly (asked)
  * other pages -> continuation; if the instrument centered at the top changes
                   (and there was no title page) a new part starts as well

Requirements: pip install pypdfium2 pillow numpy pytesseract  (+ Tesseract binary)

Examples:
    python split_parts.py set.pdf                  # -> set_parts/<Title> - <Instrument>.pdf
    python split_parts.py set.pdf -o out/          # custom output directory
    python split_parts.py set.pdf --dry-run        # only print the detected sections
    python split_parts.py set.pdf --title "Evita"  # override the detected title
    python split_parts.py a3set.pdf --split-landscape yes   # halve A3 pages first, no question
"""

import argparse
import difflib
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium

from split_contrast import OcrUnavailable, _ocr_data, _ocr_words, _segments, adjust_contrast, clean_name

OCR_DPI = 300
HEADER = 0.22                 # fraction of the page height that holds the title block
MARGIN = 0.14                 # fraction of the page width that holds score staff labels
SCORE_MIN_LABELS = 5          # margin abbreviations needed to call a page a score page

INSTRUMENTS = [
    "piccolo", "flute", "oboe", "english", "bassoon", "contrabassoon", "clarinet", "saxophone",
    "soprano", "alto", "tenor", "baritone", "bariton", "bass", "basses", "horn", "horns",
    "hoorn", "trumpet", "cornet", "flugelhorn", "trombone", "euphonium", "tuba", "bombardon",
    "percussion", "timpani", "drums", "drum", "mallet", "mallets", "glockenspiel", "xylophone",
    "marimba", "vibraphone", "bells", "chimes", "violin", "viola", "cello", "violoncello",
    "contrabass", "string", "strings", "piano", "keyboard", "guitar", "harp", "organ",
    "conductor", "score",
]
SCORE_WORDS = {"conductor", "score", "partitur", "partitura", "direttore"}
MARGIN_ABBREVS = {
    "fl", "flute", "picc", "ob", "oboe", "bsn", "bassoon", "cl", "clar", "sx", "sax", "tpt",
    "trp", "hn", "horn", "tbn", "trb", "bar", "euph", "tuba", "perc", "timp", "mlt", "mallet",
    "vln", "vla", "vc", "cb", "bass", "bs", "db",
}
TRANSPOSITIONS = ("Bb", "Eb", "F", "C", "D", "G", "A")
ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "l": "1"}


@dataclass
class PageInfo:
    index: int
    is_score: bool = False
    title_text: str = ""          # big title found on this page ("" if none)
    title_instrument: str = ""    # instrument printed next to the title (title pages)
    header_instrument: str = ""   # instrument centered at the top (continuation pages)


@dataclass
class Section:
    start: int                    # 0-based, inclusive
    end: int                      # 0-based, inclusive
    name: str                     # instrument, or "Score"
    is_score: bool = False
    candidates: list[str] = field(default_factory=list)   # title-page guess + headers (x2)
    headers: list[str] = field(default_factory=list)      # centered instrument headers

    @property
    def pages(self) -> str:
        return f"{self.start + 1}-{self.end + 1}" if self.end > self.start else f"{self.start + 1}"


# --------------------------------------------------------------------------- text helpers
def _word(w: str) -> str:
    return re.sub(r"[^a-z]", "", w.lower())


def _canonical(word: str) -> str | None:
    """Map an OCR word to a known instrument word, tolerating clipped/misread letters
    ('ASSOON' -> 'bassoon', '3ARITONE' -> 'baritone')."""
    w = _word(word)
    if len(w) < 3:
        return None
    if w in INSTRUMENTS:
        return w
    if len(w) < 4:
        return "oboe" if w == "boe" else None
    match = difflib.get_close_matches(w, INSTRUMENTS, n=1, cutoff=0.8)
    return match[0] if match else None


def has_instrument(text: str) -> bool:
    return any(_canonical(w) for w in text.split())


def normalize_instrument(text: str) -> str:
    """'3> TRUMPET 2' -> 'Bb Trumpet 2', 'F HORN I' -> 'F Horn 1', 'ASSOON' -> 'Bassoon'."""
    tokens = text.replace(",", " ").split()
    out: list[str] = []
    for i, tok in enumerate(tokens):
        canon = _canonical(tok)
        low = tok.lower().strip(".:;")
        if canon:
            out.append(canon.capitalize())
        elif re.fullmatch(r"\d+", low):
            out.append(low)
        elif low in ROMAN and out:
            out.append(ROMAN[low])
        elif i == 0 and len(tok) <= 3:          # transposition printed before the name
            first = tok[0]
            if first in "B3b8":
                out.append("Bb")
            elif first in "Ee":
                out.append("Eb")
            elif tok in ("F", "C", "D", "G", "A"):
                out.append(tok)
        elif re.fullmatch(r"[A-Ga-g][b#>]?", tok):  # "Hoorn 1 Eb", "Trombone Bb 1"
            out.append(tok[0].upper() + ("b" if len(tok) > 1 else ""))
        elif re.fullmatch(r"[A-Z]\.([A-Z]\.?)?,?", tok):   # "T.C.", "B.C"
            out.append(tok.rstrip(",") + ("" if tok.rstrip(",").endswith(".") else "."))
        elif re.fullmatch(r"[BT]C", tok):                 # "Bariton BC" (bass / treble clef)
            out.append(f"{tok[0]}.C.")
    # transposition goes first: "Hoorn 1 Eb" / "Trombone Bb 1" -> "Eb Hoorn 1" / "Bb Trombone 1"
    keys = [t for t in out[1:] if t in TRANSPOSITIONS]
    if keys and out[0] not in TRANSPOSITIONS:
        out = [keys[0]] + [t for t in out if t != keys[0]]
    return " ".join(out)


def instrument_key(name: str) -> str:
    """Comparable key without transposition: 'Bb Clarinet 2' and 'Clarinet 2' match."""
    return " ".join(t.lower() for t in name.split() if t not in TRANSPOSITIONS)


def same_instrument(a: str, b: str) -> bool:
    ka, kb = instrument_key(a), instrument_key(b)
    da, db = re.findall(r"\d+", ka), re.findall(r"\d+", kb)
    if da and db and da != db:
        return False
    ka, kb = re.sub(r"\s*\d+", "", ka), re.sub(r"\s*\d+", "", kb)
    return difflib.SequenceMatcher(None, ka, kb).ratio() >= 0.85


def _title_words(text: str) -> set[str]:
    return {w for w in (_word(t) for t in text.split()) if len(w) >= 3}


# --------------------------------------------------------------------------- page analysis
def _analyze(index: int, img) -> PageInfo:
    img = adjust_contrast(img, 110, 215, 0.7)
    W, H = img.size
    info = PageInfo(index)
    strip = img.crop((0, 0, W, int(H * HEADER)))
    segs = _segments(_ocr_words(strip))

    big = [s for s in segs if s["height"] >= 0.022 * W and sum(c.isalpha() for c in s["text"]) >= 4]
    big.sort(key=lambda s: (s["top"], s["left"]))
    info.title_text = " ".join(s["text"] for s in big)

    for s in sorted(segs, key=lambda s: (s["top"], s["left"])):
        words = {_word(w) for w in s["words"]}
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
        margin = img.crop((0, int(H * 0.05), int(W * MARGIN), H))
        d = _ocr_data(margin, psm=11)
        labels = sum(_word(t) in MARGIN_ABBREVS for t, c in zip(d["text"], d["conf"])
                     if t.strip() and float(c) > 50)
        info.is_score = labels >= SCORE_MIN_LABELS
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
            img = pdf[i].render(scale=OCR_DPI / 72.0, grayscale=True).to_pil().convert("L")
            pending.append(pool.submit(_analyze, i, img))
            # keep only a few rendered pages in memory
            while len(pending) > 2 * workers or (i == n - 1 and pending):
                results.append(pending.pop(0).result())
                if progress:
                    progress(len(results), n)
    return results


def detect_title(pages: list[PageInfo]) -> str:
    """The most frequent large heading. Title pages that OCR split in two ('Highlights
    From' / 'From EVITA') are matched by word overlap."""
    texts = [p.title_text for p in pages if p.title_text and not p.is_score]
    if not texts:
        texts = [p.title_text for p in pages if p.title_text]
    if not texts:
        return ""
    counts = Counter(re.sub(r"\s+", " ", t).strip() for t in texts)
    best = max(counts, key=lambda t: (sum(len(_title_words(t) & _title_words(o)) > 0 for o in texts),
                                      counts[t], len(t)))
    return best


def is_title_page(page: PageInfo, title: str) -> bool:
    tw = _title_words(title)
    if not tw or not page.title_text:
        return False
    return len(tw & _title_words(page.title_text)) >= max(1, len(tw) // 2)


# --------------------------------------------------------------------------- sectioning
def build_sections(pages: list[PageInfo], title: str) -> list[Section]:
    sections: list[Section] = []

    def start(i: int, is_score: bool, cand: str = "") -> None:
        sections.append(Section(i, i, "Score" if is_score else "", is_score, [cand] if cand else []))

    for p in pages:
        cur = sections[-1] if sections else None
        if p.is_score:
            if cur and cur.is_score:
                cur.end = p.index
            else:
                start(p.index, True)
            continue

        header = normalize_instrument(p.header_instrument) if p.header_instrument else ""
        if is_title_page(p, title) or cur is None or cur.is_score:
            start(p.index, False, normalize_instrument(p.title_instrument) if p.title_instrument else "")
        elif header and cur.headers and not any(same_instrument(header, h) for h in cur.headers):
            start(p.index, False)               # instrument changed without a title page
        else:
            cur.end = p.index
        if header:
            sections[-1].headers.append(header)
            sections[-1].candidates += [header, header]   # centered headers are more reliable

    for s in sections:
        if not s.is_score:
            s.name = choose_name(s.candidates) or f"Part {s.pages}"
    dedupe_names(sections)
    return sections


def choose_name(candidates: list[str]) -> str:
    cands = [c for c in candidates if instrument_key(c)]
    if not cands:
        return ""
    groups: list[list[str]] = []
    for c in cands:
        g = next((g for g in groups if same_instrument(g[0], c)), None)
        if g:
            g.append(c)
        else:
            groups.append([c])
    group = max(groups, key=len)
    # prefer the spelling that has a transposition ("Bb Clarinet 2"), then the most common
    return max(group, key=lambda c: (c.split()[0] in TRANSPOSITIONS, bool(re.search(r"\d", c)),
                                     group.count(c), len(c)))


def dedupe_names(sections: list[Section]) -> None:
    seen = Counter(s.name for s in sections)
    n = Counter()
    for s in sections:
        if seen[s.name] > 1:
            n[s.name] += 1
            s.name = f"{s.name} ({n[s.name]})"


def _ranges(pages: list[int]) -> list[tuple[int, int]]:
    """[0,1,2,5] -> [(0,2),(5,5)] (0-based, inclusive)."""
    out: list[tuple[int, int]] = []
    for p in sorted(pages):
        if out and p == out[-1][1] + 1:
            out[-1] = (out[-1][0], p)
        else:
            out.append((p, p))
    return out


def coverage(sections: list[Section], npages: int) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Return (missing, duplicated) page ranges, 0-based inclusive, so callers can make
    sure every page of the original ends up in exactly one output file."""
    count = Counter(p for s in sections for p in range(s.start, s.end + 1))
    return (_ranges([p for p in range(npages) if count[p] == 0]),
            _ranges([p for p in range(npages) if count[p] > 1]))


def format_ranges(ranges: list[tuple[int, int]]) -> str:
    return ", ".join(f"{a + 1}-{b + 1}" if b > a else f"{a + 1}" for a, b in ranges)


def analyze(src: Path, progress=None) -> tuple[str, list[Section]]:
    pages = analyze_pages(src, progress)
    title = detect_title(pages)
    return title, build_sections(pages, title)


# --------------------------------------------------------------------------- landscape pages
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


# --------------------------------------------------------------------------- export
def halved_path(src: Path) -> Path:
    """'<stem>_A4.pdf' next to src, never overwriting an existing file."""
    dst, n = src.with_name(src.stem + "_A4.pdf"), 1
    while dst.exists():
        n += 1
        dst = src.with_name(f"{src.stem}_A4 ({n}).pdf")
    return dst


def export_sections(src: Path, sections: list[Section], title: str, out_dir: Path) -> list[Path]:
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
        new.import_pages(pdf, list(range(s.start, s.end + 1)))
        new.save(str(dst))
        written.append(dst)
    return written


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", type=Path, help="PDF containing score and/or parts")
    p.add_argument("-o", "--output", type=Path, help="output directory (default: <input>_parts/)")
    p.add_argument("--title", help="piece title used in the file names (default: detected)")
    p.add_argument("--dry-run", action="store_true", help="only show the detected sections")
    p.add_argument("--split-landscape", choices=("ask", "yes", "no"), default="ask",
                   help="halve landscape (A3 = 2xA4) pages before splitting parts (default: ask)")
    args = p.parse_args()

    if not args.input.is_file():
        print(f"error: {args.input} not found", file=sys.stderr)
        return 1
    out_dir = args.output or args.input.with_name(args.input.stem + "_parts")
    wide = landscape_pages(args.input)
    if wide and args.split_landscape != "no":
        print(f"{len(wide)} of {len(pdfium.PdfDocument(str(args.input)))} pages are landscape "
              f"(pages {format_ranges(_ranges(wide))}), probably two pages side by side.")
        answer = "y" if args.split_landscape == "yes" else (
            input("Split them in half first? [Y/n] ").strip().lower() if sys.stdin.isatty() else "n")
        if answer in ("", "y", "yes"):
            dst = halved_path(args.input)
            print(f"-> {dst} ({split_landscape(args.input, dst)} pages)")
            args.input = dst
    try:
        title, sections = analyze(args.input, lambda d, n: print(f"\ranalyzing page {d}/{n}",
                                                                end="", file=sys.stderr, flush=True))
    except OcrUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(file=sys.stderr)
    title = args.title or title
    print(f"title: {title or '(not found)'}")
    for s in sections:
        print(f"  pages {s.pages:>8}  {s.name}")
    missing, dup = coverage(sections, len(pdfium.PdfDocument(str(args.input))))
    if missing or dup:   # cannot happen with build_sections, but never lose a page silently
        print(f"warning: missing pages {format_ranges(missing)}; duplicated {format_ranges(dup)}",
              file=sys.stderr)
    if args.dry_run:
        return 0
    for f in export_sections(args.input, sections, title, out_dir):
        print(f"-> {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
