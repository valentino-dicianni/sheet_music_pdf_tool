#!/usr/bin/env python3
"""Phone-friendly web front end for split_contrast.py: upload a PDF, get the converted PDF back.

Env: APP_TOKEN (required password), PORT (default 8000).
Run: python app.py   (or gunicorn app:app)
"""

import hmac
import os
import re
import tempfile
from html import escape
from pathlib import Path
from types import SimpleNamespace

from flask import Flask, request, send_file
from werkzeug.utils import secure_filename

import split_contrast

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Sheet music PDF</title>
<style>body{{font-family:sans-serif;max-width:30em;margin:1em auto;padding:0 1em}}
input,button{{width:100%;font-size:1.1em;margin:.4em 0;padding:.6em;box-sizing:border-box}}
.err{{color:#c00}}</style></head><body><h2>A3 &rarr; A4 + contrast</h2>{msg}
<form method="post" enctype="multipart/form-data">
<input type="password" name="token" placeholder="Password" required>
<input type="file" name="pdf" accept="application/pdf,.pdf" required>
<label><input type="checkbox" name="rename" checked style="width:auto"> Rename from header (OCR)</label>
<button type="submit">Convert</button></form></body></html>"""


def _page(msg=""):
    return PAGE.format(msg=f'<p class="err">{escape(msg)}</p>' if msg else "")


@app.get("/")
def index():
    return _page()


@app.post("/")
def convert():
    expected = os.environ.get("APP_TOKEN", "")
    given = request.form.get("token", "")
    if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
        return _page("Wrong password."), 403
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
