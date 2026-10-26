# Sheet music PDF tools

Tools for scanned band / orchestra sets:

* **Split into parts** – one PDF per instrument (and the score) from a single big PDF, found with OCR.
* **A3 → A4** – halve landscape (A3) pages, darken faint scans, name the file `Title - Instrument.pdf`.

…available as a **desktop app** (PySide6), a **Telegram bot**, and a **command line**.

## Setup
```bash
sudo apt install tesseract-ocr          # OCR (macOS: brew install tesseract)
pip install -e ".[gui,bot]"             # or just ".[gui]" / ".[bot]"; add ",dev" for the tests
```

## Desktop app
`./run_gui.sh` (creates `./venv` and installs what is missing), or `python -m sheetmusic gui`.

*Score & Parts* → pick a PDF → Analyze. The **Map** view shows the whole document as a colored strip (one cell per page,
one color per part) above one card per part with its page thumbnails; a page of the wrong color between two others is a
page in the wrong part.

* drag pages (Ctrl/Shift-click for several) onto another part – the destination lights up and a marker shows where they
  land; drop on a part's header to append, on "Drop pages here" to start a new part; hover a collapsed part to open it
* right-click a page for "Move to…"; edit a part's name in its header; **Ctrl+Z** undoes any edit
* the preview on the right shows the selected part's pages in output order
* **List** is the table view (edit names and page ranges such as `33-36, 40`; merge / split / delete)

## Telegram bot
Send the bot a PDF and pick: split into instruments (ZIP), A3 → A4 only, or A3 → A4 + better contrast
(20 MB in, 50 MB out – Telegram's limits for bots).

1. Create a bot with [@BotFather](https://t.me/BotFather) and `cp .env.example .env`, then fill in `TELEGRAM_BOT_TOKEN`
   (optionally `ALLOWED_USERS`, comma separated Telegram ids – find yours with @userinfobot).
2. `python -m sheetmusic bot`, or in Docker: `./run_bot.sh` (build + start; `./run_bot.sh logs` / `stop`).

The bot is a long-running worker (long polling, no public URL): run it on any always-on machine or a worker service.

## Command line
```bash
python -m sheetmusic parts set.pdf --dry-run     # show the detected parts
python -m sheetmusic parts set.pdf               # -> set_parts/<Title> - <Instrument>.pdf
python -m sheetmusic a3 scans/ -r                # whole folder, A3 -> A4 + contrast + rename
python -m sheetmusic <command> --help
```

## Layout
```
sheetmusic/
  ocr.py  imaging.py  names.py     shared building blocks (Tesseract, contrast / halving, file names)
  a3.py                            the A3 -> A4 pipeline            (A3Options, plan_jobs, process_pdf)
  parts/                           the "split into parts" engine – no GUI, no Telegram
    instruments.py                   vocabulary + tolerant matching of OCR'd names ("Flute If" -> "Flute 2")
    model.py                         PageInfo, Section (a part = a list of pages), coverage
    titles.py                        piece title, watermarks, title pages
    analysis.py                      OCR every page -> PageInfo;  analyze(pdf) -> (title, sections)
    sectioning.py                    PageInfo list -> named sections
    editing.py                       manual changes as pure functions (move_pages, merge, split, ...)
    pdfio.py                         halve landscape pages, write one PDF per section
  bot/   jobs.py (blocking runners)  app.py (Telegram handlers)
  gui/   theme · jobs · preview · thumbs · groupmap (map, drag & drop) · parts_tab · a3_tab · main_window
  cli.py  __main__.py              python -m sheetmusic gui | bot | parts | a3
tests/                             pytest, synthetic PDFs only (no OCR / display needed)
```
The dependency rule: `parts`, `a3` and the helpers know nothing about the GUI or the bot; the GUI and the bot only
call into them. To change how parts are *found*, look in `parts/analysis.py` / `sectioning.py`; to change how they are
*corrected by hand*, `parts/editing.py` (+ `gui/groupmap.py` for the widgets).

## Tests
`pytest` (needs `pip install -e ".[dev,gui]"`; the GUI tests run offscreen and skip themselves without PySide6).
