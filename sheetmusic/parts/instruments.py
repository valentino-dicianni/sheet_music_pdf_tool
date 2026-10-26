"""Instrument vocabulary and tolerant matching of OCR'd instrument names
('3> TRUMPET 2' -> 'Bb Trumpet 2', 'F HORN I' -> 'F Horn 1')."""

import difflib
import re

INSTRUMENTS = [
    "piccolo", "flute", "oboe", "english", "bassoon", "contrabassoon", "clarinet", "saxophone",
    "soprano", "alto", "tenor", "baritone", "bariton", "bass", "basses", "horn", "horns",
    "hoorn", "trumpet", "cornet", "flugelhorn", "trombone", "euphonium", "tuba", "bombardon",
    "percussion", "timpani", "drums", "drum", "mallet", "mallets", "glockenspiel", "xylophone",
    "marimba", "vibraphone", "bells", "chimes", "violin", "viola", "cello", "violoncello",
    "contrabass", "string", "strings", "piano", "keyboard", "guitar", "harp", "organ",
    "conductor", "score",
]
SCORE_WORDS = {"conductor", "score", "partitur", "partitura", "direttore"}
TRANSPOSITIONS = ("Bb", "Eb", "F", "C", "D", "G", "A")
ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "l": "1"}
# OCR reads "II" as U/H/If/[I..., so a token made only of these is a numeral: count vertical strokes
STROKE_CHARS = {"I": 1, "l": 1, "1": 1, "|": 1, "!": 1, "J": 1, "f": 1, "T": 1, "[": 1, "]": 1, "U": 2, "H": 2}


def word(w: str) -> str:
    """Lower-case letters only."""
    return re.sub(r"[^a-z]", "", w.lower())


def canonical(text: str) -> str | None:
    """Map an OCR word to a known instrument word, tolerating clipped/misread letters
    ('ASSOON' -> 'bassoon', '3ARITONE' -> 'baritone')."""
    w = word(text)
    if len(w) < 3:
        return None
    if w in INSTRUMENTS:
        return w
    if len(w) < 4:
        return {"boe": "oboe", "hom": "horn"}.get(w)    # clipped / 'rn' read as 'm'
    match = difflib.get_close_matches(w, INSTRUMENTS, n=1, cutoff=0.8)
    return match[0] if match else None


def has_instrument(text: str) -> bool:
    return any(canonical(w) for w in text.split())


def numeral(tok: str) -> str | None:
    """'II' -> '2', also for OCR garble like 'U', 'H', '[I', 'If' (2) or 'Ul', 'HI', 'ITI' (3)."""
    tok = tok.strip(".:;,")
    if not 1 <= len(tok) <= 4 or any(c not in STROKE_CHARS for c in tok) or tok in ("T", "f"):
        return None
    n = sum(STROKE_CHARS[c] for c in tok)
    return str(n) if 1 <= n <= 4 else None


def normalize_instrument(text: str) -> str:
    """'3> TRUMPET 2' -> 'Bb Trumpet 2', 'F HORN I' -> 'F Horn 1', 'ASSOON' -> 'Bassoon'."""
    tokens = text.replace(",", " ").split()
    out: list[str] = []
    for i, tok in enumerate(tokens):
        canon = canonical(tok)
        low = tok.lower().strip(".:;")
        if canon:
            out.append(canon.capitalize())
        elif re.fullmatch(r"[1-4]", low):               # other digits are clef glyphs read as '6', '8'
            out.append(low)
        elif low in ROMAN and out:
            out.append(ROMAN[low])
        elif out and tok not in TRANSPOSITIONS and numeral(tok):
            out.append(numeral(tok))
        elif i == 0 and len(tok) <= 3:          # transposition printed before the name
            first = tok[0]
            if first in "B3b8":
                out.append("Bb")
            elif first in "Ee":
                out.append("Eb")
            elif tok in ("F", "C", "D", "G", "A"):
                out.append(tok)
        elif re.fullmatch(r"[A-Ga-g][b#>]?", tok):  # "Hoorn 1 Eb", "Trombone Bb 1"
            out.append(tok[0].upper() + ("b" if len(tok) > 1 else ""))
        elif re.fullmatch(r"[A-Z]\.([A-Z]\.?)?,?", tok):   # "T.C.", "B.C"
            out.append(tok.rstrip(",") + ("" if tok.rstrip(",").endswith(".") else "."))
        elif re.fullmatch(r"[BT]C", tok):                 # "Bariton BC" (bass / treble clef)
            out.append(f"{tok[0]}.C.")
    # transposition goes first: "Hoorn 1 Eb" / "Trombone Bb 1" -> "Eb Hoorn 1" / "Bb Trombone 1"
    keys = [t for t in out[1:] if t in TRANSPOSITIONS]
    if keys and out[0] not in TRANSPOSITIONS:
        out = [keys[0]] + [t for t in out if t != keys[0]]
    return " ".join(out)


def instrument_key(name: str) -> str:
    """Comparable key without transposition: 'Bb Clarinet 2' and 'Clarinet 2' match."""
    return " ".join(t.lower() for t in name.split() if t not in TRANSPOSITIONS)


def same_instrument(a: str, b: str) -> bool:
    ka, kb = instrument_key(a), instrument_key(b)
    da, db = re.findall(r"\d+", ka), re.findall(r"\d+", kb)
    if da and db and da != db:
        return False
    ka, kb = re.sub(r"\s*\d+", "", ka), re.sub(r"\s*\d+", "", kb)
    return difflib.SequenceMatcher(None, ka, kb).ratio() >= 0.85
