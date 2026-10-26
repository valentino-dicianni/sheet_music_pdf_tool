"""Page images: rendering, contrast, halving."""

import numpy as np
from PIL import Image

OCR_LEVELS = (110, 215, 0.7)        # (black, white, gamma) applied to pages before OCR


def render_gray(page, dpi: int) -> Image.Image:
    """A pdfium page as an 8-bit grayscale image."""
    return page.render(scale=dpi / 72.0, grayscale=True).to_pil().convert("L")


def adjust_contrast(img: Image.Image, black: int, white: int, gamma: float) -> Image.Image:
    """Levels stretch (black..white -> 0..255) followed by a gamma curve.

    gamma < 1 darkens midtones, which makes thin staff lines and note stems bolder.
    """
    a = np.asarray(img.convert("L"), dtype=np.float32)
    a = np.clip((a - black) / float(white - black), 0.0, 1.0)
    a = a ** (1.0 / gamma)
    return Image.fromarray((a * 255.0 + 0.5).astype(np.uint8), mode="L")


def needs_split(img: Image.Image) -> bool:
    """Only landscape pages (e.g. A3 landscape = two A4 side by side) are split.
    Portrait pages such as A4 are already single pages and are kept whole."""
    return img.width > img.height


def split_halves(img: Image.Image) -> list[Image.Image]:
    w, h = img.size
    mid = w // 2
    return [img.crop((0, 0, mid, h)), img.crop((mid, 0, w, h))]
