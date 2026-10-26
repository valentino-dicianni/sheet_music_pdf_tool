"""Command line front ends:  python -m sheetmusic parts ...   /   python -m sheetmusic a3 ..."""

import argparse
import sys
from pathlib import Path

import pypdfium2 as pdfium

from . import a3, parts
from .ocr import OcrUnavailable

PARTS_HELP = """Split a PDF that contains a full score and/or instrument parts into one PDF per
part, named "<Title> - <Instrument>.pdf" (the score becomes "<Title> - Score.pdf").
Intended for scanned band / orchestra sets. Pages are copied losslessly.

Examples:
    python -m sheetmusic parts set.pdf                  # -> set_parts/<Title> - <Instrument>.pdf
    python -m sheetmusic parts set.pdf -o out/          # custom output directory
    python -m sheetmusic parts set.pdf --dry-run        # only print the detected sections
    python -m sheetmusic parts set.pdf --title "Evita"  # override the detected title
    python -m sheetmusic parts a3set.pdf --split-landscape yes   # halve A3 pages first, no question
"""

A3_HELP = """Split each landscape PDF page vertically into two halves (e.g. A3 landscape -> two
A4 portrait pages; portrait pages such as A4 are left whole), increase contrast, and name the
result "<Title> - <Instrument>.pdf" using the header of the score (read with OCR).
Accepts a single PDF or a directory of PDFs.

Examples:
    python -m sheetmusic a3 input.pdf                 # -> "Noah's Ark - Eb Alto Saxophone 2.pdf"
    python -m sheetmusic a3 input.pdf -o out.pdf      # explicit name, no rename
    python -m sheetmusic a3 scores/                   # -> scores/A4/<Title - Instrument>.pdf
    python -m sheetmusic a3 scores/ -o done/ -r       # recurse, custom output dir
    python -m sheetmusic a3 scores/ --no-rename       # keep original file names
    python -m sheetmusic a3 scores/ --gamma 0.6 --black 120
    python -m sheetmusic a3 input.pdf --no-contrast   # split only
    python -m sheetmusic a3 input.pdf --no-split      # contrast only
"""


def parts_main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sheetmusic parts", description=PARTS_HELP,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", type=Path, help="PDF containing score and/or parts")
    p.add_argument("-o", "--output", type=Path, help="output directory (default: <input>_parts/)")
    p.add_argument("--title", help="piece title used in the file names (default: detected)")
    p.add_argument("--dry-run", action="store_true", help="only show the detected sections")
    p.add_argument("--split-landscape", choices=("ask", "yes", "no"), default="ask",
                   help="halve landscape (A3 = 2xA4) pages before splitting parts (default: ask)")
    args = p.parse_args(argv)

    if not args.input.is_file():
        print(f"error: {args.input} not found", file=sys.stderr)
        return 1
    src = args.input
    out_dir = args.output or src.with_name(src.stem + "_parts")
    wide = parts.landscape_pages(src)
    if wide and args.split_landscape != "no":
        print(f"{len(wide)} of {len(pdfium.PdfDocument(str(src)))} pages are landscape "
              f"(pages {parts.format_ranges(parts.ranges(wide))}), probably two pages side by side.")
        answer = "y" if args.split_landscape == "yes" else (
            input("Split them in half first? [Y/n] ").strip().lower() if sys.stdin.isatty() else "n")
        if answer in ("", "y", "yes"):
            dst = parts.halved_path(src)
            print(f"-> {dst} ({parts.split_landscape(src, dst)} pages)")
            src = dst
    try:
        title, sections = parts.analyze(src, lambda d, n: print(f"\ranalyzing page {d}/{n}",
                                                                end="", file=sys.stderr, flush=True))
    except OcrUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(file=sys.stderr)
    title = args.title or title
    print(f"title: {title or '(not found)'}")
    for s in sections:
        print(f"  pages {s.pages:>8}  {s.name}")
    missing, dup = parts.coverage(sections, len(pdfium.PdfDocument(str(src))))
    if missing or dup:   # cannot happen with build_sections, but never lose a page silently
        print(f"warning: missing pages {parts.format_ranges(missing)}; duplicated {parts.format_ranges(dup)}",
              file=sys.stderr)
    if args.dry_run:
        return 0
    for f in parts.export_sections(src, sections, title, out_dir):
        print(f"-> {f}")
    return 0


def a3_main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sheetmusic a3", description=A3_HELP,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
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
    args = p.parse_args(argv)

    if not args.input.exists():
        print(f"error: {args.input} not found", file=sys.stderr)
        return 1
    opts = a3.A3Options(dpi=args.dpi, black=args.black, white=args.white, gamma=args.gamma,
                        header=args.header, split=not args.no_split, contrast=not args.no_contrast)
    try:
        opts.validate()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    jobs = a3.plan_jobs(args.input, args.output, args.recursive, rename=not args.no_rename)
    if not jobs:
        print(f"no PDF files found in {args.input}", file=sys.stderr)
        return 1

    used: set[Path] = set()
    failed = 0
    for n, (src, dst, rename) in enumerate(jobs, 1):
        print(f"[{n}/{len(jobs)}] {src} ...", end=" ", flush=True)
        try:
            out, count, note = a3.process_pdf(src, dst, rename, opts, used)
            print(f"-> {out} ({count} pages)" + (f"  [{note}]" if note else ""))
        except Exception as exc:  # keep going on a bad file
            failed += 1
            print(f"FAILED: {exc}")

    print(f"done: {len(jobs) - failed} ok, {failed} failed")
    return 1 if failed else 0
