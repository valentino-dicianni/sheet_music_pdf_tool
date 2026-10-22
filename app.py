#!/usr/bin/env python3
"""Phone-friendly web front end for split_contrast.py: upload a PDF, get the converted PDF back.

Env: PORT (default 8000).
Run: python app.py   (or gunicorn app:app)
"""

import os
import re
import tempfile
from html import escape
from pathlib import Path
from types import SimpleNamespace

from flask import Flask, request, send_file
from werkzeug.utils import secure_filename

import split_contrast
import split_parts

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Sheet music PDF</title>
<style>body{{font-family:sans-serif;max-width:30em;margin:1em auto;padding:0 1em}}
input,button{{width:100%;font-size:1.1em;margin:.4em 0;padding:.6em;box-sizing:border-box}}
.err{{color:#c00}}</style></head><body><h2>A3 &rarr; A4 + contrast</h2>{msg}
<form method="post" enctype="multipart/form-data">
<input type="file" name="pdf" accept="application/pdf,.pdf" required>
<label><input type="checkbox" name="split_only" style="width:auto"> Lossless A3 &rarr; A4 split only (no contrast/rename)</label>
<label><input type="checkbox" name="rename" checked style="width:auto"> Rename from header (OCR)</label>
<button type="submit">Convert</button></form></body></html>"""


def _page(msg=""):
    return PAGE.format(msg=f'<p class="err">{escape(msg)}</p>' if msg else "")


@app.get("/")
def index():
    return _page()


@app.post("/")
def convert():
    f = request.files.get("pdf")
    if not f or not f.filename:
        return _page("No file selected."), 400

    name = secure_filename(f.filename) or "input.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    args = SimpleNamespace(header=0.20, dpi=300, black=110, white=215, gamma=0.7,
                           no_split=False, no_contrast=False)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / name
        f.save(src)
        try:
            if "split_only" in request.form:
                dst = Path(tmp) / "out" / (src.stem + "_A4.pdf")
                dst.parent.mkdir(parents=True, exist_ok=True)
                split_parts.split_landscape(src, dst)
            else:
              dst, _, _ = split_contrast.process_pdf(
                  src, Path(tmp) / "out" / (src.stem + "_A4.pdf"),
                  "rename" in request.form, args, set())
        except Exception:
            return _page("Could not process this PDF."), 400
        data = dst.read_bytes()
    out_name = re.sub(r"[^\w .'()-]", "_", dst.name)
    import io
    return send_file(io.BytesIO(data), mimetype="application/pdf",
                     as_attachment=True, download_name=out_name)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
