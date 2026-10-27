"""The grouping map: every part as a card of page thumbnails plus a strip that colors the whole document by part.
Pages move between parts by drag & drop (with animated drop targets) or the right-click menu. The widgets only
*ask* for changes (signals); the model is changed by `parts.move_pages` in the tab that owns the map."""

import json

from PySide6.QtCore import (
    QEasingCurve, QEvent, QMimeData, QPoint, QPointF, QRectF, QSize, QTimer, QVariantAnimation, Qt, Signal,
)
from PySide6.QtGui import QBrush, QColor, QCursor, QDrag, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem,
    QMenu, QPushButton, QScrollArea, QStyledItemDelegate, QStyleOptionViewItem, QToolTip, QVBoxLayout, QWidget,
)

from ..parts import DELETE, NEW_PART, coverage
from .jobs import Jobs
from .theme import ACCENT, DANGER, OK, WARN
from .thumbs import THUMB_H, THUMB_W, ThumbCache


PART_COLORS = ["#2f6fde", "#d6762d", "#2e9d57", "#9b51d0", "#c4496b", "#1f9fb0", "#b08a1f", "#6a7bd6"]
CELL_W, CELL_H = THUMB_W + 14, THUMB_H + 30
PAGES_MIME = "application/x-sheetmusic-pages"


def _pages_from(mime: QMimeData) -> list[int]:
    return [int(p) for p in json.loads(bytes(mime.data(PAGES_MIME)).decode())]


def _fit(pix: QPixmap, box: QRectF) -> QRectF:
    """`pix`'s rectangle scaled to fit in `box` (keeping its aspect), centered."""
    size = pix.deviceIndependentSize()
    k = min(box.width() / max(size.width(), 1), box.height() / max(size.height(), 1))
    r = QRectF(0, 0, size.width() * k, size.height() * k)
    r.moveCenter(box.center())
    return r




class OverviewStrip(QWidget):
    """The whole document as one row: a cell per page, colored by the part it belongs to.
    A page of the wrong color between two others is a page in the wrong part."""

    clicked = Signal(int)

    def __init__(self):
        super().__init__()
        self.setFixedHeight(30)
        self.setMouseTracking(True)
        self._cells: list[tuple[str, QColor]] = []

    def set_cells(self, cells: list[tuple[str, QColor]]) -> None:
        self._cells = cells
        self.update()

    def _page_at(self, x: float) -> int | None:
        if not self._cells:
            return None
        return min(max(int(x / max(self.width(), 1) * len(self._cells)), 0), len(self._cells) - 1)

    def paintEvent(self, _):
        if not self._cells:
            return
        p = QPainter(self)
        n, w = len(self._cells), self.width()
        for i, (_, color) in enumerate(self._cells):
            x0, x1 = round(i * w / n), round((i + 1) * w / n)
            p.fillRect(x0, 2, max(x1 - x0 - (1 if x1 - x0 > 3 else 0), 1), self.height() - 4, color)

    def mouseMoveEvent(self, ev):
        i = self._page_at(ev.position().x())
        if i is not None:
            QToolTip.showText(ev.globalPosition().toPoint(), f"Page {i + 1} — {self._cells[i][0]}", self)

    def mousePressEvent(self, ev):
        i = self._page_at(ev.position().x())
        if i is not None:
            self.clicked.emit(i)


class DragGhost(QWidget):
    """The pages being dragged, drawn under the cursor inside the window: a small fanned stack of thumbnails with a
    count badge that pops in, trails the cursor and tilts with its motion. (Compositors such as GNOME on Wayland do
    not show the drag pixmap of a QDrag, so the app draws its own.) It follows the drag events of every widget."""

    PAD = 26

    def __init__(self, window: QWidget, pixmaps: list[QPixmap], count: int, at: QPoint):
        super().__init__(window)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self._pix, self._count = pixmaps[:3], count
        self.resize(THUMB_W + 2 * self.PAD, THUMB_H + 2 * self.PAD)
        self._target = self._pos = QPointF(at)
        self._tilt = 0.0
        self._scale, self._opacity = 0.6, 0.0
        self._in = True                                 # False once released: shrink and fade out
        self._frame = QTimer(self, interval=16)
        self._frame.timeout.connect(self._step)
        self._away = QTimer(self, singleShot=True, interval=80)     # the cursor left the window
        self._away.timeout.connect(self.hide)
        self._place()
        self.show()
        self.raise_()
        self._frame.start()
        QApplication.instance().installEventFilter(self)

    def finish(self) -> None:
        QApplication.instance().removeEventFilter(self)
        self._in = False

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in (QEvent.DragEnter, QEvent.DragMove) and isinstance(obj, QWidget) and obj.window() is self.parent():
            self._away.stop()
            self._target = QPointF(obj.mapTo(self.parent(), ev.position().toPoint()))
            if not self.isVisible():
                self._pos = self._target
                self.show()
        elif t == QEvent.DragLeave:
            self._away.start()
        return False

    def _step(self) -> None:
        d = self._target - self._pos
        self._pos += d * 0.45
        self._tilt += (max(-14.0, min(14.0, d.x() * 0.5)) - self._tilt) * 0.25
        if self._in:
            self._scale += (1.0 - self._scale) * 0.3
            self._opacity += (1.0 - self._opacity) * 0.3
        else:
            self._scale += (0.5 - self._scale) * 0.3
            self._opacity -= 0.16
            if self._opacity <= 0:
                self._frame.stop()
                self.deleteLater()
                return
        self._place()
        self.update()

    def _place(self) -> None:
        self.move(round(self._pos.x() - self.width() / 2), round(self._pos.y() - self.PAD - THUMB_H * 0.3))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setOpacity(max(0.0, min(1.0, self._opacity)))
        p.translate(self.width() / 2, self.PAD + THUMB_H * 0.3)        # pivot at the cursor
        p.scale(self._scale, self._scale)
        p.rotate(self._tilt)
        card = QRectF(-THUMB_W / 2, -THUMB_H * 0.3, THUMB_W, THUMB_H)
        for i in reversed(range(min(self._count, 3))):
            p.save()
            p.rotate(i * 6)
            p.translate(i * 4, i * 2)
            for k in range(4):                          # soft shadow
                shade = QColor(0, 0, 0, 14)
                p.setPen(Qt.NoPen)
                p.setBrush(shade)
                p.drawRoundedRect(card.adjusted(-k + 2, -k + 4, k + 2, k + 5), 5 + k, 5 + k)
            p.setBrush(QColor("white"))
            p.setPen(QPen(QColor(0, 0, 0, 60), 1))
            p.drawRoundedRect(card, 4, 4)
            if i < len(self._pix):
                p.drawPixmap(_fit(self._pix[i], card), self._pix[i], QRectF(self._pix[i].rect()))
            p.restore()
        if self._count > 1:
            text = str(self._count)
            w = 22 if len(text) < 2 else 30
            badge = QRectF(card.right() - w / 2 - 2, card.top() - 9, w, 20)
            p.setPen(QPen(QColor("white"), 2))
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(badge, 10, 10)
            f = p.font()
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("white"))
            p.drawText(badge, Qt.AlignCenter, text)


class _ShiftDelegate(QStyledItemDelegate):
    """Draws each thumbnail at its animated preview position, hides the pages being moved within their own part
    and dims them in the part they are leaving."""

    def __init__(self, lst: "GroupList"):
        super().__init__(lst)
        self.lst = lst

    def paint(self, painter, option, index):
        row = index.row()
        if row in self.lst._hidden:
            return
        opt = QStyleOptionViewItem(option)
        off = self.lst._offsets.get(row)
        if off is not None:
            opt.rect = option.rect.translated(off.toPoint())
        dim = row in self.lst._own
        if dim:
            painter.save()
            painter.setOpacity(0.3)
        super().paint(painter, opt, index)
        if dim:
            painter.restore()


class GroupList(QListWidget):
    """The page thumbnails of one part. Selected pages are dragged as a list of page numbers and
    dropped onto any part; the target decides the position (the model is changed by the owner).
    While a drag hovers, the thumbnails slide apart to open a gap where the pages would land."""

    dropped = Signal(object, int)               # pages, insert row (-1: at the end)
    drag_state = Signal(bool)
    delete_requested = Signal()                 # Delete / Backspace pressed with pages selected
    hovered = Signal(bool)                      # a drag of pages is over this list
    menu_requested = Signal(object)

    drag: dict = {}                             # the drag in progress in this app: {"pages": [...], "pix": {page: QPixmap}}

    def __init__(self):
        super().__init__(objectName="thumbs")
        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setIconSize(QSize(THUMB_W, THUMB_H))
        self.setGridSize(QSize(CELL_W, CELL_H))
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)    # setMovement(Static) turned it off: real drags fell through to the card
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos: self.menu_requested.emit(pos))
        self.setItemDelegate(_ShiftDelegate(self))
        self._drop_index: int | None = None     # where the gap is, counted among the pages that stay
        self._gap = 0                           # pages in the gap
        self._own: set[int] = set()             # rows of this list being dragged
        self._hidden: set[int] = set()          # rows taken out of the layout (dragged within this list)
        self._offsets: dict[int, QPointF] = {}  # row -> current animated shift from its real cell
        self._targets: dict[int, QPointF] = {}
        self._gap_alpha = 0.0
        self._extra = 0                         # cells added to the height while a gap is open
        self._press = QPoint()
        self._slide = QTimer(self, interval=16)
        self._slide.timeout.connect(self._step)
        self._pulse = 1.0
        self._pulse_anim = QVariantAnimation(self)      # the gap's outline breathes while a drag hovers
        self._pulse_anim.setDuration(900)
        self._pulse_anim.setLoopCount(-1)
        for t, v in ((0.0, 0.45), (0.5, 1.0), (1.0, 0.45)):
            self._pulse_anim.setKeyValueAt(t, v)
        self._pulse_anim.valueChanged.connect(self._set_pulse)

    def _set_pulse(self, v) -> None:
        self._pulse = float(v)
        self.viewport().update()

    def _end_hover(self) -> None:
        self._show_gap(None)
        self._pulse_anim.stop()
        self.hovered.emit(False)

    def pages(self) -> list[int]:
        return [self.item(r).data(Qt.UserRole) for r in range(self.count())]

    def selected_pages(self) -> list[int]:
        return sorted(i.data(Qt.UserRole) for i in self.selectedItems())

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selectedItems():
            self.delete_requested.emit()
            return
        super().keyPressEvent(ev)

    # ---- height follows the number of wrapped rows (no inner scrolling)
    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        QTimer.singleShot(0, self.fit_height)

    def _cols(self) -> int:
        return max(1, self.viewport().width() // CELL_W)

    def fit_height(self, width: int | None = None) -> None:
        """`width`: the viewport width to plan for, before this list has been laid out (a rebuilt map)."""
        cols = max(1, width // CELL_W) if width else self._cols()
        h = -(-max(self.count() + self._extra, 1) // cols) * CELL_H + 6
        if h != self.height():
            self.setFixedHeight(h)

    # ---- drag source
    def mousePressEvent(self, ev):
        self._press = ev.position().toPoint()
        super().mousePressEvent(ev)

    def startDrag(self, actions):
        pages = self.selected_pages()
        if not pages:
            return
        mime = QMimeData()
        mime.setData(PAGES_MIME, json.dumps(pages).encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        blank = QPixmap(1, 1)                           # the ghost below is the drag image
        blank.fill(Qt.transparent)
        drag.setPixmap(blank)
        items = sorted(self.selectedItems(), key=self.row)
        pix = {it.data(Qt.UserRole): it.icon().pixmap(QSize(THUMB_W, THUMB_H)) for it in items}
        GroupList.drag = {"pages": pages, "pix": pix}
        self._own = {self.row(it) for it in items}
        self.viewport().update()
        ghost = DragGhost(self.window(), [pix[it.data(Qt.UserRole)] for it in items], len(pages),
                          self.viewport().mapTo(self.window(), self._press))
        self.drag_state.emit(True)
        try:
            drag.exec(Qt.MoveAction)
        finally:
            ghost.finish()
            GroupList.drag = {}
            self.drag_state.emit(False)
        try:
            self._own = set()
            self._show_gap(None)
        except RuntimeError:                            # the list was rebuilt by the drop
            pass

    # ---- drop target
    def _layout_rows(self, pages: list[int]) -> tuple[set[int], list[int]]:
        """(rows of this list being moved, rows that stay)."""
        moving = set(pages)
        own = {r for r in range(self.count()) if self.item(r).data(Qt.UserRole) in moving}
        return own, [r for r in range(self.count()) if r not in own]

    def _index_at(self, pos, stay: int) -> int:
        """The gap position under `pos`, among the `stay` pages that stay (laid out without the moved ones)."""
        col = min(max(pos.x(), 0) // CELL_W, self._cols() - 1)
        slot = max(pos.y(), 0) // CELL_H * self._cols() + col
        slot += 1 if pos.x() - col * CELL_W > CELL_W / 2 else 0
        return min(slot, stay)

    def _cell(self, slot: int) -> QPoint:
        return QPoint(slot % self._cols() * CELL_W, slot // self._cols() * CELL_H)

    def _show_gap(self, index: int | None, pages: list[int] = ()) -> None:
        """Open a gap of len(pages) cells at `index` (None: close it) and slide the thumbnails there."""
        own, stay = self._layout_rows(pages)
        if index is None:
            self._hidden, self._gap, self._targets = set(), 0, {}
        else:
            self._hidden, self._gap = own, len(pages)
            self._targets = {}
            for k, r in enumerate(stay):
                slot = k + (self._gap if k >= index else 0)
                self._targets[r] = QPointF(self._cell(slot) - self._cell(r))
            if index != self._drop_index:
                self._gap_alpha = 0.0
            extra = len(stay) + self._gap - self.count()
            if extra > self._extra:
                self._extra = extra
                self.fit_height()
        self._drop_index = index
        if not self._slide.isActive():
            self._slide.start()

    def _step(self) -> None:
        done = True
        for r in set(self._offsets) | set(self._targets):
            target = self._targets.get(r, QPointF())
            cur = self._offsets.get(r, QPointF())
            d = target - cur
            if abs(d.x()) + abs(d.y()) < 0.6:
                cur = target
            else:
                cur = cur + d * 0.3
                done = False
            if cur.isNull():
                self._offsets.pop(r, None)
            else:
                self._offsets[r] = cur
        want = 1.0 if self._drop_index is not None else 0.0
        self._gap_alpha += (want - self._gap_alpha) * 0.25
        if abs(want - self._gap_alpha) > 0.02:
            done = False
        self.viewport().update()
        if done:
            self._slide.stop()
            if self._drop_index is None and self._extra:
                self._extra = 0
                self.fit_height()

    def _drop_row(self, pos, pages: list[int]) -> int:
        """The row (in the full list, as the model counts it) of a drop at `pos`."""
        _, stay = self._layout_rows(pages)
        k = self._index_at(pos, len(stay))
        return stay[k] if k < len(stay) else self.count()

    def hover_at(self, pos, pages: list[int]) -> None:
        """Preview a drop at `pos` (None: at the end)."""
        _, stay = self._layout_rows(pages)
        self._show_gap(len(stay) if pos is None else self._index_at(pos, len(stay)), pages)
        if self._pulse_anim.state() != QVariantAnimation.Running:
            self._pulse_anim.start()

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasFormat(PAGES_MIME):
            ev.acceptProposedAction()
            self.hover_at(ev.position().toPoint(), _pages_from(ev.mimeData()))
            self.hovered.emit(True)

    def dragMoveEvent(self, ev):
        if ev.mimeData().hasFormat(PAGES_MIME):
            ev.acceptProposedAction()
            self.hover_at(ev.position().toPoint(), _pages_from(ev.mimeData()))
            self.hovered.emit(True)

    def dragLeaveEvent(self, ev):
        self._end_hover()

    def dropEvent(self, ev):
        if not ev.mimeData().hasFormat(PAGES_MIME):
            return
        pages = _pages_from(ev.mimeData())
        row = self._drop_row(ev.position().toPoint(), pages)
        self._pulse_anim.stop()                 # the preview stays as it is: the rebuilt map shows the same layout
        self.hovered.emit(False)
        ev.acceptProposedAction()
        self.dropped.emit(pages, row)

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if self._drop_index is None or self._gap_alpha < 0.02:
            return
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self._gap_alpha)
        pix = GroupList.drag.get("pix", {})
        pages = GroupList.drag.get("pages", [])
        line = QColor(ACCENT)
        line.setAlphaF(self._pulse)
        fill = QColor(ACCENT)
        fill.setAlphaF(0.10)
        for j in range(self._gap):
            o = self._cell(self._drop_index + j)
            r = QRectF(o.x() + (CELL_W - THUMB_W) / 2, o.y() + 4, THUMB_W, THUMB_H).adjusted(-3, -3, 3, 3)
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(r, 6, 6)
            if j < len(pages) and pages[j] in pix:
                p.save()
                p.setOpacity(self._gap_alpha * 0.45)
                p.drawPixmap(_fit(pix[pages[j]], r.adjusted(3, 3, -3, -3)), pix[pages[j]], QRectF(pix[pages[j]].rect()))
                p.restore()
            pen = QPen(line, 2)
            pen.setDashPattern([3.0, 2.5])
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 6, 6)


class GlowMixin:
    """The animated 'this is where the pages will go' look of a drop target: the border fades in and its
    dashes march while a drag hovers; `flash` lights the target up green after a drop."""

    def glow_init(self) -> None:
        self._glow = 0.0
        self._glow_color = QColor(ACCENT)
        self._dash = 0.0
        self._hovering = False
        self._fade = QVariantAnimation(self)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.valueChanged.connect(self._set_glow)
        self._march = QVariantAnimation(self)
        self._march.setStartValue(0.0)
        self._march.setEndValue(5.5)
        self._march.setDuration(450)
        self._march.setLoopCount(-1)
        self._march.valueChanged.connect(self._set_dash)
        # the cursor crossing from a child widget to its parent sends leave + enter: ride that out
        self._off = QTimer(self, singleShot=True, interval=70)
        self._off.timeout.connect(lambda: self.set_drop(False))

    def hover(self, on: bool) -> None:
        if on:
            self._off.stop()
            self.set_drop(True)
        else:
            self._off.start()

    def set_drop(self, on: bool) -> None:
        if on == self._hovering:
            return
        self._hovering = on
        self._glow_color = QColor(ACCENT)
        self._animate_glow(1.0 if on else 0.0, 180 if on else 140)
        self._march.start() if on else self._march.stop()
        self.on_drop_hover(on)

    def on_drop_hover(self, on: bool) -> None:
        pass

    def flash(self) -> None:
        self._hovering = False
        self._march.stop()
        self._glow, self._glow_color = 1.0, QColor(OK)
        self._animate_glow(0.0, 1000)

    def _animate_glow(self, end: float, ms: int) -> None:
        self._fade.stop()
        self._fade.setStartValue(self._glow)
        self._fade.setEndValue(end)
        self._fade.setDuration(ms)
        self._fade.start()

    def _set_glow(self, v) -> None:
        self._glow = float(v)
        self.update()

    def _set_dash(self, v) -> None:
        self._dash = float(v)
        self.update()

    def paint_glow(self) -> None:
        if self._glow <= 0.01:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        fill = QColor(self._glow_color)
        fill.setAlphaF(0.10 * self._glow)
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(r, 8, 8)
        line = QColor(self._glow_color)
        line.setAlphaF(self._glow)
        pen = QPen(line, 2.5)
        pen.setDashPattern([3.0, 2.5])
        pen.setDashOffset(self._dash)
        p.setBrush(Qt.NoBrush)
        p.setPen(pen)
        p.drawRoundedRect(r, 8, 8)


class GroupCard(GlowMixin, QFrame):
    """One part: color swatch, editable name, page count, and its page thumbnails."""

    renamed = Signal(str)
    header_clicked = Signal()
    dropped = Signal(object, int)
    collapsed_changed = Signal(bool)

    def __init__(self, name: str, color: QColor, editable: bool, warn: bool = False):
        super().__init__(objectName="group")
        self.setAcceptDrops(True)
        self.glow_init()
        # hovering a collapsed part with a drag for a moment opens it, so a position can be chosen
        self._spring = QTimer(self, singleShot=True, interval=650)
        self._spring.timeout.connect(lambda: self.is_collapsed() and self.set_collapsed(False))
        self.color = color
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(4)
        self.header = QWidget()
        h = QHBoxLayout(self.header)
        h.setContentsMargins(0, 0, 0, 0)
        self.toggle = QPushButton("▾", objectName="flat")
        self.toggle.setFixedWidth(26)
        self.toggle.setToolTip("Collapse / expand the pages of this part")
        self.toggle.clicked.connect(lambda: self.set_collapsed(self.list.isVisible()))
        h.addWidget(self.toggle)
        swatch = QFrame()
        swatch.setFixedSize(12, 12)
        swatch.setStyleSheet(f"background: {color.name()}; border-radius: 3px;")
        h.addWidget(swatch)
        self.name = QLineEdit(name, objectName="gname")
        self.name.setReadOnly(not editable)
        if warn:
            self.name.setStyleSheet(f"color: {WARN};")
            self.name.setToolTip("The instrument could not be read — double-click to name this part.")
        self.name.editingFinished.connect(lambda: self.renamed.emit(self.name.text().strip()))
        h.addWidget(self.name, 1)
        self.count = QLabel(objectName="muted")
        h.addWidget(self.count)
        lay.addWidget(self.header)
        self.list = GroupList()
        lay.addWidget(self.list)
        self.header.mousePressEvent = lambda ev: self.header_clicked.emit()
        self.list.hovered.connect(self.hover)

    def set_collapsed(self, on: bool) -> None:
        self.list.setVisible(not on)
        self.toggle.setText("▸" if on else "▾")
        self.collapsed_changed.emit(on)

    def on_drop_hover(self, on: bool) -> None:
        if on and self.is_collapsed():
            self._spring.start()
        elif not on:
            self._spring.stop()

    def paintEvent(self, ev):
        QFrame.paintEvent(self, ev)
        self.paint_glow()

    def is_collapsed(self) -> bool:
        return not self.list.isVisible()

    def set_active(self, on: bool) -> None:
        self.setProperty("active", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasFormat(PAGES_MIME):
            ev.acceptProposedAction()
            self.hover(True)
            if not self.is_collapsed():         # the header / margins append: show the gap at the end
                self.list.hover_at(None, _pages_from(ev.mimeData()))

    def dragMoveEvent(self, ev):
        if ev.mimeData().hasFormat(PAGES_MIME):
            ev.acceptProposedAction()

    def dragLeaveEvent(self, ev):
        self.hover(False)
        self.list._show_gap(None)
        self.list._pulse_anim.stop()

    def dropEvent(self, ev):                    # dropped on the header / margins: append
        if ev.mimeData().hasFormat(PAGES_MIME):
            ev.acceptProposedAction()
            self.set_drop(False)
            self.list._show_gap(None)
            self.dropped.emit(_pages_from(ev.mimeData()), -1)


class DropZone(GlowMixin, QLabel):
    """Dropping pages here makes a new part."""

    dropped = Signal(object)
    IDLE, ARMED = "Drop pages here to start a new part", "Release to start a new part"

    def __init__(self):
        super().__init__(self.IDLE, objectName="dropzone")
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.glow_init()

    def on_drop_hover(self, on: bool) -> None:
        self.setText(self.ARMED if on else self.IDLE)

    def paintEvent(self, ev):
        QLabel.paintEvent(self, ev)
        self.paint_glow()

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasFormat(PAGES_MIME):
            ev.acceptProposedAction()
            self.hover(True)

    def dragMoveEvent(self, ev):
        if ev.mimeData().hasFormat(PAGES_MIME):
            ev.acceptProposedAction()

    def dragLeaveEvent(self, ev):
        self.hover(False)

    def dropEvent(self, ev):
        if ev.mimeData().hasFormat(PAGES_MIME):
            ev.acceptProposedAction()
            self.set_drop(False)
            self.dropped.emit(_pages_from(ev.mimeData()))


class MapView(QWidget):
    """Every part as a card of page thumbnails, in document order, plus a strip with the whole
    document colored by part. Pages move between parts by drag & drop or the right-click menu."""

    move_requested = Signal(object, object, int)     # pages, target (Section | None | NEW_PART), row
    rename_requested = Signal(object, str)           # section, new name
    delete_requested = Signal(object)                # pages the user wants gone (Delete key / menu)
    picked = Signal(object, object)                  # section | None (unassigned) | range tuple, page | None

    def __init__(self, jobs: "Jobs"):
        super().__init__()
        self.thumbs = ThumbCache(jobs)
        self.thumbs.ready.connect(self._thumb_ready)
        self._placeholder = QPixmap(THUMB_W, THUMB_H)
        self._placeholder.fill(QColor("#e4e6ea"))
        self._cards: list[tuple[GroupCard, object]] = []        # (card, Section | None)
        self._items: dict[int, list[QListWidgetItem]] = {}
        self._owner: list[object] = []
        self._active: GroupCard | None = None
        self._collapsed: dict[int, bool] = {}           # id(section) -> collapsed (kept across rebuilds)
        self._page_card: dict[int, GroupCard] = {}
        self._flash_anim: QVariantAnimation | None = None
        self._hold: int | None = None                   # scroll position to keep while the rebuilt cards find their size
        self._reveal_next = False                       # the next move came from the menu: the target may be off-screen
        self._after_delete: tuple | None = None         # (section, row): select the page that moves up into the gap

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.strip = OverviewStrip()
        self.strip.clicked.connect(self.reveal_page)
        lay.addWidget(self.strip)
        self.hint = QLabel("Drag pages between parts. Ctrl / Shift-click selects several; Del removes pages (blank or unused); "
                           "right-click for more; Ctrl+Z undoes.",
                           objectName="muted")
        lay.addWidget(self.hint)
        self.area = QScrollArea(objectName="preview")
        self.area.setWidgetResizable(True)
        self.canvas = QWidget()
        self.vbox = QVBoxLayout(self.canvas)
        self.vbox.setContentsMargins(8, 8, 8, 8)
        self.vbox.setSpacing(8)
        self.area.setWidget(self.canvas)
        lay.addWidget(self.area, 1)

        self._scroll_timer = QTimer(self, interval=30)
        self._scroll_timer.timeout.connect(self._autoscroll)
        self._visible_timer = QTimer(self, singleShot=True, interval=120)
        self._visible_timer.timeout.connect(self._prioritize_visible)
        self.area.verticalScrollBar().valueChanged.connect(lambda _: self._visible_timer.start())
        self.area.verticalScrollBar().rangeChanged.connect(self._keep_scroll)
        self._release = QTimer(self, singleShot=True, interval=500)     # fires once the layout has been quiet this long
        self._release.timeout.connect(lambda: setattr(self, "_hold", None))

    # ---- data
    def _keep_scroll(self, _lo: int, hi: int) -> None:
        """The cards are rebuilt after every edit and the scroll range collapses and grows back while they are laid
        out: put the view back where the user was (until the layout has settled, or they scroll themselves)."""
        if self._hold is not None:
            self.area.verticalScrollBar().setValue(min(self._hold, hi))
            self._release.start()                       # still growing: keep holding until it has been quiet for a while

    def set_data(self, path: str, sections: list, npages: int, select=None, reveal: bool = False, deleted=()) -> None:
        sb = self.area.verticalScrollBar()
        if self._hold is None:
            self._hold = sb.value()                     # first rebuild of a burst: remember where we are
        self._release.start()
        self.thumbs.set_path(path)
        sections = sorted(sections, key=lambda s: (s.start, s.end))
        missing, _ = coverage(sections, npages)
        un_pages = [p for a, b in missing for p in range(a, b + 1) if p not in deleted]

        if self._flash_anim is not None:
            self._flash_anim.stop()
        # the rebuilt lists get their height now, not after their first layout (they would fold and unfold)
        width = next((c.list.viewport().width() for c, _ in self._cards if not c.is_collapsed()), None)
        self._cards, self._items, self._active, self._page_card = [], {}, None, {}
        self._owner = [("Not in any file", QColor(DANGER))] * npages
        while self.vbox.count():
            w = self.vbox.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()

        groups: list[tuple[object, str, QColor, list[int]]] = []
        if un_pages:
            groups.append((None, "Not in any file", QColor(DANGER), un_pages))
        for k, s in enumerate(sections):
            groups.append((s, s.name, QColor(PART_COLORS[k % len(PART_COLORS)]), s.page_list()))
        if deleted:
            groups.append((DELETE, "Deleted pages", QColor("#8a9099"), sorted(deleted)))
        for sec, name, color, pages in groups:
            for p in pages:
                if p < npages:
                    self._owner[p] = (name, color)
            card = GroupCard(name, color, editable=sec is not None and sec != DELETE,
                             warn=sec is not None and sec != DELETE and name.startswith("Part "))
            card.count.setText(f"{len(pages)} page{'s' if len(pages) != 1 else ''}")
            for p in pages:
                it = QListWidgetItem(QIcon(self.thumbs.pix.get(p, self._placeholder)), str(p + 1))
                it.setData(Qt.UserRole, p)
                it.setTextAlignment(Qt.AlignHCenter)
                card.list.addItem(it)
                self._items.setdefault(p, []).append(it)
                self._page_card[p] = card
            card.list.fit_height(width)
            card.list.itemSelectionChanged.connect(lambda c=card, s=sec: self._selection(c, s))
            card.list.dropped.connect(lambda pg, row, s=sec: self.move_requested.emit(pg, s, row))
            card.dropped.connect(lambda pg, row, s=sec: self.move_requested.emit(pg, s, row))
            if sec != DELETE:
                card.list.delete_requested.connect(lambda c=card, s=sec: self._delete_selected(c, s))
            card.list.drag_state.connect(self._drag_state)
            card.list.menu_requested.connect(lambda pos, c=card, s=sec: self._menu(c, s, pos))
            card.header_clicked.connect(lambda c=card, s=sec: self._header(c, s))
            card.renamed.connect(lambda text, s=sec: s is not None and self.rename_requested.emit(s, text))
            if getattr(sec, "is_score", False):
                f = card.name.font()
                f.setBold(True)
                card.name.setFont(f)
            if sec is not None:
                collapsed = self._collapsed.setdefault(id(sec), (sec.is_score and len(pages) > 24) if sec != DELETE else True)
                card.set_collapsed(collapsed)
                card.collapsed_changed.connect(lambda on, s=sec: self._collapsed.__setitem__(id(s), on))
            self.vbox.addWidget(card)
            self._cards.append((card, sec))
        self.zone = DropZone()
        self.zone.dropped.connect(lambda pg: self.move_requested.emit(pg, NEW_PART, -1))
        self.vbox.addWidget(self.zone)
        self.vbox.addStretch(1)
        self.vbox.activate()                            # place the new cards before anything is painted
        self.strip.set_cells(self._owner)
        self.thumbs.request(range(npages))
        self._visible_timer.start()
        if select is not None:
            self.select_section(select, reveal)
        if self._after_delete is not None:
            self._select_after_delete(*self._after_delete)
            self._after_delete = None
        QTimer.singleShot(0, lambda: sb.setValue(min(self._hold if self._hold is not None else sb.value(), sb.maximum())))

    def current_section(self):
        sec = next((s for c, s in self._cards if c is self._active), None)
        return None if sec == DELETE else sec

    # ---- deleting pages
    def _delete_selected(self, card: GroupCard, sec) -> None:
        """Del on the selected thumbnails: ask for those pages to be deleted, and plan to select the page that moves
        up into the gap, so that pressing Del again clears a run of blank pages."""
        rows = sorted(card.list.row(i) for i in card.list.selectedItems())
        pages = card.list.selected_pages()
        if pages:
            self._after_delete = (sec, rows[0])
            self.delete_requested.emit(pages)

    def _select_after_delete(self, sec, row: int) -> None:
        for card, s in self._cards:
            if s is sec and card.list.count():
                card.list.setCurrentRow(min(row, card.list.count() - 1))
                card.list.setFocus()
                return

    # ---- selection
    def _activate(self, card: GroupCard | None) -> None:
        if self._active is card:
            return
        if self._active is not None:
            try:
                self._active.set_active(False)
            except RuntimeError:                    # card was replaced
                pass
        self._active = card
        if card is not None:
            card.set_active(True)

    def _selection(self, card: GroupCard, sec) -> None:
        pages = card.list.selected_pages()
        if not pages:
            return
        for c, _ in self._cards:                    # one selection at a time
            if c is not card and c.list.selectedItems():
                c.list.blockSignals(True)
                c.list.clearSelection()
                c.list.blockSignals(False)
        self._activate(card)
        self.picked.emit(sec, pages[-1])

    def _header(self, card: GroupCard, sec) -> None:
        for c, _ in self._cards:
            c.list.blockSignals(True)
            c.list.clearSelection()
            c.list.blockSignals(False)
        self._activate(card)
        self.picked.emit(sec, None)

    def select_section(self, sec, reveal: bool = False) -> None:
        """Mark a part as the current one; scroll to it only when asked (never after an edit: the view stays put)."""
        for card, s in self._cards:
            if s is sec:
                self._activate(card)
                if reveal:
                    self._hold = None
                    QTimer.singleShot(0, lambda c=card: self.area.ensureWidgetVisible(c, 0, 40))
                return

    def edit_name(self, sec) -> None:
        for card, s in self._cards:
            if s is sec:
                card.name.setFocus()
                card.name.selectAll()

    def reveal_page(self, page: int) -> None:
        """Strip click: scroll to the page and select it."""
        for card, sec in self._cards:
            for r in range(card.list.count()):
                if card.list.item(r).data(Qt.UserRole) == page:
                    if card.is_collapsed():
                        card.set_collapsed(False)
                    card.list.clearSelection()
                    card.list.item(r).setSelected(True)
                    card.list.scrollToItem(card.list.item(r))
                    QTimer.singleShot(0, lambda c=card, ro=r: self._ensure(c, ro))
                    return

    def _show_if_hidden(self, card: GroupCard, item) -> None:
        """Scroll to a page only if it is not on screen: after a drop the view stays where the user is working."""
        try:
            if card.is_collapsed():
                return
            top = card.list.mapTo(self.canvas, card.list.visualItemRect(item).topLeft()).y()
        except RuntimeError:                            # the card was rebuilt meanwhile
            return
        sb = self.area.verticalScrollBar()
        if top < sb.value() or top + THUMB_H > sb.value() + self.area.viewport().height():
            self._ensure(card, card.list.row(item))

    def _ensure(self, card: GroupCard, row: int) -> None:
        rect = card.list.visualItemRect(card.list.item(row))
        top = card.list.mapTo(self.canvas, rect.topLeft()).y()
        self.area.verticalScrollBar().setValue(max(top - 80, 0))

    # ---- thumbnails
    def _thumb_ready(self, page: int) -> None:
        pix = self.thumbs.pix.get(page)
        for it in self._items.get(page, []):
            try:
                it.setIcon(QIcon(pix))
            except RuntimeError:
                pass

    def _prioritize_visible(self) -> None:
        top = self.area.verticalScrollBar().value()
        bottom = top + self.area.viewport().height()
        pages = []
        for card, _ in self._cards:
            if not card.is_collapsed() and card.y() + card.height() >= top and card.y() <= bottom:
                pages.extend(card.list.pages())
        self.thumbs.prioritize(pages)

    # ---- context menu
    def _menu(self, card: GroupCard, sec, pos) -> None:
        menu = self._build_menu(card, sec, pos)
        if menu is not None:
            menu.exec(card.list.viewport().mapToGlobal(pos))

    def _build_menu(self, card: GroupCard, sec, pos) -> QMenu | None:
        """The right-click menu of the pages under `pos` (built, not shown: tests inspect it)."""
        lst = card.list
        item = lst.itemAt(pos)
        if item is not None and not item.isSelected():
            lst.clearSelection()
            item.setSelected(True)
        pages = lst.selected_pages()
        if not pages:
            return None
        menu = QMenu(self)
        if sec != DELETE:
            menu.addAction(f"Delete {len(pages)} page{'s' if len(pages) != 1 else ''}\tDel", lambda: self._delete_selected(card, sec))
        move = menu.addMenu(f"{'Restore' if sec == DELETE else 'Move'} {len(pages)} page{'s' if len(pages) != 1 else ''} to")
        for c, s in self._cards:
            if s is not None and s != DELETE and s is not sec:
                move.addAction(c.name.text() or "(unnamed)", lambda s=s: self._menu_move(pages, s))
        move.addSeparator()
        move.addAction("New part", lambda: self._menu_move(pages, NEW_PART))
        if sec is not None and sec != DELETE:
            menu.addAction("Remove from this part (keep it as unassigned)", lambda: self.move_requested.emit(pages, None, -1))
        return menu

    def _menu_move(self, pages, target) -> None:
        self._reveal_next = True
        self.move_requested.emit(pages, target, -1)

    # ---- auto-scroll while dragging near the edge of the list
    def _drag_state(self, on: bool) -> None:
        if on:
            self._scroll_timer.start()
            return
        self._scroll_timer.stop()
        for target in [c for c, _ in self._cards] + [getattr(self, "zone", None)]:     # a cancelled drag
            try:
                target is not None and target.set_drop(False)
            except RuntimeError:
                pass

    def flash_pages(self, pages) -> None:
        """After a move: light up the target part, flash the moved thumbnails, scroll them into view."""
        pages = [p for p in pages if p in self._items]
        if not pages:
            return
        card = self._page_card.get(pages[0])
        if card is not None:
            self._activate(card)
            card.flash()
            first = self._items[pages[0]][0]
            if self._reveal_next:                       # a drop happens under the cursor: the view stays put
                self._reveal_next = False
                self._hold = None
                QTimer.singleShot(400, lambda: self._show_if_hidden(card, first))
        items = [it for p in pages for it in self._items[p]]
        anim = QVariantAnimation(self)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setDuration(1100)
        anim.setEasingCurve(QEasingCurve.OutQuad)

        def tick(v):
            try:
                brush = QBrush(QColor(46, 157, 87, int(170 * float(v)))) if v > 0.01 else QBrush()
                for it in items:
                    it.setBackground(brush)
            except RuntimeError:                    # the map was rebuilt meanwhile
                anim.stop()
        anim.valueChanged.connect(tick)
        self._flash_anim = anim
        anim.start()

    def _autoscroll(self) -> None:
        y = self.area.viewport().mapFromGlobal(QCursor.pos()).y()
        h, edge = self.area.viewport().height(), 48
        sb = self.area.verticalScrollBar()
        if 0 <= y < edge:
            sb.setValue(sb.value() - max(4, (edge - y) // 2))
        elif h - edge < y <= h:
            sb.setValue(sb.value() + max(4, (y - (h - edge)) // 2))
