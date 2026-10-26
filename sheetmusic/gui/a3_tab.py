"""The A3 -> A4 tab."""

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QVBoxLayout,
    QWidget,
)

from .. import a3
from .jobs import Jobs
from .theme import button, card, open_folder


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
        opts = a3.A3Options(split=self.split.isChecked(), contrast=self.contrast.isChecked())
        jobs = a3.plan_jobs(src, Path(out) if out else None, self.recursive.isChecked(),
                            rename=self.rename.isChecked())
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
                    o, count, note = a3.process_pdf(s, d, rename, opts, used)
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
