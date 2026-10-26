"""File names for the PDFs we write."""

import re
import string


def clean_name(text: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if text.isupper():                       # "NOAH'S ARK" -> "Noah's Ark"
        text = string.capwords(text.lower())
    return text[:100]


def build_stem(title: str | None, instrument: str | None, fallback: str) -> str:
    title = clean_name(title) if title else ""
    instrument = clean_name(instrument) if instrument else ""
    if title and instrument:
        return f"{title} - {instrument}"
    if title:
        return f"{title} - {fallback}"
    if instrument:
        return f"{fallback} - {instrument}"
    return fallback
