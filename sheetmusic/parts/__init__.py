"""Split a PDF that holds a score and/or instrument parts into one PDF per part.

    analyze(pdf)               -> (title, sections)      OCR + grouping
    move_pages / merge / ...   manual corrections        (editing)
    export_sections(...)       one "<Title> - <Instrument>.pdf" per section
    split_landscape(...)       halve A3 pages first, losslessly
"""

from .analysis import analyze
from .editing import DELETE, NEW_PART, apply_move, merge_with_next, move_pages, parse_pages, split_section, unassigned_pages
from .model import PageInfo, Section, coverage, format_ranges, ranges
from .pdfio import export_sections, halved_path, landscape_pages, split_landscape

__all__ = [
    "DELETE", "NEW_PART", "PageInfo", "Section", "analyze", "apply_move", "coverage", "export_sections", "format_ranges", "halved_path",
    "landscape_pages", "merge_with_next", "move_pages", "parse_pages", "ranges", "split_landscape", "split_section",
    "unassigned_pages",
]
