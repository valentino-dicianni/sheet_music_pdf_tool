"""Tesseract access, and grouping of its words into text segments. Shared by every tool."""

import statistics

from PIL import Image

OCR_DPI = 300                # resolution pages are rendered at for OCR


class OcrUnavailable(RuntimeError):
    """pytesseract or the tesseract binary is missing."""


def ocr_data(img: Image.Image, psm: int) -> dict:
    try:
        import pytesseract
        from pytesseract import Output
    except ImportError as exc:
        raise OcrUnavailable("pytesseract is not installed") from exc
    try:
        return pytesseract.image_to_data(img, config=f"--psm {psm}", output_type=Output.DICT)
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrUnavailable("tesseract binary not found") from exc


def ocr_words(strip: Image.Image) -> list[dict]:
    d = ocr_data(strip, psm=11)             # sparse text: finds every block in the header
    words = []
    for i, text in enumerate(d["text"]):
        text = text.strip()
        if not text or float(d["conf"][i]) < 60 or not any(c.isalnum() for c in text):
            continue
        words.append({"text": text, "left": d["left"][i], "top": d["top"][i],
                      "width": d["width"][i], "height": d["height"][i]})
    return words


def refine_segment(strip: Image.Image, seg: dict) -> str:
    """Re-read one detected line as an isolated single-line crop (psm 7). This is
    noticeably more accurate than the whole-header pass (e.g. fixes 'ARIK' -> 'ARK')."""
    pad = max(20, int(seg["height"] * 0.3))
    box = (max(seg["left"] - pad, 0), max(seg["top"] - pad, 0),
           min(seg["right"] + pad, strip.width), min(seg["bottom"] + pad, strip.height))
    d = ocr_data(strip.crop(box), psm=7)
    good = [(d["text"][i].strip(), float(d["conf"][i])) for i in range(len(d["text"]))
            if d["text"][i].strip() and float(d["conf"][i]) >= 40]
    if good and statistics.mean(c for _, c in good) >= 60:
        return " ".join(t for t, _ in good)
    return seg["text"]


def text_segments(words: list[dict]) -> list[dict]:
    """Group words into rows, then split rows into text segments at large gaps."""
    rows: list[dict] = []
    for w in sorted(words, key=lambda w: w["top"] + w["height"] / 2):
        cy = w["top"] + w["height"] / 2
        if rows and abs(cy - rows[-1]["cy"]) <= 0.6 * max(w["height"], rows[-1]["h"]):
            r = rows[-1]
            r["words"].append(w)
            r["cy"] = statistics.mean(x["top"] + x["height"] / 2 for x in r["words"])
            r["h"] = max(r["h"], w["height"])
        else:
            rows.append({"words": [w], "cy": cy, "h": w["height"]})

    segments = []
    for r in rows:
        ws = sorted(r["words"], key=lambda w: w["left"])
        gap_limit = 2.5 * statistics.median(w["height"] for w in ws)
        cur = [ws[0]]
        for prev, w in zip(ws, ws[1:]):
            if w["left"] - (prev["left"] + prev["width"]) > gap_limit:
                segments.append(cur)
                cur = []
            cur.append(w)
        segments.append(cur)

    return [{"text": " ".join(w["text"] for w in s),
             "height": statistics.median(w["height"] for w in s),
             "top": min(w["top"] for w in s),
             "bottom": max(w["top"] + w["height"] for w in s),
             "left": s[0]["left"],
             "right": max(w["left"] + w["width"] for w in s),
             "words": [w["text"] for w in s]} for s in segments]
