"""The title of the piece and which pages are title pages (the first page of a part)."""

import re
from collections import Counter

from .instruments import word
from .model import PageInfo

TITLE_WORD_SHARE = 0.5        # a title word must head at least this share of the most common word's pages
RUNNING_WORD_MIN = 5          # a big heading word on at least this many pages ...
RUNNING_WORD_ADJACENT = 0.25  # ... of which this share have it on the next page too is a watermark


def title_words(text: str) -> set[str]:
    return {w for w in (word(t) for t in text.split()) if len(w) >= 3}


def strip_running_words(pages: list[PageInfo]) -> None:
    """Remove words that are big on page after page (a watermark such as 'ARCHIVOCUCOSAX', a running
    header) from every page's heading text: they are neither the title nor a title-page marker. The
    real title only heads the first page of each part, so it rarely shows up on neighbouring pages."""
    where: dict[str, set[int]] = {}
    for p in pages:
        for t in p.title_text.split():
            if len(word(t)) >= 3:
                where.setdefault(word(t), set()).add(p.index)
    running = {w for w, idx in where.items()
               if len(idx) >= RUNNING_WORD_MIN and sum(i + 1 in idx for i in idx) >= RUNNING_WORD_ADJACENT * len(idx)}
    for p in pages:
        p.title_text = " ".join(t for t in p.title_text.split() if word(t) not in running)


def detect_title(pages: list[PageInfo]) -> str:
    """The most frequent large heading. Title pages that OCR split in two ('Highlights
    From' / 'From EVITA') are matched by word overlap."""
    texts = [p.title_text for p in pages if p.title_text and not p.is_score]
    if not texts:
        texts = [p.title_text for p in pages if p.title_text]
    if not texts:
        return ""
    counts = Counter(re.sub(r"\s+", " ", t).strip() for t in texts)
    best = max(counts, key=lambda t: (sum(len(title_words(t) & title_words(o)) > 0 for o in texts),
                                      counts[t], len(t)))
    # the publisher's name often sits next to the title ("UNIO. NOAH'S ARK"): keep the words that
    # head many pages, drop the ones that only a few pages have
    df = Counter(w for p in pages for w in title_words(p.title_text))
    common = {w for w, n in df.items() if n >= TITLE_WORD_SHARE * max(df.values(), default=0)}
    tokens = [t for t in best.split() if not title_words(t) or title_words(t) <= common]
    real = [i for i, t in enumerate(tokens) if title_words(t)]          # tokens that are words, not "It" / "of" noise
    return " ".join(tokens[real[0]:real[-1] + 1]) if real else best


TITLE_SHARE = 0.3             # of the words in a heading, this share must belong to the title
HEADER_TITLE_SHARE = 0.2      # ... in a header line that also holds an instrument and maybe a credit line


def _shows_title(text: str, title: str, share: float = TITLE_SHARE) -> bool:
    """The heading is (mostly) the piece title, not a longer movement heading that merely contains its name
    ('IV. Pinocho; Historia dunha Marioneta' is not the title page of 'Pinocho Gepeto')."""
    tw, words = title_words(title), title_words(text)
    hits = len(tw & words)
    return bool(tw and words) and hits >= max(1, len(tw) // 2) and hits >= share * len(words)


def is_title_page(page: PageInfo, title: str) -> bool:
    """The piece title is printed large at the top of the page."""
    return _shows_title(page.title_text, title)


def has_title_in_header(page: PageInfo, title: str) -> bool:
    """The title is part of the centered header line instead ('Flute I ... Orient Express'). That is either the
    OCR having merged a title page's title and instrument into one line, or a running header ('PIRATES OF THE
    CARIBBEAN Flute 1') on a continuation page: only the instrument tells them apart (see part_starts)."""
    return _shows_title(page.header_instrument, title, HEADER_TITLE_SHARE)
