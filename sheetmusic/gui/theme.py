"""Colors, the stylesheet and small widget helpers shared by every tab."""

from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QStyleFactory, QVBoxLayout


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
QFrame#group { background: palette(base); border: 1px solid palette(mid); border-radius: 8px; }
QFrame#group[active="true"] { border: 2px solid palette(highlight); }
QListWidget#thumbs { background: transparent; border: none; }
QListWidget#thumbs::item { border-radius: 4px; }
QListWidget#thumbs::item:selected { background: palette(highlight); color: palette(highlighted-text); }
QLineEdit#gname { border: 1px solid transparent; background: transparent; font-weight: 600; padding: 2px 4px; }
QLineEdit#gname:hover:!read-only, QLineEdit#gname:focus { border-color: palette(mid); background: palette(window); }
QLabel#dropzone { border: 2px dashed palette(mid); border-radius: 8px; padding: 14px; color: palette(placeholder-text); }
QPushButton#seg { border: none; border-radius: 0; border-bottom: 2px solid transparent; background: transparent; padding: 6px 14px; }
QPushButton#seg:checked { border-bottom-color: palette(highlight); font-weight: 600; }
QPushButton#seg:hover:!checked { border-bottom-color: palette(mid); }
QPushButton#seg:pressed { background: transparent; }
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
