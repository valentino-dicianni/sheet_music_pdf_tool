"""Smoke tests for the grouping map: real drag events are delivered to the widgets (offscreen)."""

import json
from pathlib import Path
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


# ---------------------------------------------------------------- the view must stay where the user is working
@pytest.fixture
def long_tab(app, make_pdf):
    """Eight parts of 12 pages: far more than fits on screen, so the map scrolls."""
    pdf = make_pdf([(100 + i, 140) for i in range(96)])
    tab = PartsTab(Jobs())
    tab.resize(1100, 700)
    tab.show()
    tab.input.setText(str(pdf))
    tab.npages = 96
    tab.sections = [Section(12 * k, 12 * k + 11, f"Part {k + 1} name") for k in range(8)]
    tab.refresh(select=tab.sections[0])
    wait(app, 0.4)
    return tab


def scroll_to_card(app, tab, sec):
    card = card_of(tab, sec)
    tab.map.area.verticalScrollBar().setValue(card.y() - 20)
    wait(app, 0.3)
    return tab.map.area.verticalScrollBar().value()


def card_of(tab, sec):
    return next(c for c, s in tab.map._cards if s is sec)


def test_reordering_inside_a_part_keeps_the_view_where_it_was(app, long_tab):
    tab = long_tab
    sec = tab.sections[4]
    before = scroll_to_card(app, tab, sec)
    assert before > 300                                          # really scrolled down
    lst = card_of(tab, sec).list
    last = lst.visualItemRect(lst.item(lst.count() - 1))
    drop(app, lst, last.center() + QPoint(20, 0), [sec.page_list()[0]])      # first page to the end of its own part
    wait(app, 1.0)
    assert sec.page_list()[-1] == 48                             # it did move
    assert abs(tab.map.area.verticalScrollBar().value() - before) <= 2, "the view jumped after the drop"


def test_moving_a_page_to_another_part_keeps_the_view_where_it_was(app, long_tab):
    tab = long_tab
    src, dst = tab.sections[3], tab.sections[4]
    before = scroll_to_card(app, tab, dst)
    lst = card_of(tab, dst).list
    drop(app, lst, lst.visualItemRect(lst.item(2)).center(), [src.page_list()[0]])
    wait(app, 1.0)
    assert abs(tab.map.area.verticalScrollBar().value() - before) <= 14   # one thumbnail row may have appeared above


# ---------------------------------------------------------------- deleting pages (blank / unused)
from PySide6.QtTest import QTest

from sheetmusic.parts import DELETE


def deleted_card(tab):
    return next((c for c, s in tab.map._cards if s == DELETE), None)


def select_pages(tab, sec, rows):
    lst = card_of(tab, sec).list
    lst.clearSelection()
    for r in rows:
        lst.item(r).setSelected(True)
    lst.setFocus()
    return lst


def test_delete_key_removes_the_selected_pages_into_a_deleted_card(app, tab):
    flute, oboe, last = tab.sections
    lst = select_pages(tab, flute, [1, 2])
    QTest.keyClick(lst, Qt.Key_Delete)
    wait(app, 0.4)
    assert flute.page_list() == [0, 3] and tab.deleted == {1, 2}
    card = deleted_card(tab)
    assert card is not None and card.list.pages() == [1, 2] and card.is_collapsed()      # out of the way, but there
    assert "2 deleted" in tab.cover.text() and "Missing" not in tab.cover.text()          # no nagging about "missing pages"
    assert tab.map.strip._cells[1][0] == "Deleted pages"


def test_deleted_pages_are_not_exported_and_not_reported_missing(app, tab, tmp_path):
    from sheetmusic.parts import export_sections, unassigned_pages
    flute = tab.sections[0]
    QTest.keyClick(select_pages(tab, flute, [0]), Qt.Key_Delete)
    wait(app, 0.4)
    assert unassigned_pages(tab.sections, tab.npages, tab.deleted) == []
    files = export_sections(Path(tab.input.text()), tab.sections, "T", tmp_path)
    import pypdfium2 as pdfium
    assert sum(len(pdfium.PdfDocument(str(f))) for f in files) == 11                       # 12 pages minus the deleted one


def test_pressing_delete_again_clears_a_run_of_blank_pages_one_after_the_other(app, tab):
    flute = tab.sections[0]
    QTest.keyClick(select_pages(tab, flute, [0]), Qt.Key_Delete)
    wait(app, 0.4)
    focused = card_of(tab, flute).list
    assert focused.selected_pages() == [1]                                                  # the page that moved up is selected
    QTest.keyClick(focused, Qt.Key_Delete)
    wait(app, 0.4)
    QTest.keyClick(card_of(tab, flute).list, Qt.Key_Delete)
    wait(app, 0.4)
    assert tab.deleted == {0, 1, 2} and flute.page_list() == [3]


def test_ctrl_z_brings_deleted_pages_back_where_they_were(app, tab):
    flute = tab.sections[0]
    QTest.keyClick(select_pages(tab, flute, [1, 2]), Qt.Key_Delete)
    wait(app, 0.4)
    tab.undo()
    wait(app, 0.4)
    assert flute.page_list() == [0, 1, 2, 3] and tab.deleted == set() and deleted_card(tab) is None


def test_a_deleted_page_can_be_dragged_back_into_a_part(app, tab):
    flute, oboe, _ = tab.sections
    QTest.keyClick(select_pages(tab, flute, [1]), Qt.Key_Delete)
    wait(app, 0.4)
    card = deleted_card(tab)
    card.set_collapsed(False)
    wait(app, 0.2)
    lst = card_of(tab, oboe).list
    drop(app, lst, lst.visualItemRect(lst.item(0)).center() - QPoint(20, 0), [1])
    assert oboe.page_list()[0] == 1 and tab.deleted == set()


def test_dropping_pages_on_the_deleted_card_deletes_them(app, tab):
    flute, oboe, last = tab.sections
    QTest.keyClick(select_pages(tab, oboe, [0]), Qt.Key_Delete)           # make the card exist first
    wait(app, 0.4)
    drop(app, deleted_card(tab), QPoint(30, 10), [8])
    assert tab.deleted == {4, 8} and 8 not in last.page_list()


def menu_texts(menu):
    texts = [a.text() for a in menu.actions()]
    for a in menu.actions():
        if a.menu():
            texts += [x.text() for x in a.menu().actions()]
    return texts


def test_the_right_click_menu_offers_delete_and_the_deleted_card_offers_restore(app, tab):
    flute = tab.sections[0]
    lst = select_pages(tab, flute, [1])
    pos = lst.visualItemRect(lst.item(1)).center()
    texts = menu_texts(tab.map._build_menu(card_of(tab, flute), flute, pos))
    assert any(t.startswith("Delete 1 page") for t in texts)
    assert any(t.startswith("Move 1 page to") for t in texts)

    # Delete through the menu action, then look at the menu of the deleted card
    next(a for a in tab.map._build_menu(card_of(tab, flute), flute, pos).actions() if a.text().startswith("Delete")).trigger()
    wait(app, 0.4)
    card = deleted_card(tab)
    card.set_collapsed(False)
    wait(app, 0.2)
    card.list.item(0).setSelected(True)
    texts = menu_texts(tab.map._build_menu(card, DELETE, card.list.visualItemRect(card.list.item(0)).center()))
    assert not any(t.startswith("Delete") for t in texts) and any(t.startswith("Restore 1 page") for t in texts)


def test_deleting_keeps_the_view_where_it_was(app, long_tab):
    tab = long_tab
    sec = tab.sections[5]
    before = scroll_to_card(app, tab, sec)
    QTest.keyClick(select_pages(tab, sec, [3]), Qt.Key_Delete)
    wait(app, 1.0)
    assert 5 * 12 + 3 in tab.deleted
    assert abs(tab.map.area.verticalScrollBar().value() - before) <= 2, "the view jumped after deleting"
