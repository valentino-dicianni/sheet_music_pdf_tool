"""The page preview on the right of the Score & Parts tab."""

import pypdfium2 as pdfium
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from .jobs import Jobs
from .theme import button


class PreviewPane(QWidget):
    """The pages of a section stacked vertically (any list of pages, in output order). Placeholders are laid out at once
    (page sizes are known without rendering); pages are then rendered one per event-loop
    turn, always the next one nearest to what is on screen. Ctrl+wheel zooms."""

    def __init__(self, jobs: Jobs):
        super().__init__()
        self.jobs = jobs
        self.zoom = 1.0
        self._path = ""
        self._doc = None
        self._pages: list[int] | None = None
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
    def show_pages(self, path: str, pages: list[int] | None, focus: int | None = None, force: bool = False) -> None:
        """Show `pages` of the PDF; `focus` scrolls to one of them."""
        if not pages:
            self._pages = None
            self._message("Select a section to see its pages.")
            return
        if not force and path == self._path and pages == self._pages:
            if focus is not None:
                self._scroll_to(focus)
            return
        if path != self._path:
            self._path, self._doc = path, None
        self._pages = list(pages)
        self._build(keep_position=False, focus=focus)

    def clear(self) -> None:
        self._path, self._doc, self._pages = "", None, None
        self._message("Select a section to see its pages.")

    def resume(self) -> None:
        self._kick()

    def set_zoom(self, z: float) -> None:
        self.zoom = min(4.0, max(0.4, z))
        self.zoom_label.setText(f"{round(self.zoom * 100)}%")
        if self._pages:
            self._relayout.start()

    # ---- internals
    def eventFilter(self, obj, ev):
        if ev.type() == ev.Type.Wheel and ev.modifiers() & Qt.ControlModifier:
            self.set_zoom(self.zoom * (1.25 if ev.angleDelta().y() > 0 else 0.8))
            return True
        if ev.type() == ev.Type.Resize and self._pages:
            self._relayout.start()
        return super().eventFilter(obj, ev)

    def _clear_layout(self) -> None:
        self._gen += 1
        self._slots, self._done = [], set()
        while self.vbox.count():
            w = self.vbox.takeAt(0).widget()
            if w:
                w.hide()                        # deleteLater alone leaves it painted until the loop runs
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

    def _scroll_to(self, page: int) -> None:
        for i, lab in self._slots:
            if i == page:
                self.vbox.activate()
                self.area.verticalScrollBar().setValue(max(lab.y() - 30, 0))
                break
        self._kick()

    def _build(self, keep_position: bool, focus: int | None = None) -> None:
        if not self._pages or self.jobs.busy:
            return
        sb = self.area.verticalScrollBar()
        frac = sb.value() / max(sb.maximum(), 1) if keep_position else 0.0
        self._clear_layout()
        pdf = self._pdf()
        width = max(int((self.area.viewport().width() - 34) * self.zoom), 80)
        for i in self._pages:
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
        if focus is not None:
            QTimer.singleShot(0, lambda: gen == self._gen and self._scroll_to(focus))
        else:
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
