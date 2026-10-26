#!/usr/bin/env bash
# Start the desktop app. Uses ./venv (created, and filled with the GUI dependencies, on first run).
#   ./run_gui.sh
set -euo pipefail
cd "$(dirname "$0")"

[ -x venv/bin/python ] || python3 -m venv venv
if ! venv/bin/python -c "import PySide6, pypdfium2, pytesseract, numpy, PIL" 2>/dev/null; then
  echo "installing dependencies into ./venv ..."
  venv/bin/pip install -e ".[gui]"
fi
command -v tesseract >/dev/null || echo "warning: tesseract is not installed (apt install tesseract-ocr): analysis needs it" >&2

exec venv/bin/python -m sheetmusic gui "$@"
