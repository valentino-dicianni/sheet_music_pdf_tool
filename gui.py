#!/usr/bin/env python3
"""GUI (Qt / PySide6) for the two tools:
  * Score & Parts : split a set into score and parts, "<Title> - <Instrument>.pdf" (split_parts.py)
  * A3 -> A4      : split landscape pages in two + contrast + rename (split_contrast.py)

Requirements: pip install PySide6   (plus the requirements of the two tools)
Run:          python gui.py
"""

import argparse
import re
import sys
from pathlib import Path

import pypdfium2 as pdfium
from PySide6.QtCore import QObject, QThreadPool, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QImage, QKeySequence, QPalette, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSplitter, QStyleFactory, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

import split_contrast
import split_parts

ACCENT = "#2f6fde"
DANGER = "#d64545"
WARN = "#c98a00"
OK = "#2e9d57"

STYLE = """
QMainWindow, QTabWidget > QWidget { background: palette(window); }
QFrame#card { background: palette(base); border: 1px solid palette(mid); border-radius: 10px; }
QLabel#h1 { font-size: 15pt; font-weight: 600; }
QLabel#muted { color: palette(placeholder-text); }
QLabel#chip { border-radius: 10px; padding: 3px 10px; font-weight: 600; }
QPushButton { padding: 6px 14px; border-radius: 6px; border: 1px solid palette(mid); background: palette(button); }
QPushButton:hover { border-color: palette(highlight); }
QPushButton:pressed { background: palette(midlight); }
QPushButton:disabled { color: palette(placeholder-text); }
QPushButton#primary { background: palette(highlight); color: palette(highlighted-text); border: none; font-weight: 600; padding: 7px 18px; }
QPushButton#primary:hover { background: %(accent_hover)s; }
QPushButton#primary:disabled { background: palette(mid); color: palette(placeholder-text); }
QPushButton#flat { border: none; background: transparent; padding: 4px 8px; }
QPushButton#flat:hover { background: palette(midlight); }
QLineEdit { padding: 6px 8px; border-radius: 6px; border: 1px solid palette(mid); background: palette(base); }
QLineEdit:focus { border-color: palette(highlight); }
QTableWidget { border: 1px solid palette(mid); border-radius: 8px; background: palette(base); gridline-color: transparent; }
QTableWidget::item { padding: 4px 8px; }
QTableWidget::item:selected { background: palette(highlight); color: palette(highlighted-text); }
QHeaderView::section { padding: 6px 8px; border: none; border-bottom: 1px solid palette(mid); background: palette(base); font-weight: 600; }
QProgressBar { border: none; background: palette(midlight); border-radius: 3px; max-height: 6px; }
QProgressBar::chunk { background: palette(highlight); border-radius: 3px; }
QTabWidget::pane { border: none; }
QTabBar::tab { padding: 9px 20px; border: none; border-bottom: 2px solid transparent; background: transparent; }
QTabBar::tab:selected { border-bottom-color: palette(highlight); font-weight: 600; }
QTabBar::tab:hover:!selected { border-bottom-color: palette(mid); }
QScrollArea#preview { border: 1px solid palette(mid); border-radius: 8px; background: palette(window); }
QLabel#page { background: white; border: 1px solid palette(mid); }
QPlainTextEdit { border: 1px solid palette(mid); border-radius: 8px; background: palette(base); }
QSplitter::handle { background: transparent; width: 10px; }
"""


# --------------------------------------------------------------------------- theme
def apply_theme(app: QApplication) -> None:
    """Fusion + a clean light/dark palette that follows the system color scheme."""
    app.setStyle(QStyleFactory.create("Fusion"))
    dark = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    c = ({"window": "#1e2024", "base": "#26292e", "alt": "#2b2e34", "text": "#e7e9ec", "button": "#2b2e34",
          "mid": "#3b3f46", "midlight": "#33363c", "placeholder": "#8a9099"} if dark else
         {"window": "#f4f5f7", "base": "#ffffff", "alt": "#f8f9fb", "text": "#1d2024", "button": "#ffffff",
          "mid": "#d6d9de", "midlight": "#eceef1", "placeholder": "#7c828b"})
    p = QPalette()
    for role, key in [(QPalette.Window, "window"), (QPalette.Base, "base"), (QPalette.AlternateBase, "alt"),
                      (QPalette.WindowText, "text"), (QPalette.Text, "text"), (QPalette.ButtonText, "text"),
                      (QPalette.Button, "button"), (QPalette.Mid, "mid"), (QPalette.Midlight, "midlight"),
                      (QPalette.PlaceholderText, "placeholder"), (QPalette.ToolTipBase, "base"),
                      (QPalette.ToolTipText, "text")]:
        p.setColor(role, QColor(c[key]))
    p.setColor(QPalette.Highlight, QColor(ACCENT))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(c["placeholder"]))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(c["placeholder"]))
    app.setPalette(p)
    app.setStyleSheet(STYLE % {"accent_hover": QColor(ACCENT).lighter(112).name()})


def card() -> tuple[QFrame, QVBoxLayout]:
    f = QFrame(objectName="card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(8)
    return f, lay


def button(text: str, slot, primary: bool = False, flat: bool = False, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if primary:
        b.setObjectName("primary")
    elif flat:
        b.setObjectName("flat")
    b.setCursor(Qt.PointingHandCursor)
    b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    return b


def set_chip(label: QLabel, text: str, color: str) -> None:
    c = QColor(color)
    label.setText(text)
    label.setStyleSheet(f"color: {color}; background: rgba({c.red()},{c.green()},{c.blue()},38);")
    label.setVisible(bool(text))


def open_folder(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


# --------------------------------------------------------------------------- background jobs
class _Signals(QObject):
    progress = Signal(object)
    done = Signal(object)
    failed = Signal(object)


class _Relay(QObject):
    """Lives in the GUI thread, so signals emitted by the worker arrive queued here."""

    def __init__(self, on_progress, on_done, on_failed):
        super().__init__()
        self._p, self._d, self._f = on_progress, on_done, on_failed

    @Slot(object)
    def progress(self, v):
        if self._p:
            self._p(v)

    @Slot(object)
    def done(self, v):
        self._d(v)

    @Slot(object)
    def failed(self, e):
        self._f(e)


class Jobs(QObject):
    """One background job at a time. pdfium is not thread safe, so the GUI must not render
    previews while `busy`; `idle` fires when a job ends so the preview can resume."""
    idle = Signal()

    def __init__(self):
        super().__init__()
        self.busy = False
        self._keep: set = set()

    def run(self, fn, on_done, on_failed, on_progress=None) -> None:
        self.busy = True
        sig = _Signals()
        relay = _Relay(on_progress, lambda r: self._finish(on_done, r, sig, relay),
                       lambda e: self._finish(on_failed, e, sig, relay))
        sig.progress.connect(relay.progress)
        sig.done.connect(relay.done)
        sig.failed.connect(relay.failed)
        self._keep.add((sig, relay))

        def work():
            try:
                sig.done.emit(fn(sig.progress.emit))
            except Exception as exc:  # report every failure in the GUI
                sig.failed.emit(exc)
        QThreadPool.globalInstance().start(work)

    def _finish(self, cb, arg, sig, relay):
        self.busy = False
        self._keep.discard((sig, relay))
        cb(arg)
        self.idle.emit()


# --------------------------------------------------------------------------- preview
class PreviewPane(QWidget):
    """All pages of a page range stacked vertically. Placeholders are laid out at once
    (page sizes are known without rendering); pages are then rendered one per event-loop
    turn, always the next one nearest to what is on screen. Ctrl+wheel zooms."""

    def __init__(self, jobs: Jobs):
        super().__init__()
        self.jobs = jobs
        self.zoom = 1.0
        self._path = ""
        self._doc = None
        self._range: tuple[int, int] | None = None
        self._slots: list[tuple[int, QLabel]] = []
        self._done: set[int] = set()
        self._gen = 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        title = QLabel("Preview")
        title.setStyleSheet("font-weight: 600;")
        bar.addWidget(title)
        bar.addStretch()
        bar.addWidget(button("−", lambda: self.set_zoom(self.zoom / 1.25), flat=True, tip="Zoom out (Ctrl+wheel)"))
        self.zoom_label = QLabel("100%", objectName="muted")
        self.zoom_label.setMinimumWidth(44)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        bar.addWidget(self.zoom_label)
        bar.addWidget(button("+", lambda: self.set_zoom(self.zoom * 1.25), flat=True, tip="Zoom in (Ctrl+wheel)"))
        bar.addWidget(button("Fit", lambda: self.set_zoom(1.0), flat=True, tip="Fit page width"))
        lay.addLayout(bar)

        self.area = QScrollArea(objectName="preview")
        self.area.setWidgetResizable(True)
        self.area.viewport().installEventFilter(self)
        self.area.verticalScrollBar().valueChanged.connect(lambda _: self._kick())
        self.canvas = QWidget()
        self.vbox = QVBoxLayout(self.canvas)
        self.vbox.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.vbox.setContentsMargins(16, 12, 16, 16)
        self.vbox.setSpacing(4)
        self.area.setWidget(self.canvas)
        lay.addWidget(self.area, 1)

        self._relayout = QTimer(self, singleShot=True, interval=150)
        self._relayout.timeout.connect(lambda: self._build(keep_position=True))
        self._ticker = QTimer(self, singleShot=True, interval=0)
        self._ticker.timeout.connect(self._render_next)
        self._message("Select a section to see its pages.")

    # ---- public
    def show_pages(self, path: str, rng: tuple[int, int] | None, force: bool = False) -> None:
        if rng is None:
            self._range = None
            self._message("Select a section to see its pages.")
            return
        if not force and path == self._path and rng == self._range:
            return
        if path != self._path:
            self._path, self._doc = path, None
        self._range = rng
        self._build(keep_position=False)

    def clear(self) -> None:
        self._path, self._doc, self._range = "", None, None
        self._message("Select a section to see its pages.")

    def resume(self) -> None:
        self._kick()

    def set_zoom(self, z: float) -> None:
        self.zoom = min(4.0, max(0.4, z))
        self.zoom_label.setText(f"{round(self.zoom * 100)}%")
        if self._range:
            self._relayout.start()

    # ---- internals
    def eventFilter(self, obj, ev):
        if ev.type() == ev.Type.Wheel and ev.modifiers() & Qt.ControlModifier:
            self.set_zoom(self.zoom * (1.25 if ev.angleDelta().y() > 0 else 0.8))
            return True
        if ev.type() == ev.Type.Resize and self._range:
            self._relayout.start()
        return super().eventFilter(obj, ev)

    def _clear_layout(self) -> None:
        self._gen += 1
        self._slots, self._done = [], set()
        while self.vbox.count():
            w = self.vbox.takeAt(0).widget()
            if w:
                w.deleteLater()

    def _message(self, text: str) -> None:
        self._clear_layout()
        m = QLabel(text, objectName="muted")
        m.setAlignment(Qt.AlignCenter)
        m.setContentsMargins(0, 40, 0, 0)
        self.vbox.addWidget(m)

    def _pdf(self):
        if self._doc is None:
            self._doc = pdfium.PdfDocument(self._path)
        return self._doc

    def _build(self, keep_position: bool) -> None:
        if not self._range or self.jobs.busy:
            return
        sb = self.area.verticalScrollBar()
        frac = sb.value() / max(sb.maximum(), 1) if keep_position else 0.0
        self._clear_layout()
        pdf = self._pdf()
        width = max(int((self.area.viewport().width() - 34) * self.zoom), 80)
        for i in range(self._range[0], self._range[1] + 1):
            w, h = pdf[i].get_size()
            cap = QLabel(f"Page {i + 1}", objectName="muted")
            cap.setContentsMargins(0, 8, 0, 0)
            page = QLabel(objectName="page")
            page.setFixedSize(width, int(width * h / w))
            page.setAlignment(Qt.AlignCenter)
            self.vbox.addWidget(cap, 0, Qt.AlignLeft if self.zoom > 1 else Qt.AlignHCenter)
            self.vbox.addWidget(page, 0, Qt.AlignHCenter)
            self._slots.append((i, page))
        self._width = width
        gen = self._gen
        QTimer.singleShot(0, lambda: (gen == self._gen and sb.setValue(int(frac * sb.maximum())), self._kick()))

    def _kick(self) -> None:
        if self._slots and not self._ticker.isActive():
            self._ticker.start()

    def _render_next(self) -> None:
        if self.jobs.busy or not self._slots:
            return
        top = self.area.verticalScrollBar().value()
        bottom = top + self.area.viewport().height()
        todo = [(i, lab) for i, lab in self._slots if i not in self._done]
        if not todo:
            return
        visible = [s for s in todo if s[1].y() + s[1].height() >= top and s[1].y() <= bottom]
        below = [s for s in todo if s[1].y() > bottom]
        i, lab = (visible or below or todo)[0]
        dpr = self.devicePixelRatioF()
        page = self._pdf()[i]
        img = page.render(scale=lab.width() * dpr / page.get_width()).to_pil().convert("RGB")
        qimg = QImage(img.tobytes(), img.width, img.height, img.width * 3, QImage.Format_RGB888).copy()
        pix = QPixmap.fromImage(qimg)
        pix.setDevicePixelRatio(dpr)
        lab.setPixmap(pix)
        self._done.add(i)
        self._ticker.start()


# --------------------------------------------------------------------------- Score & Parts tab
PAGES_RE = re.compile(r"^\s*(\d+)\s*(?:[-–]\s*(\d+))?\s*$")


class PartsTab(QWidget):
    def __init__(self, jobs: Jobs):
        super().__init__()
        self.jobs = jobs
        self.sections: list[split_parts.Section] = []
        self.npages = 0
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)

        # input card
        c, cl = card()
        head = QLabel("Split a set into score and parts", objectName="h1")
        sub = QLabel("Each part is saved as “Title - Instrument.pdf”. Drop a PDF anywhere in the window.",
                     objectName="muted")
        cl.addWidget(head)
        cl.addWidget(sub)
        row = QHBoxLayout()
        self.input = QLineEdit(placeholderText="PDF with score and/or parts…")
        row.addWidget(self.input, 1)
        row.addWidget(button("Browse…", self.pick_file))
        self.analyze_btn = button("Analyze", self.analyze, primary=True)
        row.addWidget(self.analyze_btn)
        cl.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Title"))
        self.title = QLineEdit(placeholderText="detected from the title pages")
        row.addWidget(self.title, 1)
        cl.addLayout(row)
        self.progress = QProgressBar(textVisible=False)
        self.progress.setVisible(False)
        cl.addWidget(self.progress)
        root.addWidget(c)

        # sections | preview
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        hl = QHBoxLayout()
        lab = QLabel("Sections")
        lab.setStyleSheet("font-weight: 600;")
        hl.addWidget(lab)
        hl.addStretch()
        self.cover = QLabel(objectName="chip")
        self.cover.setVisible(False)
        hl.addWidget(self.cover)
        ll.addLayout(hl)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Pages", "Score / Instrument"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        self.table.itemChanged.connect(self.item_changed)
        self.table.cellDoubleClicked.connect(self.double_clicked)
        ll.addWidget(self.table, 1)
        hint = QLabel("Double-click a name or page range to edit it.", objectName="muted")
        ll.addWidget(hint)
        tools = QHBoxLayout()
        tools.addWidget(button("Merge with next", self.merge, tip="Join the selected section with the one below"))
        tools.addWidget(button("Split at page…", self.split_at, tip="Cut the selected section in two"))
        tools.addWidget(button("Delete", self.delete, tip="Remove the section (its pages become unassigned)"))
        tools.addStretch()
        ll.addLayout(tools)
        split.addWidget(left)
        self.preview = PreviewPane(jobs)
        split.addWidget(self.preview)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        split.setSizes([520, 520])
        root.addWidget(split, 1)
        QShortcut(QKeySequence.Delete, self.table, activated=self.delete)

        # output card
        c, cl = card()
        row = QHBoxLayout()
        row.addWidget(QLabel("Output folder"))
        self.output = QLineEdit(placeholderText="<input>_parts next to the PDF")
        row.addWidget(self.output, 1)
        row.addWidget(button("Browse…", self.pick_out))
        self.export_btn = button("Export PDFs", self.export, primary=True)
        self.export_btn.setEnabled(False)
        row.addWidget(self.export_btn)
        cl.addLayout(row)
        self.status = QLabel("Choose a PDF and press Analyze.", objectName="muted")
        cl.addWidget(self.status)
        root.addWidget(c)

    # ---- files
    def set_input(self, path: str) -> None:
        self.input.setText(path)
        self.output.setText(str(Path(path).with_name(Path(path).stem + "_parts")))

    def pick_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Choose PDF", self.input.text(), "PDF files (*.pdf)")
        if f:
            self.set_input(f)

    def pick_out(self):
        d = QFileDialog.getExistingDirectory(self, "Output folder", self.output.text())
        if d:
            self.output.setText(d)

    # ---- analysis
    def analyze(self):
        src = Path(self.input.text().strip())
        if not src.is_file():
            QMessageBox.warning(self, "Score & Parts", "Choose an existing PDF first.")
            return
        if not self.output.text().strip():
            self.output.setText(str(src.with_name(src.stem + "_parts")))

        halve_to = None
        wide = split_parts.landscape_pages(src)
        if wide:
            total = len(pdfium.PdfDocument(str(src)))
            pages = "all pages" if len(wide) == total else \
                f"pages {split_parts.format_ranges(split_parts._ranges(wide))}"
            box = QMessageBox(QMessageBox.Question, "Score & Parts",
                              f"{len(wide)} of {total} pages are landscape. Split them in half first?", parent=self)
            box.setInformativeText(
                f"Landscape pages ({pages}) usually hold two pages side by side, e.g. an A3 sheet "
                f"with two A4 pages.\n\nSplitting is lossless. The result is saved next to the original "
                f"as “{split_parts.halved_path(src).name}” and the parts are taken from that file.")
            split_b = box.addButton("Split in half", QMessageBox.AcceptRole)
            keep_b = box.addButton("Keep as is", QMessageBox.NoRole)
            box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(split_b)
            box.exec()
            if box.clickedButton() is split_b:
                halve_to = split_parts.halved_path(src)
            elif box.clickedButton() is not keep_b:
                return

        self.preview.clear()
        self.analyze_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)

        def work(report):
            path = src
            if halve_to:
                report(("status", "Splitting landscape pages in half…"))
                split_parts.split_landscape(src, halve_to)
                path = halve_to
            report(("status", "Reading pages with OCR…"))
            return path, split_parts.analyze(path, lambda d, n: report(("page", d, n)))

        self.jobs.run(work, self.analyzed, self.failed, self.on_progress)

    def on_progress(self, msg):
        if msg[0] == "status":
            self.status.setText(msg[1])
        else:
            _, d, n = msg
            self.progress.setRange(0, n)
            self.progress.setValue(d)
            self.status.setText(f"Reading page {d} of {n}…")

    def analyzed(self, result):
        path, (title, sections) = result
        self.input.setText(str(path))            # the halved copy when pages were split
        self.npages = len(pdfium.PdfDocument(str(path)))
        self.title.setText(split_contrast.clean_name(title) if title else path.stem.removesuffix("_A4"))
        self.sections = sections
        self.progress.setVisible(False)
        self.analyze_btn.setEnabled(True)
        self.export_btn.setEnabled(True)
        self.status.setText(f"Found {len(sections)} sections. Check names and pages, then export.")
        self.refresh(select=sections[0] if sections else None)

    def failed(self, exc):
        self.progress.setVisible(False)
        self.analyze_btn.setEnabled(True)
        self.export_btn.setEnabled(bool(self.sections))
        self.status.setText(f"Error: {exc}")
        QMessageBox.critical(self, "Score & Parts", str(exc))

    # ---- table
    def refresh(self, select=None):
        """Rebuild the table: sections plus red rows for pages that are in no section."""
        self.sections.sort(key=lambda s: (s.start, s.end))
        missing, dup = split_parts.coverage(self.sections, self.npages)
        rows = [(s.start, 0, s) for s in self.sections] + [(a, 1, (a, b)) for a, b in missing]
        rows.sort(key=lambda r: (r[0], r[1]))
        self._loading = True
        self.table.setRowCount(len(rows))
        bold = QFont()
        bold.setBold(True)
        red = QColor(DANGER)
        red_bg = QColor(red.red(), red.green(), red.blue(), 45)
        sel_row = None
        for r, (_, _, ref) in enumerate(rows):
            if isinstance(ref, split_parts.Section):
                pages = QTableWidgetItem(ref.pages)
                name = QTableWidgetItem(ref.name)
                if ref.is_score:
                    name.setFont(bold)
                if ref is select:
                    sel_row = r
            else:
                a, b = ref
                pages = QTableWidgetItem(split_parts.format_ranges([(a, b)]))
                name = QTableWidgetItem("Not in any file — double-click to add")
                for it in (pages, name):
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    it.setBackground(red_bg)
                    it.setForeground(red)
                if select == ref:
                    sel_row = r
            pages.setTextAlignment(Qt.AlignCenter)
            pages.setData(Qt.UserRole, ref)
            self.table.setItem(r, 0, pages)
            self.table.setItem(r, 1, name)
        self._loading = False

        if missing:
            set_chip(self.cover, f"Missing pages: {split_parts.format_ranges(missing)}", DANGER)
        elif dup:
            set_chip(self.cover, f"Pages in two files: {split_parts.format_ranges(dup)}", WARN)
        elif self.sections:
            set_chip(self.cover, f"✓ All {self.npages} pages assigned", OK)
        else:
            set_chip(self.cover, "", OK)
        if sel_row is not None:
            self.table.selectRow(sel_row)
            self.table.scrollToItem(self.table.item(sel_row, 0))
        self.selection_changed()

    def _ref(self, row: int):
        it = self.table.item(row, 0)
        return it.data(Qt.UserRole) if it else None

    def current(self):
        rows = self.table.selectionModel().selectedRows()
        return self._ref(rows[0].row()) if rows else None

    def selection_changed(self):
        ref = self.current()
        if isinstance(ref, split_parts.Section):
            self.preview.show_pages(self.input.text().strip(), (ref.start, ref.end))
        elif ref is not None:
            self.preview.show_pages(self.input.text().strip(), ref)
        else:
            self.preview.show_pages("", None)

    def item_changed(self, item: QTableWidgetItem):
        if self._loading:
            return
        ref = self._ref(item.row())
        if not isinstance(ref, split_parts.Section):
            return
        text = item.text().strip()
        if item.column() == 1:
            if text:
                ref.name = text
        else:
            m = PAGES_RE.match(text)
            a, b = (int(m.group(1)), int(m.group(2) or m.group(1))) if m else (0, 0)
            if 1 <= a <= b <= self.npages:
                ref.start, ref.end = a - 1, b - 1
            else:
                QMessageBox.warning(self, "Pages", f"Enter a page or range within 1–{self.npages}, e.g. “33-36”.")
        QTimer.singleShot(0, lambda: self.refresh(select=ref))

    def double_clicked(self, row: int, col: int):
        ref = self._ref(row)
        if isinstance(ref, tuple):                  # unassigned pages -> new section
            s = split_parts.Section(ref[0], ref[1], "New part")
            self.sections.append(s)
            self.refresh(select=s)
            r = self.table.selectionModel().selectedRows()[0].row()
            self.table.editItem(self.table.item(r, 1))

    def merge(self):
        ref = self.current()
        if not isinstance(ref, split_parts.Section):
            return
        i = self.sections.index(ref)
        if i + 1 < len(self.sections):
            nxt = self.sections.pop(i + 1)
            ref.end = max(ref.end, nxt.end)
            self.refresh(select=ref)

    def split_at(self):
        ref = self.current()
        if not isinstance(ref, split_parts.Section) or ref.end == ref.start:
            return
        page, ok = QInputDialog.getInt(self, "Split section",
                                       f"First page of the new section ({ref.start + 2}–{ref.end + 1}):",
                                       ref.start + 2, ref.start + 2, ref.end + 1)
        if ok:
            new = split_parts.Section(page - 1, ref.end, f"{ref.name} (2)")
            ref.end = page - 2
            self.sections.append(new)
            self.refresh(select=new)

    def delete(self):
        ref = self.current()
        if isinstance(ref, split_parts.Section):
            self.sections.remove(ref)
            self.refresh()

    # ---- export
    def export(self):
        if not self.sections:
            return
        missing, _ = split_parts.coverage(self.sections, self.npages)
        if missing:
            box = QMessageBox(QMessageBox.Warning, "Score & Parts", "Some pages are not in any file", parent=self)
            box.setInformativeText(f"Pages {split_parts.format_ranges(missing)} are not assigned to any part "
                                   f"and will not be exported.")
            back = box.addButton("Go back", QMessageBox.RejectRole)
            box.addButton("Export anyway", QMessageBox.DestructiveRole)
            box.setDefaultButton(back)
            box.exec()
            if box.clickedButton() is back:
                return
        src = Path(self.input.text().strip())
        out = Path(self.output.text().strip() or src.with_name(src.stem + "_parts"))
        title = self.title.text().strip()
        sections = list(self.sections)
        self.export_btn.setEnabled(False)
        self.status.setText("Writing PDFs…")
        self.jobs.run(lambda _: split_parts.export_sections(src, sections, title, out),
                      self.exported, self.failed)

    def exported(self, files):
        self.export_btn.setEnabled(True)
        self.status.setText(f"Wrote {len(files)} PDFs to {files[0].parent if files else ''}")
        if files:
            open_folder(files[0].parent)


# --------------------------------------------------------------------------- A3 -> A4 tab
class A3Tab(QWidget):
    def __init__(self, jobs: Jobs):
        super().__init__()
        self.jobs = jobs
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)

        c, cl = card()
        cl.addWidget(QLabel("A3 → A4, contrast and rename", objectName="h1"))
        cl.addWidget(QLabel("Splits landscape pages into two A4 pages, darkens faint scans and names the "
                            "file “Title - Instrument.pdf”. Works on one PDF or a whole folder.",
                            objectName="muted", wordWrap=True))
        row = QHBoxLayout()
        self.input = QLineEdit(placeholderText="PDF file or folder of PDFs…")
        row.addWidget(self.input, 1)
        row.addWidget(button("File…", self.pick_file))
        row.addWidget(button("Folder…", self.pick_dir))
        cl.addLayout(row)
        row = QHBoxLayout()
        self.output = QLineEdit(placeholderText="Output (optional): file name, or folder for a folder input")
        row.addWidget(self.output, 1)
        row.addWidget(button("Browse…", self.pick_out))
        cl.addLayout(row)
        opts = QHBoxLayout()
        self.split = QCheckBox("Split landscape pages", checked=True)
        self.contrast = QCheckBox("Increase contrast", checked=True)
        self.rename = QCheckBox("Rename “Title - Instrument”", checked=True)
        self.recursive = QCheckBox("Include subfolders")
        for cb in (self.split, self.contrast, self.rename, self.recursive):
            opts.addWidget(cb)
        opts.addStretch()
        self.run_btn = button("Run", self.start, primary=True)
        opts.addWidget(self.run_btn)
        cl.addLayout(opts)
        self.progress = QProgressBar(textVisible=False)
        self.progress.setVisible(False)
        cl.addWidget(self.progress)
        root.addWidget(c)

        self.log = QPlainTextEdit(readOnly=True, placeholderText="Results appear here.")
        root.addWidget(self.log, 1)

    def set_input(self, path: str) -> None:
        self.input.setText(path)

    def pick_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Choose PDF", self.input.text(), "PDF files (*.pdf)")
        if f:
            self.input.setText(f)

    def pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Choose folder", self.input.text())
        if d:
            self.input.setText(d)

    def pick_out(self):
        if Path(self.input.text().strip()).is_file():
            f, _ = QFileDialog.getSaveFileName(self, "Output PDF", "", "PDF files (*.pdf)")
        else:
            f = QFileDialog.getExistingDirectory(self, "Output folder")
        if f:
            self.output.setText(f)

    def start(self):
        src = Path(self.input.text().strip())
        if not self.input.text().strip() or not src.exists():
            QMessageBox.warning(self, "A3 → A4", "Choose an existing PDF or folder first.")
            return
        out = self.output.text().strip()
        args = argparse.Namespace(
            input=src, output=Path(out) if out else None, recursive=self.recursive.isChecked(),
            no_rename=not self.rename.isChecked(), header=0.20, dpi=300, black=110, white=215,
            gamma=0.7, no_split=not self.split.isChecked(), no_contrast=not self.contrast.isChecked())
        jobs = split_contrast.collect_jobs(args)
        if not jobs:
            QMessageBox.information(self, "A3 → A4", "No PDF files found.")
            return
        self.run_btn.setEnabled(False)
        self.progress.setRange(0, len(jobs))
        self.progress.setValue(0)
        self.progress.setVisible(True)

        def work(report):
            used, failed, outs = set(), 0, []
            for n, (s, d, rename) in enumerate(jobs, 1):
                try:
                    o, count, note = split_contrast.process_pdf(s, d, rename, args, used)
                    outs.append(o)
                    msg = f"✓  {s.name}  →  {o.name}  ({count} pages)" + (f"   [{note}]" if note else "")
                except Exception as exc:
                    failed += 1
                    msg = f"✗  {s.name}: {exc}"
                report((n, msg))
            return len(jobs) - failed, failed, outs

        self.jobs.run(work, self.done, self.failed, self.on_progress)

    def on_progress(self, msg):
        n, text = msg
        self.progress.setValue(n)
        self.log.appendPlainText(text)

    def done(self, result):
        ok, failed, outs = result
        self.run_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.log.appendPlainText(f"Done: {ok} ok, {failed} failed\n")
        if outs:
            open_folder(outs[0].parent)

    def failed(self, exc):
        self.run_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.log.appendPlainText(f"Error: {exc}")
        QMessageBox.critical(self, "A3 → A4", str(exc))


# --------------------------------------------------------------------------- main window
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sheet Music PDF Tools")
        self.resize(1240, 860)
        self.setAcceptDrops(True)
        self.jobs = Jobs()
        self.tabs = QTabWidget(documentMode=True)
        self.parts = PartsTab(self.jobs)
        self.a3 = A3Tab(self.jobs)
        self.tabs.addTab(self.parts, "Score && Parts")
        self.tabs.addTab(self.a3, "A3 → A4")
        self.setCentralWidget(self.tabs)
        self.jobs.idle.connect(self.parts.preview.resume)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if not urls:
            return
        path = Path(urls[0])
        if self.tabs.currentWidget() is self.parts and path.suffix.lower() == ".pdf":
            self.parts.set_input(str(path))
        elif self.tabs.currentWidget() is self.a3:
            self.a3.set_input(str(path))


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Sheet Music PDF Tools")
    apply_theme(app)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
