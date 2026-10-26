"""A3 -> A4: split landscape pages in two, increase contrast, and name the result
"<Title> - <Instrument>.pdf" from the header of the first page (read with OCR).
Output page order: page1-left, page1-right, page2-left, page2-right, ..."""

from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import pypdfium2 as pdfium
from PIL import Image

from .imaging import OCR_LEVELS, adjust_contrast, needs_split, render_gray, split_halves
from .names import build_stem
from .ocr import OCR_DPI, OcrUnavailable, ocr_words, refine_segment, text_segments

INSTRUMENT_WORDS = {
    "piccolo", "flute", "oboe", "bassoon", "clarinet", "saxophone", "sax", "soprano",
    "alto", "tenor", "baritone", "bariton", "bass", "horn", "french horns", "trumpet", "cornet",
    "flugelhorn", "flugel", "trombone", "euphonium", "tuba", "bombardon", "percussion",
    "timpani", "drums", "mallets", "glockenspiel", "xylophone", "marimba", "vibraphone",
    "bells", "violin", "viola", "cello", "contrabass", "score", "conductor", "piano",
}


@dataclass
class A3Options:
    dpi: int = 300                  # render resolution
    black: int = 110                # levels black point 0-254
    white: int = 215                # levels white point 1-255
    gamma: float = 0.7              # < 1 darker
    header: float = 0.20            # fraction of the first page height scanned for title / instrument
    split: bool = True              # halve landscape pages
    contrast: bool = True           # apply the levels / gamma

    def validate(self) -> None:
        if not 0 <= self.black < self.white <= 255:
            raise ValueError("need 0 <= black < white <= 255")
        if self.gamma <= 0:
            raise ValueError("gamma must be > 0")
        if not 0.02 <= self.header <= 1.0:
            raise ValueError("header must be between 0.02 and 1.0")


class Job(NamedTuple):
    src: Path
    dst: Path
    rename: bool                    # name the result from its header


def detect_title_instrument(src: Path, band: float, split: bool) -> tuple[str | None, str | None]:
    """Read the score header. Title = largest text in the header, instrument = the
    segment that contains an instrument name (e.g. "Eb Alto Saxophone 2").

    The first page is rendered separately at a fixed resolution with fixed levels, so the
    result does not depend on the output dpi / contrast options."""
    page = render_gray(pdfium.PdfDocument(str(src))[0], OCR_DPI)
    if split and needs_split(page):
        page = split_halves(page)[0]          # the title lives on the first output page
    page = adjust_contrast(page, *OCR_LEVELS)
    strip = page.crop((0, 0, page.width, int(page.height * band)))
    segs = text_segments(ocr_words(strip))

    instrument = None
    for s in sorted(segs, key=lambda s: (s["top"], s["left"])):
        if any(w.lower().strip(".,;:()") in INSTRUMENT_WORDS for w in s["words"]):
            instrument = s
            break

    candidates = [s for s in segs if s is not instrument
                  and sum(c.isalnum() for c in s["text"]) >= 2]
    title = max(candidates, key=lambda s: s["height"], default=None)

    return (refine_segment(strip, title) if title else None,
            refine_segment(strip, instrument) if instrument else None)


def render_pages(src: Path, opts: A3Options) -> list[Image.Image]:
    pdf = pdfium.PdfDocument(str(src))
    pages: list[Image.Image] = []
    for i in range(len(pdf)):
        img = render_gray(pdf[i], opts.dpi)
        parts = split_halves(img) if opts.split and needs_split(img) else [img]
        for part in parts:
            if opts.contrast:
                part = adjust_contrast(part, opts.black, opts.white, opts.gamma)
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


def process_pdf(src: Path, dst: Path, rename: bool, opts: A3Options,
                used: set[Path]) -> tuple[Path, int, str]:
    """Convert one PDF. Returns (final path, number of output pages, note)."""
    pages = render_pages(src, opts)
    note = ""

    if rename:
        try:
            title, instrument = detect_title_instrument(src, opts.header, opts.split)
            if title or instrument:
                dst = dst.with_name(build_stem(title, instrument, src.stem) + ".pdf")
            else:
                note = "no title/instrument found, kept default name"
        except OcrUnavailable as exc:
            note = f"cannot rename ({exc})"

    dst = unique_path(dst, src, used)
    dst.parent.mkdir(parents=True, exist_ok=True)
    pages[0].save(dst, save_all=True, append_images=pages[1:], resolution=float(opts.dpi))
    return dst, len(pages), note


def plan_jobs(input: Path, output: Path | None = None, recursive: bool = False, rename: bool = True) -> list[Job]:
    """What to convert where. An explicit output *file* name is kept as given."""
    if input.is_file():
        if output:
            return [Job(input, output, False)]
        return [Job(input, input.with_name(input.stem + "_A4.pdf"), rename)]

    out_dir = output or (input / "A4")
    pattern = "**/*" if recursive else "*"
    out_resolved = out_dir.resolve()
    jobs = []
    for src in sorted(input.glob(pattern)):
        if not src.is_file() or src.suffix.lower() != ".pdf":
            continue
        if src.stem.endswith("_A4") or out_resolved in src.resolve().parents:
            continue  # skip our own output
        rel = src.relative_to(input)
        jobs.append(Job(src, out_dir / rel.with_name(rel.stem + ".pdf"), rename))
    return jobs
