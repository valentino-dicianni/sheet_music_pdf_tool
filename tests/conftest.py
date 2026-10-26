import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")      # the GUI tests need no display

import pytest
from PIL import Image


@pytest.fixture
def make_pdf(tmp_path):
    """make_pdf([(w, h), ...]) -> a PDF whose page i is w x h points (page identity = its width)."""
    def make(sizes, name="in.pdf"):
        pages = [Image.new("L", size, 255) for size in sizes]
        path = tmp_path / name
        pages[0].save(path, "PDF", save_all=True, append_images=pages[1:], resolution=72.0)
        return path
    return make


@pytest.fixture
def numbered_pdf(make_pdf):
    """12 portrait pages; page i is 100 + i points wide."""
    return make_pdf([(100 + i, 140) for i in range(12)])
