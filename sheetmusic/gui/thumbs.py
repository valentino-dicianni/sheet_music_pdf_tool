"""Small page images for the grouping map."""

import pypdfium2 as pdfium
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPixmap

from .jobs import Jobs

THUMB_W, THUMB_H = 72, 102


class ThumbCache(QObject):
    """Small page images for the map, rendered one per event-loop turn so the window stays
    responsive; `prioritize` moves the pages on screen to the front of the queue."""

    ready = Signal(int)

    def __init__(self, jobs: Jobs):
        super().__init__()
        self.jobs = jobs
        self.pix: dict[int, QPixmap] = {}
        self._path = ""
        self._doc = None
        self._queue: list[int] = []
        self._timer = QTimer(self, singleShot=True, interval=0)
        self._timer.timeout.connect(self._tick)

    def set_path(self, path: str) -> None:
        if path != self._path:
            self._path, self._doc = path, None
            self.pix.clear()
            self._queue.clear()

    def request(self, pages) -> None:
        todo = [p for p in pages if p not in self.pix and p not in self._queue]
        self._queue.extend(todo)
        if self._queue and not self._timer.isActive():
            self._timer.start()

    def prioritize(self, pages) -> None:
        first = [p for p in pages if p in self._queue]
        if first:
            self._queue = first + [p for p in self._queue if p not in set(first)]

    def _tick(self) -> None:
        if not self._queue or not self._path:
            return
        if self.jobs.busy:                       # pdfium is not thread safe: wait for the analysis
            self._timer.start(200)
            return
        i = self._queue.pop(0)
        try:
            if self._doc is None:
                self._doc = pdfium.PdfDocument(self._path)
            page = self._doc[i]
            w, h = page.get_size()
            dpr = QGuiApplication.primaryScreen().devicePixelRatio() if QGuiApplication.primaryScreen() else 1.0
            img = page.render(scale=min(THUMB_W / w, THUMB_H / h) * dpr).to_pil().convert("RGB")
            pix = QPixmap.fromImage(QImage(img.tobytes(), img.width, img.height, img.width * 3,
                                           QImage.Format_RGB888).copy())
            pix.setDevicePixelRatio(dpr)
            self.pix[i] = pix
            self.ready.emit(i)
        except Exception:
            pass                                 # an unreadable page just keeps its placeholder
        if self._queue:
            self._timer.start()
