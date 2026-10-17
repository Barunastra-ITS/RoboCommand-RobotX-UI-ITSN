"""Course tab (presets, centre, Course ID, pinger), theme palettes and host
course detection. Qt runs offscreen; no broker."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["ROBOCOMMAND_MAP_TILES"] = "0"          # no satellite fetches from tests
sys.path.insert(0, ROOT)

from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QInputDialog, QLabel

from robocommand_ui import theme
from robocommand_ui.course_presets import BUILTIN_PRESETS, load_user_presets
from robocommand_ui.courses import COURSES, host_course
from robocommand_ui.widgets.boundary_map import BoundaryMap
from robocommand_ui.widgets.compass import compass_center
from robocommand_ui.widgets.course_map import MapCanvas
from robocommand_ui.widgets.course_tab import CourseTab

app = QApplication.instance() or QApplication(["-platform", "offscreen"])


class TestHostCourse(unittest.TestCase):
    def test_course_from_this_hosts_address(self):
        self.assertEqual(host_course("", [("enp12s0", "192.168.66.2")]).key, "bravo")
        self.assertEqual(host_course("", [("enp12s0", "192.168.70.2")]).key, "demo")
        self.assertIsNone(host_course("", [("wlan0", "10.0.0.7")]))

    def test_broker_address_wins(self):
        self.assertEqual(host_course("192.168.68.2", [("enp12s0", "192.168.65.2")]).key, "delta")


class TestThemePalettes(unittest.TestCase):
    def tearDown(self):
        theme.set_mode(theme.LIGHT)

    def test_light_is_the_default(self):
        self.assertEqual(theme.DEFAULT_MODE, theme.LIGHT)

    def test_both_palettes_have_the_same_tokens(self):
        self.assertEqual(set(theme.PALETTES[theme.LIGHT]), set(theme.PALETTES[theme.DARK]))

    def test_a_colour_means_one_thing_in_every_palette(self):
        """resolve() maps colours by value, so shared colours must be true aliases."""
        palettes = theme.PALETTES.values()
        for palette in palettes:
            for colour in set(palette.values()):
                names = {n for p in palettes for n, v in p.items() if v == colour}
                for other in palettes:
                    self.assertEqual(len({other[n] for n in names}), 1, (colour, names))

    def test_set_mode_swaps_tokens_and_resolve_maps_captured_colours(self):
        light_ok = theme.OK
        theme.set_mode(theme.DARK)
        self.assertEqual(theme.OK, theme.PALETTES[theme.DARK]["OK"])
        self.assertEqual(theme.resolve(light_ok), theme.OK)        # import-time table colour
        self.assertIn(theme.SOLID[theme.OK][0], theme.chip_style(light_ok))
        self.assertEqual(theme.resolve("#EF4444"), "#EF4444")      # not a token: unchanged
        with self.assertRaises(ValueError):
            theme.set_mode("sepia")

    def test_apply_restyles_inline_colours(self):
        label = QLabel("x")
        label.setStyleSheet(f"color: {theme.WARN};")
        theme.set_mode(theme.DARK)
        theme.apply(app)
        self.assertEqual(label.styleSheet(), f"color: {theme.PALETTES[theme.DARK]['WARN']};")
        theme.set_mode(theme.LIGHT)
        theme.apply(app)
        self.assertEqual(label.styleSheet(), f"color: {theme.PALETTES[theme.LIGHT]['WARN']};")


class TestCourseTab(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "presets.json"
        self.tab = CourseTab(self.path)
        self.tab.resize(1400, 800)
        self.tab.map.resize(600, 400)

    def tearDown(self):
        self.tab.deleteLater()
        self.dir.cleanup()

    def add(self, name):
        original = QInputDialog.getText
        QInputDialog.getText = staticmethod(lambda *a, **k: (name, True))
        try:
            self.tab.add_preset_btn.click()
        finally:
            QInputDialog.getText = original

    def test_presets_are_listed_and_the_first_is_loaded(self):
        first = BUILTIN_PRESETS[0]
        self.assertEqual(self.tab.preset_list.count(), len(BUILTIN_PRESETS))
        self.assertEqual(self.tab.selected_preset(), first.name)
        self.assertEqual(self.tab.corners.rowCount(), len(first.corners) - 1)

    def test_selecting_a_preset_fills_the_centre(self):
        second = BUILTIN_PRESETS[1]
        self.tab.select_preset(second.name)
        corners = second.corners[:-1]
        self.assertAlmostEqual(self.tab.center_lat.value(),
                               sum(c[0] for c in corners) / len(corners), places=4)
        self.assertAlmostEqual(self.tab.center_lng.value(),
                               sum(c[1] for c in corners) / len(corners), places=4)

    def test_centre_follows_the_map_when_panned(self):
        before = self.tab.center_lng.value()
        QTest.mousePress(self.tab.map, Qt.LeftButton, Qt.NoModifier, QPoint(300, 200))
        drag = QMouseEvent(QEvent.MouseMove, QPointF(200, 200), Qt.LeftButton, Qt.LeftButton,
                           Qt.NoModifier)
        QApplication.sendEvent(self.tab.map, drag)
        QTest.mouseRelease(self.tab.map, Qt.LeftButton, Qt.NoModifier, QPoint(200, 200))
        lat, lng = self.tab.map.center()
        self.assertGreater(self.tab.center_lng.value(), before)    # dragged left: view moved east
        self.assertAlmostEqual(self.tab.center_lng.value(), lng, places=6)
        self.assertAlmostEqual(self.tab.center_lat.value(), lat, places=6)
        self.assertEqual(self.tab.corners.rowCount(), len(BUILTIN_PRESETS[0].corners) - 1)

    def test_course_id_follows_the_course_this_host_serves(self):
        self.tab.set_rc_course(COURSES["charlie"])
        self.assertEqual(self.tab.course_id.text(), "CHARLIE")
        self.assertIn("Course Charlie", self.tab.rc_course_note.text())
        self.tab.select_preset(BUILTIN_PRESETS[1].name)            # preset says ALPHA
        self.assertEqual(self.tab.course_id.text(), "CHARLIE")
        self.assertFalse(self.tab.update_preset_btn.isEnabled())   # auto ID isn't an edit
        self.tab.set_rc_course(None)
        self.assertFalse(self.tab.rc_course_btn.isEnabled())

    def test_a_typed_course_id_is_kept_on_reconnect(self):
        self.tab.set_rc_course(COURSES["alpha"])
        self.tab.course_id.clear()
        QTest.keyClicks(self.tab.course_id, "TRIAL")                 # operator types
        self.tab.set_rc_course(COURSES["bravo"])
        self.assertEqual(self.tab.course_id.text(), "TRIAL")
        self.tab.rc_course_btn.click()                               # back to the auto ID
        self.tab.set_rc_course(COURSES["delta"])
        self.assertEqual(self.tab.course_id.text(), "DELTA")

    def test_pinger_is_a_plain_number_with_hz_beside_it(self):
        self.assertEqual(self.tab.pinger.suffix(), "")
        self.assertEqual(self.tab.pinger.text(), "25000")
        units = [w for w in self.tab.findChildren(QLabel) if w.objectName() == "Unit"]
        self.assertEqual([u.text() for u in units], ["Hz"])

    def test_add_asks_for_a_name_and_update_does_not(self):
        self.add("Lake bench")
        self.assertEqual(self.tab.selected_preset(), "Lake bench")
        self.assertFalse(self.tab.update_preset_btn.isEnabled())   # nothing changed yet
        self.tab.pinger.setValue(31000)
        self.assertTrue(self.tab.update_preset_btn.isEnabled())
        self.assertEqual(self.tab.preset_state.text(), "Unsaved changes")

        def no_dialog(*_a, **_k):
            raise AssertionError("Update must not ask for a name")
        original = QInputDialog.getText
        QInputDialog.getText = staticmethod(no_dialog)
        try:
            self.tab.update_preset_btn.click()
        finally:
            QInputDialog.getText = original
        saved = {p.name: p for p in load_user_presets(self.path)}
        self.assertEqual(list(saved), ["Lake bench"])
        self.assertEqual(saved["Lake bench"].pinger_freq_hz, 31000)
        self.assertFalse(self.tab.update_preset_btn.isEnabled())

    def test_delete_only_for_saved_presets(self):
        self.assertFalse(self.tab.delete_btn.isEnabled())          # built-in selected
        self.add("Scratch")
        self.assertTrue(self.tab.delete_btn.isEnabled())



def shift_drag(widget, start, end):
    QTest.mousePress(widget, Qt.LeftButton, Qt.ShiftModifier, start)
    QApplication.sendEvent(widget, QMouseEvent(QEvent.MouseMove, QPointF(end), Qt.LeftButton,
                                               Qt.LeftButton, Qt.ShiftModifier))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.ShiftModifier, end)


class TestMapRotation(unittest.TestCase):
    def test_boundary_map_shift_drag_turns_and_compass_resets(self):
        m = BoundaryMap()
        m.resize(600, 400)
        m.set_center(-7.2868, 112.7961)
        shift_drag(m, QPoint(500, 200), QPoint(300, 0))     # quarter turn around the centre
        self.assertAlmostEqual(m.bearing(), 90.0, places=3)
        self.assertEqual(m.corners(), [])                   # turning drops no pin
        point = m.to_latlng(QPointF(400, 120))
        back = m.to_px(*point)
        self.assertAlmostEqual(back.x(), 400, places=3)
        self.assertAlmostEqual(back.y(), 120, places=3)
        east = m.to_px(-7.2868, 112.7971)                   # east is up at bearing 90
        self.assertLess(east.y(), 200)
        self.assertAlmostEqual(east.x(), 300, delta=1)
        QTest.mouseClick(m, Qt.LeftButton, Qt.NoModifier, compass_center(600).toPoint())
        self.assertEqual(m.bearing(), 0.0)
        self.assertEqual(m.corners(), [])                   # the compass is not a pin

    def test_pin_lands_where_clicked_on_a_turned_map(self):
        m = BoundaryMap()
        m.resize(600, 400)
        m.set_center(-7.2868, 112.7961)
        m.set_bearing(30.0)
        QTest.mouseClick(m, Qt.LeftButton, Qt.NoModifier, QPoint(150, 300))
        q = m.to_px(*m.corners()[0])
        self.assertAlmostEqual(q.x(), 150, places=2)
        self.assertAlmostEqual(q.y(), 300, places=2)

    def test_course_map_turns_and_compass_resets(self):
        c = MapCanvas()
        c.resize(600, 400)
        c.set_course_points([(1.2803, 103.8556), (1.2805, 103.8554), (1.2809, 103.8557),
                             (1.2803, 103.8556)])
        c.grab()                                            # fits the view
        shift_drag(c, QPoint(500, 200), QPoint(300, 0))
        self.assertAlmostEqual(c.bearing(), 90.0, places=3)
        x, y = c._px_to_m(QPointF(120, 80))
        q = c._m_to_px(x, y)
        self.assertAlmostEqual(q.x(), 120, places=3)
        self.assertAlmostEqual(q.y(), 80, places=3)
        QTest.mouseClick(c, Qt.LeftButton, Qt.NoModifier, compass_center(600).toPoint())
        self.assertEqual(c.bearing(), 0.0)


if __name__ == "__main__":
    unittest.main()
