"""Pages (with their OCR findings) -> named sections."""

import re
from collections import Counter

from .instruments import TRANSPOSITIONS, instrument_key, normalize_instrument, same_instrument
from .model import PageInfo, Section
from .titles import is_title_page

MIN_TITLE_PAGES = 3           # title pages needed before they are trusted as the only part boundaries


def build_sections(pages: list[PageInfo], title: str) -> list[Section]:
    sections: list[Section] = []
    # Headers are read with OCR noise ('Flute If', 'Clarinet U'), so a changed header only starts a
    # part in sets without title pages; where every part has one, the title pages are the boundaries.
    has_title_pages = sum(is_title_page(p, title) and not p.is_score for p in pages) >= MIN_TITLE_PAGES

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
        elif not has_title_pages and header and cur.headers and not any(same_instrument(header, h) for h in cur.headers):
            start(p.index, False)               # instrument changed without a title page
        else:
            cur.end = p.index
        if header:
            sections[-1].headers.append(header)
            sections[-1].candidates += [header, header]   # centered headers are more reliable

    if len(sections) > 1 and sections[1].is_score and not sections[0].is_score and not sections[0].headers:
        sections[1].start = sections[0].start       # cover / foreword pages go with the score
        del sections[0]
    for s in sections:
        if not s.is_score:
            s.name = choose_name(s.candidates) or f"Part {s.pages}"
    number_siblings(sections)
    tidy_percussion(sections)
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


def number_siblings(sections: list[Section]) -> None:
    """Parts of one family ('Bb Trumpet 1', 'Bb Trumpet 2', 'Bb Trumpet') where OCR lost a numeral:
    if the missing numbers are unambiguous, give them to the unnumbered ones (in page order)."""
    families: dict[str, list[Section]] = {}
    for s in sections:
        if not s.is_score and instrument_key(s.name) and not s.name.startswith("Part "):  # keep Eb / Bb apart
            families.setdefault(re.sub(r"\s*\d+", "", s.name).lower(), []).append(s)
    for members in families.values():
        have = {int(m.group()) for s in members for m in [re.search(r"\d+", s.name)] if m}
        bare = [s for s in members if not re.search(r"\d", s.name)]
        missing = sorted(set(range(1, len(have) + len(bare) + 1)) - have)
        if have and bare and len(missing) == len(bare):
            for s, n in zip(bare, missing):
                s.name += f" {n}"


def tidy_percussion(sections: list[Section]) -> None:
    """Percussion parts come in pairs ('I & II', 'III & IV'); OCR drops the '&' and misreads."""
    for s in sections:
        m = re.fullmatch(r"(.*?Percussion) (\d)(?: \d)?", s.name)
        if m and int(m.group(2)) % 2 == 1:
            s.name = f"{m.group(1)} {m.group(2)} & {int(m.group(2)) + 1}"


def dedupe_names(sections: list[Section]) -> None:
    seen = Counter(s.name for s in sections)
    n = Counter()
    for s in sections:
        if seen[s.name] > 1:
            n[s.name] += 1
            s.name = f"{s.name} ({n[s.name]})"
