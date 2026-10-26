"""The Score & Parts tab: analyze a PDF, then check and correct the grouping (map or list) before exporting."""

from pathlib import Path

import pypdfium2 as pdfium
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from ..names import clean_name
from ..parts import (
    DELETE, NEW_PART, Section, analyze, apply_move, coverage, export_sections, format_ranges, halved_path, landscape_pages,
    merge_with_next, parse_pages, ranges, split_landscape, split_section, unassigned_pages,
)
from .groupmap import MapView
from .jobs import Jobs
from .preview import PreviewPane
from .theme import DANGER, OK, WARN, button, card, open_folder, set_chip


class PartsTab(QWidget):
    def __init__(self, jobs: Jobs):
        super().__init__()
        self.jobs = jobs
        self.sections: list[Section] = []
        self.npages = 0
        self._loading = False
        self._undo: list[tuple[list[tuple], set[int]]] = []
        self.deleted: set[int] = set()              # pages removed on purpose (blank, unused): not exported, not "missing"

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
        ll.setContentsMargins(0, 0, 8, 0)
        hl = QHBoxLayout()
        lab = QLabel("Sections")
        lab.setStyleSheet("font-weight: 600;")
        hl.addWidget(lab)
        hl.addStretch()
        self.cover = QLabel(objectName="chip")
        self.cover.setVisible(False)
        hl.addWidget(self.cover)
        self.view_group = QButtonGroup(self)
        for i, (text, tip) in enumerate([("Map", "Pages as thumbnails, grouped by part — drag pages between parts"),
                                         ("List", "One row per part, with page ranges to edit")]):
            b = QPushButton(text, objectName="seg", checkable=True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(tip)
            self.view_group.addButton(b, i)
            hl.addWidget(b)
        self.view_group.button(0).setChecked(True)
        self.view_group.idClicked.connect(self.set_view)
        ll.addLayout(hl)
        self.views = QStackedWidget()
        list_page = QWidget()
        lp = QVBoxLayout(list_page)
        lp.setContentsMargins(0, 0, 0, 0)
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
        lp.addWidget(self.table, 1)
        hint = QLabel("Double-click a name or page range to edit it (e.g. “33-36, 40”).", objectName="muted")
        lp.addWidget(hint)
        tools = QHBoxLayout()
        tools.addWidget(button("Merge with next", self.merge, tip="Join the selected section with the one below"))
        tools.addWidget(button("Split at page…", self.split_at, tip="Cut the selected section in two"))
        tools.addWidget(button("Delete", self.delete, tip="Remove the section (its pages become unassigned)"))
        tools.addStretch()
        lp.addLayout(tools)
        self.map = MapView(jobs)
        self.map.move_requested.connect(self.move_pages)
        self.map.rename_requested.connect(self.rename_section)
        self.map.picked.connect(self.map_picked)
        self.map.delete_requested.connect(lambda pages: self.move_pages(pages, DELETE, -1))
        self.views.addWidget(self.map)
        self.views.addWidget(list_page)
        ll.addWidget(self.views, 1)
        split.addWidget(left)
        self.preview = PreviewPane(jobs)
        split.addWidget(self.preview)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        split.setSizes([520, 520])
        root.addWidget(split, 1)
        QShortcut(QKeySequence.Delete, self.table, activated=self.delete)
        QShortcut(QKeySequence.Undo, self, activated=self.undo)

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
        wide = landscape_pages(src)
        if wide:
            total = len(pdfium.PdfDocument(str(src)))
            pages = "all pages" if len(wide) == total else \
                f"pages {format_ranges(ranges(wide))}"
            box = QMessageBox(QMessageBox.Question, "Score & Parts",
                              f"{len(wide)} of {total} pages are landscape. Split them in half first?", parent=self)
            box.setInformativeText(
                f"Landscape pages ({pages}) usually hold two pages side by side, e.g. an A3 sheet "
                f"with two A4 pages.\n\nSplitting is lossless. The result is saved next to the original "
                f"as “{halved_path(src).name}” and the parts are taken from that file.")
            split_b = box.addButton("Split in half", QMessageBox.AcceptRole)
            keep_b = box.addButton("Keep as is", QMessageBox.NoRole)
            box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(split_b)
            box.exec()
            if box.clickedButton() is split_b:
                halve_to = halved_path(src)
            elif box.clickedButton() is not keep_b:
                return

        self.preview.clear()
        self.map.set_data("", [], 0)
        self.analyze_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)

        def work(report):
            path = src
            if halve_to:
                report(("status", "Splitting landscape pages in half…"))
                split_landscape(src, halve_to)
                path = halve_to
            report(("status", "Reading pages with OCR…"))
            return path, analyze(path, lambda d, n: report(("page", d, n)))

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
        self.title.setText(clean_name(title) if title else path.stem.removesuffix("_A4"))
        self.sections = sections
        self._undo.clear()
        self.deleted.clear()
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
        missing = ranges(unassigned_pages(self.sections, self.npages, self.deleted))
        dup = coverage(self.sections, self.npages)[1]
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
            if isinstance(ref, Section):
                pages = QTableWidgetItem(ref.pages)
                name = QTableWidgetItem(ref.name)
                if ref.is_score:
                    name.setFont(bold)
                if ref is select:
                    sel_row = r
            else:
                a, b = ref
                pages = QTableWidgetItem(format_ranges([(a, b)]))
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
            set_chip(self.cover, f"Missing pages: {format_ranges(missing)}", DANGER)
        elif dup:
            set_chip(self.cover, f"Pages in two files: {format_ranges(dup)}", WARN)
        elif self.sections:
            gone = f" ({len(self.deleted)} deleted)" if self.deleted else ""
            set_chip(self.cover, f"✓ All {self.npages - len(self.deleted)} pages assigned{gone}", OK)
        else:
            set_chip(self.cover, "", OK)
        if sel_row is not None:
            self.table.selectRow(sel_row)
            self.table.scrollToItem(self.table.item(sel_row, 0))
        sec = select if isinstance(select, Section) else None
        self.map.set_data(self.input.text().strip(), self.sections, self.npages, sec, deleted=self.deleted)
        if self.views.currentIndex() == 0:
            self._show(sec)
        else:
            self.selection_changed()

    def _ref(self, row: int):
        it = self.table.item(row, 0)
        return it.data(Qt.UserRole) if it else None

    def current(self):
        rows = self.table.selectionModel().selectedRows()
        return self._ref(rows[0].row()) if rows else None

    def _show(self, ref, focus: int | None = None):
        path = self.input.text().strip()
        if isinstance(ref, Section):
            self.preview.show_pages(path, ref.page_list(), focus)
        elif ref is not None:                       # a range of unassigned pages
            self.preview.show_pages(path, list(range(ref[0], ref[1] + 1)), focus)
        else:
            self.preview.show_pages("", None)

    def selection_changed(self):
        self._show(self.current())

    def set_view(self, index: int):
        self.views.setCurrentIndex(index)
        if index == 1:                              # list: select what the map had selected
            sec = self.map.current_section()
            for r in range(self.table.rowCount()):
                if sec is not None and self._ref(r) is sec:
                    self.table.selectRow(r)
                    break
            self.selection_changed()
        else:
            self._show(self.map.current_section())

    # ---- map edits
    def map_picked(self, sec, page):
        if sec is None:                             # the "not in any file" card
            self.preview.show_pages(self.input.text().strip(),
                                    unassigned_pages(self.sections, self.npages, self.deleted), page)
        elif sec == DELETE:                         # the "deleted pages" card
            self.preview.show_pages(self.input.text().strip(), sorted(self.deleted), page)
        else:
            self._show(sec, page)

    def rename_section(self, sec, name: str):
        if name and name != sec.name:
            self._remember()
            sec.name = name
            QTimer.singleShot(0, lambda: self.refresh(select=sec))

    def _remember(self) -> None:
        """Snapshot the grouping before a manual change (for Ctrl+Z)."""
        self._undo.append(([(s, s.name, s.page_list()) for s in self.sections], set(self.deleted)))
        del self._undo[:-50]

    def undo(self):
        if not self._undo or self.jobs.busy:
            return
        self.sections = []
        snapshot, self.deleted = self._undo.pop()
        for sec, name, pages in snapshot:
            sec.name = name
            sec.set_pages(pages)
            self.sections.append(sec)
        self.status.setText("Undone.")
        self.refresh()

    def move_pages(self, pages, target, row: int):
        """Called by the map: move pages to a section, a new section (NEW_PART) or out of every section."""
        moving = list(dict.fromkeys(pages))
        if not moving:
            return
        self._remember()
        select = apply_move(self.sections, self.deleted, moving, target, row)
        many = f"{len(moving)} page{'s' if len(moving) != 1 else ''}"
        self.status.setText(f"Deleted {many} (Ctrl+Z undoes; drag them back from “Deleted pages”)." if target == DELETE
                            else f"Moved {many}.")

        def apply():
            self.refresh(select=select)
            if target != DELETE:
                self.map.flash_pages(moving)
            if target == NEW_PART:
                self.map.edit_name(select)
        QTimer.singleShot(0, apply)                 # not while the drag that triggered this is still running

    def item_changed(self, item: QTableWidgetItem):
        if self._loading:
            return
        ref = self._ref(item.row())
        if not isinstance(ref, Section):
            return
        text = item.text().strip()
        if item.column() == 1:
            if text:
                self._remember()
                ref.name = text
        else:
            pages = parse_pages(text, self.npages)
            if pages:
                self._remember()
                ref.set_pages(pages)
            else:
                QMessageBox.warning(self, "Pages", f"Enter pages within 1–{self.npages}, e.g. “33-36” or “33-36, 40”.")
        QTimer.singleShot(0, lambda: self.refresh(select=ref))

    def double_clicked(self, row: int, col: int):
        ref = self._ref(row)
        if isinstance(ref, tuple):                  # unassigned pages -> new section
            s = Section(ref[0], ref[1], "New part")
            self._remember()
            self.sections.append(s)
            self.refresh(select=s)
            r = self.table.selectionModel().selectedRows()[0].row()
            self.table.editItem(self.table.item(r, 1))

    def merge(self):
        ref = self.current()
        if isinstance(ref, Section):
            self._remember()
            if merge_with_next(self.sections, ref):
                self.refresh(select=ref)
            else:
                self._undo.pop()

    def split_at(self):
        ref = self.current()
        pages = sorted(ref.page_list()) if isinstance(ref, Section) else []
        if len(pages) < 2:
            return
        page, ok = QInputDialog.getInt(self, "Split section",
                                       f"First page of the new section ({pages[1] + 1}–{pages[-1] + 1}):",
                                       pages[1] + 1, pages[1] + 1, pages[-1] + 1)
        if ok:
            self._remember()
            new = split_section(self.sections, ref, page - 1)
            if new:
                self.refresh(select=new)
            else:
                self._undo.pop()

    def delete(self):
        ref = self.current()
        if isinstance(ref, Section):
            self._remember()
            self.sections.remove(ref)
            self.refresh()

    # ---- export
    def export(self):
        if not self.sections:
            return
        missing = ranges(unassigned_pages(self.sections, self.npages, self.deleted))
        if missing:
            box = QMessageBox(QMessageBox.Warning, "Score & Parts", "Some pages are not in any file", parent=self)
            box.setInformativeText(f"Pages {format_ranges(missing)} are not assigned to any part "
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
        self.jobs.run(lambda _: export_sections(src, sections, title, out),
                      self.exported, self.failed)

    def exported(self, files):
        self.export_btn.setEnabled(True)
        self.status.setText(f"Wrote {len(files)} PDFs to {files[0].parent if files else ''}")
        if files:
            open_folder(files[0].parent)
