"""Manual changes to the grouping, as plain functions on a list of sections (no GUI in here)."""

import re

from .model import Section, coverage

NEW_PART = "new"        # `move_pages` target that creates a section
DELETE = "delete"       # `apply_move` target: pages that are not wanted (blank, unused); not exported, not "missing"
_PAGES_RE = re.compile(r"^\s*(\d+)\s*(?:[-–]\s*(\d+))?\s*$")


def parse_pages(text: str, npages: int) -> list[int] | None:
    """'3-5, 9' -> [2, 3, 4, 8] (0-based, in the order typed); None if invalid or out of range."""
    pages: list[int] = []
    for part in text.split(","):
        m = _PAGES_RE.match(part)
        if not m:
            return None
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if not 1 <= a <= b <= npages:
            return None
        pages += range(a - 1, b)
    return list(dict.fromkeys(pages)) or None


def unassigned_pages(sections: list[Section], npages: int, deleted=()) -> list[int]:
    """Pages in no section that were not deleted on purpose: the ones to look at."""
    missing, _ = coverage(sections, npages)
    return [p for a, b in missing for p in range(a, b + 1) if p not in deleted]


def apply_move(sections: list[Section], deleted: set[int], pages: list[int], target, row: int = -1) -> Section | None:
    """`move_pages` that also knows deleted pages: `DELETE` takes the pages out of every section and remembers them in
    `deleted`; moving them to a section (or a new one) brings them back. Edits both in place."""
    moving = list(dict.fromkeys(pages))
    if target == DELETE:
        move_pages(sections, moving, None)
        deleted.update(moving)
        return None
    deleted.difference_update(moving)
    return move_pages(sections, moving, target, row)


def move_pages(sections: list[Section], pages: list[int], target, row: int = -1) -> Section | None:
    """Move pages to a section (inserted at position `row`, -1 = end), to a new section (`NEW_PART`)
    or out of every section (`None`). A section left without pages disappears. Edits `sections` in
    place and returns the section the pages ended up in (None when they were removed)."""
    moving = list(dict.fromkeys(pages))
    moved = set(moving)
    if not moving:
        return None
    if isinstance(target, Section) and row >= 0:
        row -= sum(1 for p in target.page_list()[:row] if p in moved)   # earlier moved pages leave first
    base: list[int] = []
    for sec in list(sections):
        keep = [p for p in sec.page_list() if p not in moved]
        if sec is target:
            base = keep
        elif len(keep) != len(sec.page_list()):
            if keep:
                sec.set_pages(keep)
            else:
                sections.remove(sec)
    if isinstance(target, Section):
        at = len(base) if row < 0 else min(row, len(base))
        target.set_pages(base[:at] + moving + base[at:])
        return target
    if target == NEW_PART:
        new = Section(min(moving), max(moving), "New part")
        new.set_pages(moving)
        sections.append(new)
        return new
    return None


def merge_with_next(sections: list[Section], sec: Section) -> bool:
    """Join `sec` with the section after it in the list; False if it is the last one."""
    i = sections.index(sec)
    if i + 1 >= len(sections):
        return False
    nxt = sections.pop(i + 1)
    sec.set_pages(sorted(set(sec.page_list()) | set(nxt.page_list())))
    return True


def split_section(sections: list[Section], sec: Section, first_page: int) -> Section | None:
    """Cut `sec` in two: pages before `first_page` (0-based) stay, the rest become a new section."""
    left = [p for p in sec.page_list() if p < first_page]
    right = [p for p in sec.page_list() if p >= first_page]
    if not left or not right:
        return None
    new = Section(min(right), max(right), f"{sec.name} (2)")
    new.set_pages(right)
    sec.set_pages(left)
    sections.append(new)
    return new
