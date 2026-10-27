"""The main window and the entry point of the desktop app."""

import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

from .a3_tab import A3Tab
from .jobs import Jobs
from .parts_tab import PartsTab
from .theme import apply_theme


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


def main(argv: list[str] | None = None) -> int:
    # Qt 6 on Wayland logs a spurious text-input warning whenever the window loses focus.
    rules = os.environ.get("QT_LOGGING_RULES", "")
    os.environ["QT_LOGGING_RULES"] = ";".join(filter(None, [rules, "qt.qpa.wayland.textinput=false"]))
    app = QApplication([sys.argv[0], *(argv or [])])
    app.setApplicationName("Sheet Music PDF Tools")
    app.setWindowIcon(QIcon(str(Path(__file__).with_name("icon.png"))))
    app.setDesktopFileName("sheetmusic-tools")     # Wayland takes the icon from the installed .desktop file
    apply_theme(app)
    w = MainWindow()
    w.show()
    return app.exec()
