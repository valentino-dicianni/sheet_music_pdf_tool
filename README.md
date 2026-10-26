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
(see below for PDFs over 20 MB).

1. Create a bot with [@BotFather](https://t.me/BotFather) and `cp .env.example .env`, then fill in `TELEGRAM_BOT_TOKEN`
   (optionally `ALLOWED_USERS`, comma separated Telegram ids – find yours with @userinfobot).
2. `python -m sheetmusic bot`, or in Docker: `./run_bot.sh` (build + start; `./run_bot.sh logs` / `stop`).

The bot is a long-running worker (long polling, no public URL): run it on any always-on machine or a worker service.

### PDFs above 20 MB
The HTTP Bot API refuses to hand a bot more than 20 MB per file ("File is too big", it is Telegram that says so). Two ways around it:

1. **Direct, up to 2 GB (recommended):** let the bot also log in over Telegram's normal protocol (MTProto) for big downloads.
   Get an `api_id` / `api_hash` at <https://my.telegram.org> → *API development tools*, put them in `.env` as `TELEGRAM_API_ID`
   and `TELEGRAM_API_HASH`, restart the bot. The log then says `MTProto connection ready`, and any PDF up to 2000 MB just works.
2. **Without credentials:** the bot asks for a **split ZIP** instead: all pieces in one go, in any order; it puts them back
   together, then asks what to do. `/cancel` drops pieces it is still waiting for.

* 7-Zip / Keka: *Add to archive* → format **zip** → *Split to volumes* `15M` → `name.zip.001`, `name.zip.002`, …
* Terminal: `zip -s 15m name.zip big.pdf` → `name.z01`, `name.z02`, …, `name.zip`
* A PDF cut into pieces named `big.pdf.001`, `big.pdf.002`, … also works.
* A normal `.zip` with one PDF inside works too.

Results come back the same way in reverse: a ZIP of the parts, or, above 50 MB, several ZIPs (`Title (1 of 3).zip` …); a single
file that is itself over 50 MB arrives as `.zip.001`, `.zip.002`, … volumes that 7-Zip / `unzip` join again.

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

## How parts are found (and what to do when it goes wrong)
Every page is OCR'd (header band + left margin), then `parts/` decides:

* **score page** – at least 5 *instrument names / abbreviations* in the left margin (`Fl.`, `Clarinet` …; ordinary
  text there is notation noise, so only instrument words count), plus a few-page gap between two score pages.
* **a part starts** on a page that shows the piece title and/or an instrument name at the top left. When the parts found
  are evenly spaced (e.g. all 4 pages) and a page at the expected spot has some heading, that is a part too (`*inferred*`).
* **a title page can carry its label badly** (a library stamp over it): the top-left corner is then read again, close up.
  A note lower on the page (`Bombo`, `(Flute)`) never names or opens a part.
* **folded A3 booklets** are recognised: after halving, a booklet's pages come as 4, 1, 2, 3, so the last page of each part
  sits *before* its title page. When most parts show that, each part starts one page earlier, and its pages are put in
  reading order 1, 2, 3, 4 (shown as e.g. `52-54, 51`). Parts are then whole 4-page sheets, which also repairs a boundary
  that is a page out.
* **names** are read from the title page and the centered headers, voted, then cleaned: `Flute If` → `Flute 2`,
  numbers inferred for `Clarinet ×3`, `Horns 1-3` kept. Instrument words are known in English, Spanish / Galician /
  Portuguese / Catalan, Italian, French, German and Dutch (`parts/instruments.py`).

When a set comes out wrong: run `python -m sheetmusic parts set.pdf --dry-run`, look at the page numbers that are off, and
fix them in the GUI map (drag pages, rename). To teach it something general, add a test in `tests/test_sectioning.py`
using `PageInfo` objects (no PDF needed) and change `parts/sectioning.py` / `parts/instruments.py`.

## Tests
`pytest` (needs `pip install -e ".[dev,gui]"`; the GUI tests run offscreen and skip themselves without PySide6).
