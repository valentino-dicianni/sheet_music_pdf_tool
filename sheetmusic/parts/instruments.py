"""Instrument vocabulary and tolerant matching of OCR'd instrument names
('3> TRUMPET 2' -> 'Bb Trumpet 2', 'F HORN I' -> 'F Horn 1')."""

import difflib
import re
import unicodedata

INSTRUMENTS = [
    "piccolo", "flute", "oboe", "english", "bassoon", "contrabassoon", "clarinet", "saxophone",
    "soprano", "alto", "tenor", "baritone", "bariton", "bass", "basses", "horn", "horns", "sax", "saxes",
    "hoorn", "trumpet", "cornet", "flugelhorn", "trombone", "euphonium", "tuba", "bombardon",
    "percussion", "timpani", "drums", "drum", "mallet", "mallets", "glockenspiel", "xylophone",
    "marimba", "vibraphone", "bells", "chimes", "violin", "viola", "cello", "violoncello",
    "contrabass", "string", "strings", "piano", "keyboard", "guitar", "harp", "organ",
    "conductor", "score",
    # Spanish / Galician / Portuguese / Catalan
    "flauta", "flautas", "flautin", "frautin", "frauta", "frautas", "oboes", "fagot", "fagote", "fagotes", "fagots",
    "clarinete", "clarinetes", "requinto", "saxofon", "saxofone", "saxofones", "baritono", "bombardino", "trompa",
    "trompas", "trompeta", "trompetas", "trompete", "trompetes", "fliscorno", "fiscorno", "cornetin", "trombon",
    "trombones", "tubas", "bajo", "baixo", "contrabajo", "contrabaixo", "violonchelo", "violoncelo", "violines",
    "percusion", "percusao", "timbales", "timbal", "bombo", "caixa", "platillos", "xilofon", "xilofone", "arpa",
    "bateria", "tiple", "contralto", "clarinet", "trompa", "tenora", "fiscorn", "bombardi", "llauto", "flabiol",
    # Italian
    "flauto", "flauti", "ottavino", "fagotto", "clarinetto", "clarinetti", "sassofono", "tromba", "trombe", "corno",
    "corni", "tromboni", "eufonio", "basso", "bassi", "percussioni", "timpani", "grancassa", "rullante", "piatti",
    "contrabbasso", "flicorno", "cornetta", "xilofono", "campane", "tamburo", "arpa", "pianoforte",
    # French
    "flute", "hautbois", "basson", "clarinette", "trompette", "harpe", "contrebasse", "bugle", "cor", "timbale",
    # German
    "floete", "floete", "fagott", "klarinette", "posaune", "posaunen", "schlagzeug", "pauke", "pauken", "harfe",
    "kontrabass", "waldhorn", "tenorhorn", "baritonhorn",
    # Dutch
    "fluit", "hobo", "klarinet", "saxofoon", "trompet", "hoorn", "hoorns", "bas", "slagwerk", "harp", "althoorn",
    "bugel", "eufonium", "tuben",
]
SCORE_WORDS = {"conductor", "score", "partitur", "partitura", "partition", "direttore", "dirigent", "particella"}
# staff labels as printed in the margin of a score ("Fl.", "Bsn.", ...), besides the full names above
MARGIN_ABBREVS = {
    "fl", "flt", "picc", "ob", "bsn", "bn", "cl", "clar", "sx", "sax", "tpt", "trp", "tr", "hn", "hrn", "tbn",
    "trb", "bar", "euph", "tba", "perc", "timp", "mlt", "mall", "vln", "vla", "vc", "cb", "bs", "db", "eh", "cor",
    "hp", "pno", "bd", "sd", "cym",
}
TRANSPOSITIONS = ("Bb", "Eb", "F", "C", "D", "G", "A")
ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "l": "1"}
# OCR reads "II" as U/H/If/[I..., so a token made only of these is a numeral: count vertical strokes
STROKE_CHARS = {"I": 1, "l": 1, "1": 1, "|": 1, "!": 1, "J": 1, "f": 1, "T": 1, "[": 1, "]": 1, "U": 2, "H": 2}


def word(w: str) -> str:
    """Lower-case letters only, accents dropped ('Frautín' -> 'frautin')."""
    w = unicodedata.normalize("NFKD", w).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", w.lower())


def canonical(text: str) -> str | None:
    """Map an OCR word to a known instrument word, tolerating clipped/misread letters
    ('ASSOON' -> 'bassoon', '3ARITONE' -> 'baritone')."""
    w = word(text)
    if len(w) < 3:
        return None
    if w in INSTRUMENTS:
        return w
    for cut in (1, 2):                              # a plural of a known name ('Tenores', 'Altos'): keep it as printed
        if len(w) - cut >= 4 and w[:-cut] in INSTRUMENTS and w.endswith(("s", "es")[cut - 1]):
            return w
    if len(w) < 4:
        return {"boe": "oboe", "hom": "horn"}.get(w)    # clipped / 'rn' read as 'm'
    if len(w) < 6:                                  # one wrong letter in 5 already scores 0.8 ('pinoc' ~ 'piano')
        return None
    for m in difflib.get_close_matches(w, INSTRUMENTS, n=3, cutoff=0.8):
        if abs(len(m) - len(w)) <= 1:               # OCR drops or garbles a letter, not two ('latin' != 'flautin')
            return m
    return None


def has_instrument(text: str) -> bool:
    return any(canonical(w) for w in text.split())


def is_staff_label(token: str) -> bool:
    """An instrument name or abbreviation, as printed beside the staves of a score."""
    w = word(token)
    return w in MARGIN_ABBREVS or (len(w) >= 4 and canonical(token) is not None)


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
        elif re.fullmatch(r"[1-4][-–][1-4]", low):      # "Horns 1-3": one part for several players
            out.append(low.replace("–", "-"))
        elif low in ("e", "y", "i", "et", "und", "en", "&", "and") and out and out[-1].isdigit() \
                and i + 1 < len(tokens) and re.fullmatch(r"[1-4]", tokens[i + 1].strip(".:;")):
            out.append("&")                              # "Trompas 1 e 2"
        elif low in ("e", "y", "i") and out and not out[-1].isdigit() and i + 1 < len(tokens) \
                and tokens[i + 1].strip(".:;") == "2":
            out += ["1", "&"]                            # the "1" of "Trompas 1 e 2" read as a letter: "Trompas e 2"
        elif low in ROMAN and out:
            out.append(ROMAN[low])
        elif out and tok not in TRANSPOSITIONS and numeral(tok):
            out.append(numeral(tok))
        elif not out and len(tok) <= 3:         # transposition printed before the name
            first = tok[0]
            if first in "B3b8":
                out.append("Bb")
            elif first in "EeF" and tok[1:2] in ("b", ">", "}", "+", "B", "♭") and len(tok) == 2:   # 'Fb' is a misread 'Eb'
                out.append("Eb")
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
    elif keys:                                      # already has its key first: a later "A" is noise
        out = out[:1] + [t for t in out[1:] if t not in TRANSPOSITIONS]
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
