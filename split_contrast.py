#!/usr/bin/env python3
"""Split each landscape PDF page vertically into two halves (e.g. A3 landscape -> two
A4 portrait pages; portrait pages such as A4 are left whole), increase contrast, and name the result "<Title> - <Instrument>.pdf"
using the header of the score (read with OCR). Intended for scanned sheet music.

Accepts a single PDF or a directory of PDFs.
Output page order: page1-left, page1-right, page2-left, page2-right, ...

Requirements:
    pip install pypdfium2 pillow numpy pytesseract
    plus the Tesseract binary (apt install tesseract-ocr / brew install tesseract)
    Without Tesseract the script still works, it just cannot rename.

Examples:
    python split_contrast.py input.pdf                 # -> "Noah's Ark - Eb Alto Saxophone 2.pdf"
    python split_contrast.py input.pdf -o out.pdf      # explicit name, no rename
    python split_contrast.py scores/                   # -> scores/A4/<Title - Instrument>.pdf
    python split_contrast.py scores/ -o done/ -r       # recurse, custom output dir
    python split_contrast.py scores/ --no-rename       # keep original file names
    python split_contrast.py scores/ --gamma 0.6 --black 120
    python split_contrast.py input.pdf --no-contrast   # split only
    python split_contrast.py input.pdf --no-split      # contrast only
"""

import argparse
import re
import statistics
import string
import sys
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from PIL import Image

INSTRUMENT_WORDS = {
    "piccolo", "flute", "oboe", "bassoon", "clarinet", "saxophone", "sax", "soprano",
    "alto", "tenor", "baritone", "bariton", "bass", "horn", "french horns", "trumpet", "cornet",
    "flugelhorn", "flugel", "trombone", "euphonium", "tuba", "bombardon", "percussion",
    "timpani", "drums", "mallets", "glockenspiel", "xylophone", "marimba", "vibraphone",
    "bells", "violin", "viola", "cello", "contrabass", "score", "conductor", "piano",
}


OCR_DPI = 300


class OcrUnavailable(RuntimeError):
    pass


# --------------------------------------------------------------------------- image ops
def adjust_contrast(img: Image.Image, black: int, white: int, gamma: float) -> Image.Image:
    """Levels stretch (black..white -> 0..255) followed by a gamma curve.

    gamma < 1 darkens midtones, which makes thin staff lines and note stems bolder.
    """
    a = np.asarray(img.convert("L"), dtype=np.float32)
    a = np.clip((a - black) / float(white - black), 0.0, 1.0)
    a = a ** (1.0 / gamma)
    return Image.fromarray((a * 255.0 + 0.5).astype(np.uint8), mode="L")


def needs_split(img: Image.Image) -> bool:
    """Only landscape pages (e.g. A3 landscape = two A4 side by side) are split.
    Portrait pages such as A4 are already single pages and are kept whole."""
    return img.width > img.height


def split_halves(img: Image.Image) -> list[Image.Image]:
    w, h = img.size
    mid = w // 2
    return [img.crop((0, 0, mid, h)), img.crop((mid, 0, w, h))]


# --------------------------------------------------------------------------- header OCR
def _ocr_data(img: Image.Image, psm: int) -> dict:
    try:
        import pytesseract
        from pytesseract import Output
    except ImportError as exc:
        raise OcrUnavailable("pytesseract is not installed") from exc
    try:
        return pytesseract.image_to_data(img, config=f"--psm {psm}", output_type=Output.DICT)
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrUnavailable("tesseract binary not found") from exc


def _ocr_words(strip: Image.Image) -> list[dict]:
    d = _ocr_data(strip, psm=11)             # sparse text: finds every block in the header
    words = []
    for i, text in enumerate(d["text"]):
        text = text.strip()
        if not text or float(d["conf"][i]) < 60 or not any(c.isalnum() for c in text):
            continue
        words.append({"text": text, "left": d["left"][i], "top": d["top"][i],
                      "width": d["width"][i], "height": d["height"][i]})
    return words


def _refine(strip: Image.Image, seg: dict) -> str:
    """Re-read one detected line as an isolated single-line crop (psm 7). This is
    noticeably more accurate than the whole-header pass (e.g. fixes 'ARIK' -> 'ARK')."""
    pad = max(20, int(seg["height"] * 0.3))
    box = (max(seg["left"] - pad, 0), max(seg["top"] - pad, 0),
           min(seg["right"] + pad, strip.width), min(seg["bottom"] + pad, strip.height))
    d = _ocr_data(strip.crop(box), psm=7)
    good = [(d["text"][i].strip(), float(d["conf"][i])) for i in range(len(d["text"]))
            if d["text"][i].strip() and float(d["conf"][i]) >= 40]
    if good and statistics.mean(c for _, c in good) >= 60:
        return " ".join(t for t, _ in good)
    return seg["text"]


def _segments(words: list[dict]) -> list[dict]:
    """Group words into rows, then split rows into text segments at large gaps."""
    rows: list[dict] = []
    for w in sorted(words, key=lambda w: w["top"] + w["height"] / 2):
        cy = w["top"] + w["height"] / 2
        if rows and abs(cy - rows[-1]["cy"]) <= 0.6 * max(w["height"], rows[-1]["h"]):
            r = rows[-1]
            r["words"].append(w)
            r["cy"] = statistics.mean(x["top"] + x["height"] / 2 for x in r["words"])
            r["h"] = max(r["h"], w["height"])
        else:
            rows.append({"words": [w], "cy": cy, "h": w["height"]})

    segments = []
    for r in rows:
        ws = sorted(r["words"], key=lambda w: w["left"])
        gap_limit = 2.5 * statistics.median(w["height"] for w in ws)
        cur = [ws[0]]
        for prev, w in zip(ws, ws[1:]):
            if w["left"] - (prev["left"] + prev["width"]) > gap_limit:
                segments.append(cur)
                cur = []
            cur.append(w)
        segments.append(cur)

    return [{"text": " ".join(w["text"] for w in s),
             "height": statistics.median(w["height"] for w in s),
             "top": min(w["top"] for w in s),
             "bottom": max(w["top"] + w["height"] for w in s),
             "left": s[0]["left"],
             "right": max(w["left"] + w["width"] for w in s),
             "words": [w["text"] for w in s]} for s in segments]


def detect_title_instrument(src: Path, band: float, split: bool) -> tuple[str | None, str | None]:
    """Read the score header. Title = largest text in the header, instrument = the
    segment that contains an instrument name (e.g. "Eb Alto Saxophone 2").

    The first page is rendered separately at a fixed resolution with fixed levels, so the
    result does not depend on the output --dpi / contrast options."""
    pdf = pdfium.PdfDocument(str(src))
    page = pdf[0].render(scale=OCR_DPI / 72.0, grayscale=True).to_pil().convert("L")
    if split and needs_split(page):
        page = split_halves(page)[0]          # the title lives on the first output page
    page = adjust_contrast(page, 110, 215, 0.7)
    strip = page.crop((0, 0, page.width, int(page.height * band)))
    segs = _segments(_ocr_words(strip))

    instrument = None
    for s in sorted(segs, key=lambda s: (s["top"], s["left"])):
        if any(w.lower().strip(".,;:()") in INSTRUMENT_WORDS for w in s["words"]):
            instrument = s
            break

    candidates = [s for s in segs if s is not instrument
                  and sum(c.isalnum() for c in s["text"]) >= 2]
    title = max(candidates, key=lambda s: s["height"], default=None)

    return (_refine(strip, title) if title else None,
            _refine(strip, instrument) if instrument else None)


def clean_name(text: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if text.isupper():                       # "NOAH'S ARK" -> "Noah's Ark"
        text = string.capwords(text.lower())
    return text[:100]


def build_stem(title: str | None, instrument: str | None, fallback: str) -> str:
    title = clean_name(title) if title else ""
    instrument = clean_name(instrument) if instrument else ""
    if title and instrument:
        return f"{title} - {instrument}"
    if title:
        return f"{title} - {fallback}"
    if instrument:
        return f"{fallback} - {instrument}"
    return fallback


# --------------------------------------------------------------------------- processing
def render_pages(src: Path, args: argparse.Namespace) -> list[Image.Image]:
    pdf = pdfium.PdfDocument(str(src))
    scale = args.dpi / 72.0
    pages: list[Image.Image] = []
    for i in range(len(pdf)):
        img = pdf[i].render(scale=scale, grayscale=True).to_pil().convert("L")
        parts = split_halves(img) if not args.no_split and needs_split(img) else [img]
        for part in parts:
            if not args.no_contrast:
                part = adjust_contrast(part, args.black, args.white, args.gamma)
            pages.append(part)
    if not pages:
        raise ValueError("PDF has no pages")
    return pages


def unique_path(dst: Path, src: Path, used: set[Path]) -> Path:
    """Never overwrite the source, and never let two inputs of one run collide."""
    cand, n = dst, 1
    while cand.resolve() == src.resolve() or cand.resolve() in used:
        n += 1
        cand = dst.with_name(f"{dst.stem} ({n}){dst.suffix}")
    used.add(cand.resolve())
    return cand


def process_pdf(src: Path, dst: Path, rename: bool, args: argparse.Namespace,
                used: set[Path]) -> tuple[Path, int, str]:
    """Convert one PDF. Returns (final path, number of output pages, note)."""
    pages = render_pages(src, args)
    note = ""

    if rename:
        try:
            title, instrument = detect_title_instrument(src, args.header, not args.no_split)
            if title or instrument:
                dst = dst.with_name(build_stem(title, instrument, src.stem) + ".pdf")
            else:
                note = "no title/instrument found, kept default name"
        except OcrUnavailable as exc:
            note = f"cannot rename ({exc})"

    dst = unique_path(dst, src, used)
    dst.parent.mkdir(parents=True, exist_ok=True)
    pages[0].save(dst, save_all=True, append_images=pages[1:], resolution=float(args.dpi))
    return dst, len(pages), note


def collect_jobs(args: argparse.Namespace) -> list[tuple[Path, Path, bool]]:
    """Build (source, destination, rename?) tuples. An explicit -o file name is kept."""
    rename = not args.no_rename

    if args.input.is_file():
        if args.output:
            return [(args.input, args.output, False)]
        return [(args.input, args.input.with_name(args.input.stem + "_A4.pdf"), rename)]

    out_dir = args.output or (args.input / "A4")
    pattern = "**/*" if args.recursive else "*"
    out_resolved = out_dir.resolve()
    jobs = []
    for src in sorted(args.input.glob(pattern)):
        if not src.is_file() or src.suffix.lower() != ".pdf":
            continue
        if src.stem.endswith("_A4") or out_resolved in src.resolve().parents:
            continue  # skip our own output
        rel = src.relative_to(args.input)
        jobs.append((src, out_dir / rel.with_name(rel.stem + ".pdf"), rename))
    return jobs


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", type=Path, help="input PDF or directory containing PDFs")
    p.add_argument("-o", "--output", type=Path,
                   help="output PDF (file mode, name kept as given) or output directory (directory mode)")
    p.add_argument("-r", "--recursive", action="store_true", help="include subdirectories")
    p.add_argument("--no-rename", action="store_true",
                   help='keep file names instead of "<Title> - <Instrument>"')
    p.add_argument("--header", type=float, default=0.20,
                   help="fraction of the first page height scanned for title/instrument (default: 0.20)")
    p.add_argument("--dpi", type=int, default=300, help="render resolution (default: 300)")
    p.add_argument("--black", type=int, default=110, help="levels black point 0-254 (default: 110)")
    p.add_argument("--white", type=int, default=215, help="levels white point 1-255 (default: 215)")
    p.add_argument("--gamma", type=float, default=0.7, help="gamma, <1 darker (default: 0.7)")
    p.add_argument("--no-split", action="store_true", help="do not split pages")
    p.add_argument("--no-contrast", action="store_true", help="do not change contrast")
    args = p.parse_args()

    if not args.input.exists():
        print(f"error: {args.input} not found", file=sys.stderr)
        return 1
    if not 0 <= args.black < args.white <= 255:
        print("error: need 0 <= black < white <= 255", file=sys.stderr)
        return 1
    if args.gamma <= 0:
        print("error: gamma must be > 0", file=sys.stderr)
        return 1
    if not 0.02 <= args.header <= 1.0:
        print("error: --header must be between 0.02 and 1.0", file=sys.stderr)
        return 1

    jobs = collect_jobs(args)
    if not jobs:
        print(f"no PDF files found in {args.input}", file=sys.stderr)
        return 1

    used: set[Path] = set()
    failed = 0
    for n, (src, dst, rename) in enumerate(jobs, 1):
        print(f"[{n}/{len(jobs)}] {src} ...", end=" ", flush=True)
        try:
            out, count, note = process_pdf(src, dst, rename, args, used)
            print(f"-> {out} ({count} pages)" + (f"  [{note}]" if note else ""))
        except Exception as exc:  # keep going on a bad file
            failed += 1
            print(f"FAILED: {exc}")

    print(f"done: {len(jobs) - failed} ok, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
