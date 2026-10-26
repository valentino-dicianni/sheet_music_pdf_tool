"""What the analysis produces and what the user edits: per-page findings and sections of pages."""

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class PageInfo:
    """What OCR found on one page."""
    index: int
    is_score: bool = False
    title_text: str = ""          # big title found on this page ("" if none)
    title_instrument: str = ""    # instrument printed next to the title (title pages)
    header_instrument: str = ""   # instrument centered at the top (continuation pages)
    margin_instruments: int = 0   # instrument names / abbreviations in the left margin (staff labels of a score)


@dataclass
class Section:
    """One output file: a score or an instrument part."""
    start: int                    # 0-based, inclusive
    end: int                      # 0-based, inclusive
    name: str                     # instrument, or "Score"
    is_score: bool = False
    candidates: list[str] = field(default_factory=list)   # title-page guess + headers (x2)
    headers: list[str] = field(default_factory=list)      # centered instrument headers
    order: list[int] | None = None  # explicit pages in output order, once pages were moved by hand
    inferred: bool = False        # started because parts are evenly spaced, not because a title was read
    titled: bool = False          # opened by its own title page (not by a leftover page or a header change)

    def page_list(self) -> list[int]:
        """0-based pages of this section in output order."""
        return list(self.order) if self.order is not None else list(range(self.start, self.end + 1))

    def set_pages(self, pages: list[int]) -> None:
        self.start, self.end = min(pages), max(pages)
        self.order = None if pages == list(range(self.start, self.end + 1)) else list(pages)

    @property
    def pages(self) -> str:
        """'61, 143, 62-64': runs of consecutive pages in output order."""
        runs: list[tuple[int, int]] = []
        for p in self.page_list():
            runs.append((runs[-1][0], p) if runs and p == runs[-1][1] + 1 else (p, p))
            if len(runs) > 1 and runs[-1][0] == runs[-2][0]:
                del runs[-2]
        return format_ranges(runs)


def ranges(pages: list[int]) -> list[tuple[int, int]]:
    """[0,1,2,5] -> [(0,2),(5,5)] (0-based, inclusive)."""
    out: list[tuple[int, int]] = []
    for p in sorted(pages):
        if out and p == out[-1][1] + 1:
            out[-1] = (out[-1][0], p)
        else:
            out.append((p, p))
    return out


def format_ranges(rs: list[tuple[int, int]]) -> str:
    """[(0,2),(5,5)] -> '1-3, 6' (1-based, for people)."""
    return ", ".join(f"{a + 1}-{b + 1}" if b > a else f"{a + 1}" for a, b in rs)


def coverage(sections: list[Section], npages: int) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Return (missing, duplicated) page ranges, 0-based inclusive, so callers can make
    sure every page of the original ends up in exactly one output file."""
    count = Counter(p for s in sections for p in s.page_list())
    return (ranges([p for p in range(npages) if count[p] == 0]),
            ranges([p for p in range(npages) if count[p] > 1]))
