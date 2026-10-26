"""Smoke tests for the grouping map: real drag events are delivered to the widgets (offscreen)."""

import json
import time

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QVariantAnimation
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from sheetmusic.gui.groupmap import PAGES_MIME
from sheetmusic.gui.jobs import Jobs
from sheetmusic.gui.parts_tab import PartsTab
from sheetmusic.gui.theme import OK, apply_theme
from sheetmusic.parts import Section

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")      # Qt's synthetic event constructors


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


def wait(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


class Mime:
    """A QMimeData that outlives the events built from it (they only hold a pointer)."""
    def __init__(self, pages):
        self.data = QMimeData()
        self.data.setData(PAGES_MIME, json.dumps(pages).encode())


@pytest.fixture
def tab(app, numbered_pdf):
    tab = PartsTab(Jobs())
    tab.resize(1100, 800)
    tab.show()
    tab.input.setText(str(numbered_pdf))
    tab.npages = 12
    tab.sections = [Section(0, 3, "Flute 1"), Section(4, 7, "Oboe 1"), Section(8, 11, "Part 9-12")]
    tab.refresh(select=tab.sections[0])
    wait(app, 0.2)
    return tab


def card(tab, sec):
    return next(c for c, s in tab.map._cards if s is sec)


def drop(app, widget, pos, pages):
    m = Mime(pages)
    ev = QDropEvent(QPointF(pos), Qt.MoveAction, m.data, Qt.LeftButton, Qt.NoModifier)
    widget.dropEvent(ev)
    assert ev.isAccepted()
    wait(app, 0.3)


def test_map_shows_one_card_per_part_and_flags_unnamed_parts(tab):
    assert [c.name.text() for c, _ in tab.map._cards] == ["Flute 1", "Oboe 1", "Part 9-12"]
    assert all(c.list.count() == 4 for c, _ in tab.map._cards)
    assert tab.map.strip._cells[0][0] == "Flute 1" and tab.map.strip._cells[11][0] == "Part 9-12"


def test_drop_on_a_thumbnail_moves_the_page_there(app, tab):
    flute, oboe, _ = tab.sections
    lst = card(tab, flute).list
    drop(app, lst, lst.visualItemRect(lst.item(1)).center() - QPoint(20, 0), [7])      # left half of page 2
    assert flute.page_list() == [0, 7, 1, 2, 3] and oboe.page_list() == [4, 5, 6]


def test_drop_on_a_header_appends_and_drop_zone_makes_a_new_part(app, tab):
    flute, oboe, _ = tab.sections
    drop(app, card(tab, oboe), QPoint(30, 10), [0, 1])
    assert oboe.page_list() == [4, 5, 6, 7, 0, 1] and flute.page_list() == [2, 3]
    drop(app, tab.map.zone, QPoint(5, 5), [11])
    new = next(s for s in tab.sections if s.name == "New part")
    assert new.page_list() == [11]


def test_undo_restores_every_kind_of_edit(app, tab):
    flute, oboe, _ = tab.sections
    before = [(s.name, s.page_list()) for s in tab.sections]
    drop(app, card(tab, oboe), QPoint(30, 10), [0])
    tab.rename_section(oboe, "Oboe 2")
    wait(app, 0.2)
    tab.undo(); wait(app, 0.2)
    tab.undo(); wait(app, 0.2)
    assert [(s.name, s.page_list()) for s in tab.sections] == before
    assert tab.map.strip._cells[0][0] == "Flute 1"


def test_every_page_stays_in_exactly_one_part(app, tab):
    flute, oboe, last = tab.sections
    drop(app, card(tab, last), QPoint(30, 10), [0, 5])
    drop(app, card(tab, flute), QPoint(30, 10), [4, 6, 7])
    pages = sorted(p for s in tab.sections for p in s.page_list())
    assert pages == list(range(12))


def test_hovering_a_drag_lights_up_the_destination(app, tab):
    flute, oboe, _ = tab.sections
    c = card(tab, oboe)
    m = Mime([0])
    pos = c.list.visualItemRect(c.list.item(1)).center()
    c.list.dragEnterEvent(QDragEnterEvent(pos, Qt.MoveAction, m.data, Qt.LeftButton, Qt.NoModifier))
    c.list.dragMoveEvent(QDragMoveEvent(pos, Qt.MoveAction, m.data, Qt.LeftButton, Qt.NoModifier))
    wait(app, 0.4)
    assert c._glow > 0.95 and c._march.state() == QVariantAnimation.Running      # border + marching dashes
    assert c.list._pulse_anim.state() == QVariantAnimation.Running               # the insertion marker pulses
    assert card(tab, flute)._glow < 0.01                                          # only the destination lights up
    c.list.dragLeaveEvent(QDragLeaveEvent())
    wait(app, 0.5)
    assert c._glow < 0.02 and c._march.state() != QVariantAnimation.Running


def test_hovering_a_collapsed_part_opens_it(app, tab):
    c = card(tab, tab.sections[1])
    c.set_collapsed(True)
    m = Mime([0])
    c.dragEnterEvent(QDragEnterEvent(QPoint(20, 10), Qt.MoveAction, m.data, Qt.LeftButton, Qt.NoModifier))
    wait(app, 0.3)
    assert c.is_collapsed()
    wait(app, 0.6)
    assert not c.is_collapsed()


def test_a_drop_flashes_the_target_green(app, tab):
    flute, oboe, _ = tab.sections
    m = Mime([5])
    lst = card(tab, flute).list
    ev = QDropEvent(QPointF(lst.visualItemRect(lst.item(1)).center()), Qt.MoveAction, m.data, Qt.LeftButton, Qt.NoModifier)
    lst.dropEvent(ev)
    wait(app, 0.25)
    c = card(tab, flute)                                    # rebuilt after the move
    assert 5 in flute.page_list() and c._glow > 0.2 and c._glow_color.name() == OK.lower()
    wait(app, 1.4)
    assert c._glow < 0.02
