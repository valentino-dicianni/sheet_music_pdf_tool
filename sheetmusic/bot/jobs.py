"""What the bot does with a PDF: plain blocking functions, no Telegram in here (so they are easy to test).

Each runner takes (source PDF, work dir, progress callback) and returns (files to send, caption). Results
bigger than Telegram's 50 MB per file come back as several files (see packing.py)."""

import re
from pathlib import Path

from .. import a3, parts
from ..names import clean_name
from .packing import pack

MODES = {
    "parts": "Split into instruments (ZIP)",
    "a4": "A3 → A4 only (lossless)",
    "contrast": "A3 → A4 + better contrast",
}


def safe_name(name: str) -> str:
    """A file name Telegram and every file system accept."""
    return re.sub(r"[^\w .'()-]", "_", name)


def run_parts(src: Path, out_dir: Path, progress) -> tuple[list[Path], str]:
    work = src
    if parts.landscape_pages(src):                      # A3 sheets: OCR needs one page at a time
        work = out_dir / (src.stem + "_A4.pdf")
        parts.split_landscape(src, work)
    title, sections = parts.analyze(work, progress)
    if not sections:
        raise ValueError("no sections found")
    pdfs = parts.export_sections(work, sections, title, out_dir / "parts")
    base = safe_name(clean_name(title) if title else src.stem)
    files = pack(pdfs, base, out_dir / "send")
    summary = "\n".join(f"{s.pages:>9}  {s.name}" for s in sections)
    return files, f"{len(pdfs)} parts, title: {title or '(not found)'}\n{summary}"


def run_a4(src: Path, out_dir: Path, progress) -> tuple[list[Path], str]:
    dst = out_dir / (src.stem + "_A4.pdf")
    n = parts.split_landscape(src, dst)
    return pack([dst], safe_name(dst.stem), out_dir / "send", as_zip=False), f"{n} pages"


def run_contrast(src: Path, out_dir: Path, progress) -> tuple[list[Path], str]:
    dst, n, note = a3.process_pdf(src, out_dir / (src.stem + "_A4.pdf"), True, a3.A3Options(), set())
    return pack([dst], safe_name(dst.stem), out_dir / "send", as_zip=False), f"{n} pages" + (f" ({note})" if note else "")


RUNNERS = {"parts": run_parts, "a4": run_a4, "contrast": run_contrast}
