"""The title of the piece and which pages are title pages (the first page of a part)."""

import re
from collections import Counter

from .instruments import word
from .model import PageInfo

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
    return best


def is_title_page(page: PageInfo, title: str) -> bool:
    tw = title_words(title)
    # the OCR sometimes merges instrument and title into one line ('Flute I ... Orient Express'),
    # which then lands in header_instrument instead of title_text
    text = f"{page.title_text} {page.header_instrument}"
    if not tw or not text.strip():
        return False
    return len(tw & title_words(text)) >= max(1, len(tw) // 2)
