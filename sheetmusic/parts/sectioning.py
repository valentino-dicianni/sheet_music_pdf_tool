"""Pages (with their OCR findings) -> named sections."""

import difflib
import re
from collections import Counter

from .instruments import TRANSPOSITIONS, instrument_key, normalize_instrument, same_instrument
from .model import PageInfo, Section
from .titles import has_title_in_header, is_title_page

MIN_TITLE_PAGES = 3           # title pages needed before they are trusted as the only part boundaries
EVEN_SHARE = 0.6              # parts count as evenly spaced when this share of the gaps between them is equal
BOOKLET_SHARE = 0.5           # share of the parts whose last page comes before their title page (A3 booklet order)


def _family(name: str) -> str:
    """'Bb Clarinet 2' -> 'clarinet': a part's instrument without key and number, to tell parts from each other."""
    return re.sub(r"\s*[\d&-]+", "", instrument_key(name)).strip()


def _same_family(a: str, b: str) -> bool:
    """Tolerant of a garbled key letter ('Fb Alto' is 'Eb Alto'): is it the instrument of the previous page?"""
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= 0.7


def part_starts(pages: list[PageInfo], title: str) -> tuple[set[int], set[int]]:
    """(pages that open a part, those of them that were only inferred from an even spacing).

    A part opens with its piece title and/or the instrument name printed at the top left. The title is
    often unreadable and the instrument is sometimes missing, so when the parts that were found are evenly
    spaced (all 4 pages long, say), a page at the expected spot that has some heading text opens one too."""
    plain = [p for p in pages if not p.is_score]
    # '(Flute)' / '(Doubling Oboe II' at the left is a note: it can name a part, but it does not open one
    labelled = {p.index for p in plain if p.title_instrument and not p.title_instrument.startswith("(")}
    by_instrument = len(labelled) >= MIN_TITLE_PAGES
    starts = {p.index for p in plain if is_title_page(p, title) or (by_instrument and p.index in labelled)}
    last = ""                                       # the instrument the previous page was for (ignoring numbers)
    for p in plain:
        text = p.title_instrument or p.header_instrument
        now = _family(normalize_instrument(text)) if text else ""
        if p.index not in starts and has_title_in_header(p, title) and now and not (last and _same_family(now, last)):
            starts.add(p.index)                     # title in the header and a new instrument: a part starts here
        last = now or last
    if len(starts) < MIN_TITLE_PAGES:
        return starts, set()
    marks = sorted(starts) + [len(pages)]
    gaps = [b - a for a, b in zip(marks, marks[1:])]
    size, n = Counter(gaps).most_common(1)[0]
    if size < 2 or n < EVEN_SHARE * len(gaps):
        return starts, set()
    inferred = set()
    for a, b in zip(marks, marks[1:]):
        if b - a > size and (b - a) % size == 0:
            for j in range(a + size, b, size):
                q = pages[j]
                if not q.is_score and (q.title_text or q.title_instrument):   # a running header proves nothing
                    inferred.add(j)
    return starts | inferred, inferred


def _same_part_name(a: str, b: str) -> bool:
    """Do two instrument texts name the same part? Same instrument (key and wording ignored: 'Bb Clarinet'
    ~ 'Clarinet', but not 'Alto Clarinet'), and the same first number if both have one."""
    if not a or not b:
        return False
    ka, kb = re.sub(r"[\d&-]+", "", instrument_key(a)).strip(), re.sub(r"[\d&-]+", "", instrument_key(b)).strip()
    if not ka or not kb or difflib.SequenceMatcher(None, ka, kb).ratio() < 0.85:
        return False
    da, db = re.findall(r"\d", a), re.findall(r"\d", b)
    return not (da and db and da[0] != db[0])


def _instrument_on(page: PageInfo, header_first: bool = False) -> str:
    text = (page.header_instrument or page.title_instrument) if header_first else (page.title_instrument or page.header_instrument)
    return normalize_instrument(text) if text else ""


def booklet_shifts(pages: list[PageInfo], starts: set[int]) -> dict[int, int]:
    """{title page: page the part really starts on} for sets scanned as folded A3 booklets.

    A booklet sheet carries pages [4 | 1] and the next [2 | 3], so halved the order is 4, 1, 2, 3: the last page of a
    part sits right *before* its title page, with a running header for the same instrument as the pages after it. When
    that holds for most parts, the page before each title page belongs to the part, not to the one before it."""
    strong, weak = {}, {}
    for s in sorted(starts):
        if s < 1 or (s - 1) in starts or pages[s - 1].is_score or s + 2 >= len(pages):
            continue
        before = _instrument_on(pages[s - 1], header_first=True)
        this = next((n for n in (_instrument_on(pages[s]), _instrument_on(pages[s + 1], True), _instrument_on(pages[s + 2], True)) if n), "")
        earlier = _instrument_on(pages[s - 2], header_first=True) if s >= 2 and not pages[s - 2].is_score else ""
        if _same_part_name(this, before) and not _same_part_name(before, earlier):
            strong[s] = s - 1                       # its running header is this part's, not the previous part's
        elif this and not before:
            weak[s] = s - 1                         # nothing readable there (a stamp, a clipped header)
    if len(strong) < MIN_TITLE_PAGES or len(strong) < BOOKLET_SHARE * len(starts):
        return {}
    return {**weak, **strong}                       # the set is in booklet order: unreadable pages most likely are too


def build_sections(pages: list[PageInfo], title: str) -> list[Section]:
    sections: list[Section] = []
    starts, inferred = part_starts(pages, title)
    shifts = booklet_shifts(pages, starts - inferred)
    if shifts:
        starts = {shifts.get(s, s) for s in starts}
        inferred = {shifts.get(s, s) for s in inferred}
    shifted = set(shifts.values())
    # Headers are read with OCR noise ('Flute If', 'Clarinet U'), so a changed header only starts a
    # part in sets where parts cannot be told apart by their first page.
    has_title_pages = len(starts - inferred) >= MIN_TITLE_PAGES

    def start(i: int, is_score: bool, cand: str = "") -> None:
        sections.append(Section(i, i, "Score" if is_score else "", is_score, [cand] if cand else [],
                                inferred=i in inferred, titled=i in starts and i not in inferred))

    for p in pages:
        cur = sections[-1] if sections else None
        if p.is_score:
            if cur and cur.is_score:
                cur.end = p.index
            else:
                start(p.index, True)
            continue

        header = normalize_instrument(p.header_instrument) if p.header_instrument else ""
        if p.index in starts or cur is None or cur.is_score:
            start(p.index, False, normalize_instrument(p.title_instrument) if p.title_instrument else "")
        elif not has_title_pages and header and cur.headers and not any(same_instrument(header, h) for h in cur.headers):
            start(p.index, False)               # instrument changed without a title page
        else:
            cur.end = p.index
            if p.title_instrument:                  # a title page that is not the first page of its part (booklet order)
                cur.candidates.append(normalize_instrument(p.title_instrument))
        if header:
            sections[-1].headers.append(header)
            sections[-1].candidates += [header, header]   # centered headers are more reliable

    first_score = next((i for i, s in enumerate(sections) if s.is_score), None)
    if first_score:                                 # cover / foreword pages before the score belong to it
        front = sections[:first_score]
        if not any(s.headers or s.candidates for s in front):
            sections[first_score].start = front[0].start
            del sections[:first_score]
    for s in sections:
        if not s.is_score:
            s.name = choose_name(s.candidates) or f"Part {s.pages}"
    for prev, s in zip(sections, sections[1:]):
        if s.inferred and s.name.startswith("Part ") and not prev.is_score:
            s.name = prev.name              # same instrument again (a second Mallets part ...): numbered below
    merge_leftovers(sections)
    if shifted:
        snap_to_sheets(sections)
    for s in sections:                              # booklet order 4,1,2,3 -> reading order 1,2,3,4 (per 4-page sheet pair)
        pages_ = s.page_list()
        if not s.is_score and pages_[0] in shifted and len(pages_) % 4 == 0:
            s.set_pages([p for b in range(0, len(pages_), 4) for p in (*pages_[b + 1:b + 4], pages_[b])])
    number_siblings(sections)
    tidy_percussion(sections)
    dedupe_names(sections)
    return sections


def merge_leftovers(sections: list[Section]) -> None:
    """A section that no title page opened, right before a part of the same instrument, is a piece of that part
    (a page that came first in the scan): 'Flute 1' (1 page) + 'Flute 1' (4 pages with title) = one part."""
    i = 0
    while i + 1 < len(sections):
        a, b = sections[i], sections[i + 1]
        if (not a.is_score and not b.is_score and not a.titled and b.titled and not a.name.startswith("Part ")
                and same_instrument(a.name, b.name)):
            b.set_pages(a.page_list() + b.page_list())
            b.candidates += a.candidates
            del sections[i]
        else:
            i += 1


def snap_to_sheets(sections: list[Section]) -> None:
    """In a set of folded booklets every part is a whole number of 4-page sheets. Two neighbouring parts that are
    both off ('F Horn' 5 + 3 pages) but add up to whole sheets share a boundary that is a page or two out: move it."""
    for a, b in zip(sections, sections[1:]):
        if a.is_score or b.is_score or a.order is not None or b.order is not None or a.end + 1 != b.start:
            continue
        la, lb = a.end - a.start + 1, b.end - b.start + 1
        if la % 4 and lb % 4 and (la + lb) % 4 == 0:
            want = max(4, round(la / 4) * 4)
            d = want - la
            if d and abs(d) <= 2 and lb - d >= 4:
                a.end += d
                b.start += d


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
    if the missing numbers are unambiguous, give them to the unnumbered ones (in page order). A family
    with several parts and no number at all ('Bb Clarinet' x3) is numbered 1, 2, 3."""
    families: dict[str, list[Section]] = {}
    for s in sections:
        if not s.is_score and instrument_key(s.name) and not s.name.startswith("Part "):  # keep Eb / Bb apart
            families.setdefault(re.sub(r"\s*\d+(-\d+)?", "", s.name).lower(), []).append(s)
    for members in families.values():
        have = {int(m.group()) for s in members for m in [re.search(r"\d+", s.name)] if m}
        bare = [s for s in members if not re.search(r"\d", s.name)]
        missing = sorted(set(range(1, len(have) + len(bare) + 1)) - have)
        if have and bare and len(missing) == len(bare):
            for s, n in zip(bare, missing):
                s.name += f" {n}"
        elif not have and len(bare) > 1:
            for n, s in enumerate(bare, 1):
                s.name += f" {n}"


def tidy_percussion(sections: list[Section]) -> None:
    """Percussion parts often come in pairs ('I & II', 'III & IV'); OCR drops the '&' and misreads. A
    part is a pair when its title page showed two numerals ('Percussion 1 1'): the page headers only
    show the first. A set with 'Percussion 1', '2', '3' parts has no such title page, so stays as it is."""
    for s in sections:
        m = re.fullmatch(r"(.*?Percussion) (\d)", s.name)
        if m and int(m.group(2)) % 2 == 1 and any(re.fullmatch(rf"{m.group(1)} {m.group(2)} \d", c) for c in s.candidates):
            s.name = f"{m.group(1)} {m.group(2)} & {int(m.group(2)) + 1}"


def dedupe_names(sections: list[Section]) -> None:
    seen = Counter(s.name for s in sections)
    n = Counter()
    for s in sections:
        if seen[s.name] > 1:
            n[s.name] += 1
            s.name = f"{s.name} ({n[s.name]})"
