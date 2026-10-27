"""RoboCommand schema 2026-10-23: UAV transit area, UAV declaration fields,
UAV registration and the moving object keep-out radius. Qt runs offscreen;
no broker."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["ROBOCOMMAND_MAP_TILES"] = "0"          # no satellite fetches from tests
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from PyQt5.QtWidgets import QAbstractSpinBox, QApplication, QLabel

import report
from fake_broker import FakeBroker
from robocommand_ui import commands
from robocommand_ui.course_presets import (
    BUILTIN_PRESETS, CoursePreset, load_user_presets, save_preset,
)
from robocommand_ui.course_validation import validate_course
from robocommand_ui.fleet_state import FleetState
from robocommand_ui.proto_helper import (
    common_pb2, rx_common_pb2, rx_reports_pb2, rx_requests_pb2,
)
from robocommand_ui.uav_geofence import geofence_problems, is_uav
from robocommand_ui.widgets.course_tab import BOUNDARY, TRANSIT, CourseTab
from robocommand_ui.widgets.form import LatLngField
from robocommand_ui.widgets.run_start_tab import RunStartTab
from robocommand_ui.widgets.task4_tab import Task4Tab

app = QApplication.instance() or QApplication(["-platform", "offscreen"])

TEAM = "ITSN"
# Upstream test server: Course Alpha and Garuda's Transit A, closed rings
ALPHA = [(1.2809652, 103.8548424), (1.2808457, 103.8550331), (1.2810752, 103.8551770),
         (1.2811947, 103.8549863), (1.2809652, 103.8548424)]
TRANSIT_A = [(1.281294119, 103.855048646), (1.281174598, 103.855239379),
             (1.2810752, 103.8551770), (1.2811947, 103.8549863), (1.281294119, 103.855048646)]
# Upstream test client's default geofence: Alpha plus Transit A
FENCE = [(1.2809652, 103.8548424), (1.2808457, 103.8550331), (1.2810752, 103.8551770),
         (1.281174598, 103.855239379), (1.281294119, 103.855048646), (1.2811947, 103.8549863),
         (1.2809652, 103.8548424)]


def latlngs(points):
    return [common_pb2.LatLng(latitude=a, longitude=b) for a, b in points]


def declaration(seq=1, vehicles=("USV1", "UAV1"), fence=FENCE, ceiling=40.0, callsign="Budi 123"):
    return rx_requests_pb2.RxRequest(
        team_id=TEAM, seq=seq,
        run_declaration=rx_requests_pb2.RunDeclaration(
            vehicle_ids=list(vehicles), uav_geofence=latlngs(fence),
            uav_geofence_max_altitude_hae_m=ceiling, uav_pilot_callsign=callsign))


def assert_ring(test, got, want):
    """Rings equal to the table's 7 decimals (~1 cm)."""
    test.assertEqual(len(got), len(want))
    for (a, b), (c, d) in zip(got, want):
        test.assertAlmostEqual(a, c, places=7)
        test.assertAlmostEqual(b, d, places=7)


def moved(points, index, dlat):
    out = list(points)
    out[index] = (out[index][0] + dlat, out[index][1])
    if index == 0:
        out[-1] = out[0]
    return out


class TestGeofenceCheck(unittest.TestCase):
    def test_upstream_default_geofence_is_accepted_with_the_transit_area(self):
        self.assertEqual(geofence_problems(FENCE, 40.0, ALPHA, TRANSIT_A), [])

    def test_geofence_into_transit_is_refused_without_a_transit_area(self):
        problems = geofence_problems(FENCE, 40.0, ALPHA)
        self.assertEqual(len(problems), 1)
        self.assertIn("leaves the course and transit area", problems[0])

    def test_point_outside_both_areas_is_refused_and_named(self):
        problems = geofence_problems(moved(FENCE, 2, -0.0002), 40.0, ALPHA, TRANSIT_A)
        self.assertEqual(len(problems), 1)
        self.assertIn("at point 3", problems[0])

    def test_within_tolerance_is_accepted(self):
        # ~0.5 m outside a boundary corner: rounding between surveys
        self.assertEqual(geofence_problems(moved(FENCE, 1, -0.0000045), 40.0, ALPHA, TRANSIT_A), [])

    def test_ceiling_must_be_above_zero_and_at_most_50(self):
        for ceiling in (0.0, -1.0, 50.1):
            problems = geofence_problems(FENCE, ceiling, ALPHA, TRANSIT_A)
            self.assertEqual(len(problems), 1, ceiling)
            self.assertIn("uav_geofence_max_altitude_hae_m", problems[0])
        self.assertEqual(geofence_problems(FENCE, 50.0, ALPHA, TRANSIT_A), [])

    def test_ring_shape(self):
        self.assertIn("needs at least 4", geofence_problems(FENCE[:3], 40.0, ALPHA)[0])
        self.assertIn("isn't closed", geofence_problems(FENCE[:-1], 40.0, ALPHA)[0])

    def test_without_a_course_only_shape_and_ceiling_are_checked(self):
        self.assertEqual(geofence_problems(FENCE, 40.0, []), [])

    def test_is_uav(self):
        self.assertTrue(is_uav("UAV1"))
        self.assertTrue(is_uav("uav2"))
        self.assertTrue(is_uav("DRONE", "UAV"))
        self.assertFalse(is_uav("USV1", "USV"))


class TestCourseTransit(unittest.TestCase):
    def course(self, transit):
        return commands.build_course("ALPHA", 25000, ALPHA, transit)

    def test_build_course_carries_the_transit_area(self):
        course = self.course(TRANSIT_A)
        self.assertEqual([(p.latitude, p.longitude) for p in course.uav_transit_area], TRANSIT_A)
        self.assertEqual(validate_course(course), [])

    def test_transit_area_is_optional(self):
        self.assertEqual(validate_course(self.course(())), [])

    def test_transit_area_must_be_closed_with_three_corners(self):
        self.assertIn("not a closed polygon", validate_course(self.course(TRANSIT_A[:-1]))[0])
        self.assertIn("only 3 point(s)", validate_course(self.course(TRANSIT_A[:3]))[0])

    def test_transit_point_range_is_checked(self):
        bad = [(91.0, 103.0)] + TRANSIT_A[1:-1] + [(91.0, 103.0)]
        self.assertIn("UAV transit point 1 out of range", validate_course(self.course(bad)))


class TestPresetTransit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "presets.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_transit_round_trips(self):
        save_preset(self.path, CoursePreset("SG", "ALPHA", 25000, tuple(ALPHA), tuple(TRANSIT_A)))
        self.assertEqual(load_user_presets(self.path)[0].transit, tuple(TRANSIT_A))

    def test_old_preset_files_load_without_a_transit_area(self):
        self.path.write_text(json.dumps({"presets": [
            {"name": "Old", "course_id": "ALPHA", "pinger_freq_hz": 25000,
             "corners": [list(c) for c in ALPHA]}]}))
        self.assertEqual(load_user_presets(self.path)[0].transit, ())

    def test_builtins_with_a_transit_area_are_valid(self):
        with_transit = [p for p in BUILTIN_PRESETS if p.transit]
        self.assertTrue(with_transit)
        for p in with_transit:
            course = commands.build_course(p.course_id, p.pinger_freq_hz, p.corners, p.transit)
            self.assertEqual(validate_course(course), [], p.name)


class TestCourseTabTransit(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.tab = CourseTab(Path(self.dir.name) / "presets.json")
        self.tab.resize(1400, 800)
        self.tab.map.resize(600, 400)

    def tearDown(self):
        self.tab.deleteLater()
        self.dir.cleanup()

    def test_transit_is_edited_on_the_map_with_the_boundary_as_backdrop(self):
        self.tab.set_fields("ALPHA", 25000, ALPHA)
        self.tab.set_editing(TRANSIT)
        self.assertEqual(self.tab.map.corners(), [])
        self.assertEqual(len(self.tab.map.backdrop()), len(ALPHA))
        self.tab._on_map_corners(TRANSIT_A[:-1])        # pins dropped on the map
        transit, error = self.tab.read_transit()
        self.assertEqual(error, "")
        assert_ring(self, transit, TRANSIT_A[:-1])
        corners, _ = self.tab.read_corners()
        self.assertEqual(corners, ALPHA[:-1])           # the boundary is untouched

        self.tab.set_editing(BOUNDARY)
        self.assertEqual(self.tab.map.corners(), ALPHA[:-1])
        self.assertEqual(len(self.tab.map.backdrop()), len(TRANSIT_A))

    def test_publish_carries_the_closed_transit_area(self):
        self.tab.set_fields("ALPHA", 25000, ALPHA, TRANSIT_A)
        sent = []
        self.tab.publish_requested.connect(sent.append)
        self.tab.publish_btn.click()
        self.assertEqual(len(sent), 1)
        assert_ring(self, [(p.latitude, p.longitude) for p in sent[0].uav_transit_area], TRANSIT_A)

    def test_a_two_point_transit_area_blocks_publish(self):
        self.tab.set_fields("ALPHA", 25000, ALPHA, TRANSIT_A[:2])
        self.assertFalse(self.tab.publish_btn.isEnabled())

    def test_editing_the_transit_area_marks_the_preset_modified(self):
        self.tab.select_preset("Course Alpha SG + Transit A")
        self.assertFalse(self.tab.update_preset_btn.isEnabled())
        self.tab.set_editing(TRANSIT)
        self.tab._clear_corners()
        self.assertTrue(self.tab.preset_state.text())
        self.assertEqual(self.tab.read_corners()[0], ALPHA[:-1])


class TestFleetDeclaration(unittest.TestCase):
    def setUp(self):
        self.fleet = FleetState()
        self.fleet.set_course(ALPHA, TRANSIT_A)

    def test_declaration_fields_are_kept(self):
        self.fleet.ingest_request(TEAM, declaration())
        team = self.fleet.teams[TEAM]
        self.assertEqual(team.geofence_ceiling_hae_m, 40.0)
        self.assertEqual(team.uav_pilot_callsign, "Budi 123")
        self.assertEqual(self.fleet.declaration_problems(TEAM), [])

    def test_refused_declaration_is_reported(self):
        self.fleet.ingest_request(TEAM, declaration(ceiling=0.0))
        self.assertEqual(len(self.fleet.declaration_problems(TEAM)), 1)

    def test_geofence_needs_the_transit_area(self):
        self.fleet.set_course(ALPHA)
        self.fleet.ingest_request(TEAM, declaration())
        self.assertIn("leaves the course", self.fleet.declaration_problems(TEAM)[0])

    def test_without_a_uav_nothing_is_checked(self):
        self.fleet.ingest_request(TEAM, declaration(vehicles=("USV1",), fence=(), ceiling=0.0))
        self.assertEqual(self.fleet.declaration_problems(TEAM), [])

    def test_no_course_blocks_a_uav_run(self):
        self.fleet.set_course([])
        self.fleet.ingest_request(TEAM, declaration())
        self.assertIn("no course published", self.fleet.declaration_problems(TEAM)[0])

    def test_run_start_tab_lists_the_problem_and_blocks_start(self):
        self.fleet.ingest_request(TEAM, declaration(vehicles=("UAV1",), ceiling=60.0))
        self.fleet.ingest_report(TEAM, "UAV1", rx_reports_pb2.RxReport(
            team_id=TEAM, vehicle_id="UAV1", seq=1, heartbeat=rx_reports_pb2.Heartbeat(
                state=common_pb2.STATE_AUTO, vehicle_type=rx_common_pb2.TYPE_UAV,
                position=common_pb2.LatLng(latitude=ALPHA[0][0], longitude=ALPHA[0][1]))))
        self.assertEqual(self.fleet.start_blockers(TEAM), [])
        with tempfile.TemporaryDirectory() as runs:
            tab = RunStartTab(Path(runs))
            tab.set_connected(True)
            tab.refresh(self.fleet)
            tab.select_team(TEAM)
            self.assertFalse(tab.start_btn.isEnabled())
            self.assertIn("RoboCommand would refuse", tab.detail.text())
            self.assertIn("Budi 123", tab.detail.text())
            self.assertEqual(tab.table.item(0, 4).text(), "1/1")    # vehicles are ready
            tab.deleteLater()


class TestMovingObjectRadius(unittest.TestCase):
    def test_command_default_and_explicit_radius(self):
        _, msg = commands.moving_object_alert((1.28, 103.85), 90.0, 1.5, ["USV"])
        self.assertAlmostEqual(msg.keep_out_radius_m, 5.0)
        _, msg = commands.moving_object_alert((1.28, 103.85), 90.0, 1.5, ["USV"], 12.5)
        self.assertAlmostEqual(msg.keep_out_radius_m, 12.5)

    def test_task4_tab_sends_the_radius(self):
        tab = Task4Tab()
        tab.team_combo.addItem(TEAM)
        sent = []
        tab.command_requested.connect(lambda team, body, summary: sent.append((body, summary)))
        tab.mo_radius.setValue(8.0)
        tab._send_moving()
        self.assertEqual(len(sent), 1)
        (name, msg), summary = sent[0]
        self.assertEqual(name, "moving_object_alert")
        self.assertAlmostEqual(msg.keep_out_radius_m, 8.0)
        self.assertIn("r=8.0 m", summary)
        tab.deleteLater()


class TestNineDecimals(unittest.TestCase):
    def test_position_field_keeps_nine_decimals(self):
        field = LatLngField()
        field.set_value(TRANSIT_A[0])
        self.assertEqual(field.value(), TRANSIT_A[0])
        field.deleteLater()

    def test_course_table_keeps_nine_decimals(self):
        with tempfile.TemporaryDirectory() as tmp:
            tab = CourseTab(Path(tmp) / "presets.json")
            tab.set_fields("ALPHA", 25000, ALPHA, TRANSIT_A)
            self.assertEqual(tab.read_transit()[0], TRANSIT_A[:-1])
            self.assertEqual(tab.transit.item(0, 0).text(), "1.281294119")
            tab.deleteLater()


class TestIncidentMap(unittest.TestCase):
    def setUp(self):
        self.tab = Task4Tab()
        self.tab.resize(1500, 900)
        self.tab.map.resize(700, 400)
        self.tab.set_course(ALPHA, ALPHA[0], commands.build_course("ALPHA", 25000, ALPHA, TRANSIT_A))

    def tearDown(self):
        self.tab.deleteLater()

    def declare(self, tier):
        self.tab._declared_tier = tier
        self.tab._sync_buttons()

    def test_every_tier_position_follows_the_map_centre(self):
        self.tab.map.center_changed.emit(*TRANSIT_A[1])
        for field in (self.tab.assist_pos, self.tab.koz_pos, self.tab.mo_pos):
            self.assertEqual(field.value(), TRANSIT_A[1])

    def test_typing_a_position_moves_the_map(self):
        self.tab.koz_pos.lat.setValue(1.2811)
        self.tab.koz_pos.lng.setValue(103.8551)
        lat, lng = self.tab.map.center_latlng()
        self.assertAlmostEqual(lat, 1.2811, places=8)
        self.assertAlmostEqual(lng, 103.8551, places=8)

    def test_the_declared_tier_is_previewed_active_with_its_radius(self):
        self.declare(common_pb2.TIER_ADVANCED)
        self.tab.koz_radius.setValue(22.0)
        active = [v for v in self.tab.map.previews() if v.active]
        self.assertEqual(len(self.tab.map.previews()), 3)       # the others faint
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].radius_m, 22.0)
        self.assertIn("KEEP-OUT 22 m", active[0].label)

    def test_other_tiers_stay_editable_but_cannot_send(self):
        self.tab.team_combo.addItem(TEAM)
        self.tab.set_connected(True)
        self.declare(common_pb2.TIER_ADVANCED)
        for panel in (self.tab.core, self.tab.advanced, self.tab.disruptive):
            self.assertTrue(panel.isEnabled())
        self.assertTrue(self.tab.mo_radius.isEnabled())
        sendable = {b.text(): b.isEnabled() for b, _ in self.tab._send_buttons}
        self.assertTrue(sendable["Send keep-out zone"])
        self.assertTrue(sendable["Send all clear"])
        self.assertFalse(sendable["Send moving object alert"])
        self.assertFalse(sendable["Send assistance request"])
        blocked = dict((b.text(), b.toolTip()) for b, _ in self.tab._send_buttons)
        self.assertIn("declared Task 4 tier", blocked["Send moving object alert"])

    def test_moving_object_preview_has_radius_heading_and_speed(self):
        self.declare(common_pb2.TIER_DISRUPTIVE)
        self.tab.mo_radius.setValue(7.5)
        self.tab.mo_heading.setValue(135.0)
        self.tab.mo_speed.setValue(2.0)
        (preview,) = [v for v in self.tab.map.previews() if v.active]
        self.assertEqual((preview.radius_m, preview.heading_deg, preview.speed_mps),
                         (7.5, 135.0, 2.0))

    def test_rings_alternate_only_when_on_the_same_line(self):
        self.declare(None)
        canvas = self.tab.map
        canvas.grab()                        # paints: the map has its projection

        def colors():
            rings = {v.label.split(" ")[0]: v for v in canvas.previews()}
            both = canvas.previews()
            return (canvas._ring_colors(rings["KEEP-OUT"], both),
                    canvas._ring_colors(rings["MOVING"], both),
                    rings["KEEP-OUT"].color, rings["MOVING"].color)

        self.tab.koz_radius.setValue(5.0)
        self.tab.mo_radius.setValue(5.0)     # same place, same radius: one line, a b a b
        koz, moving, red, yellow = colors()
        self.assertEqual((koz, moving), ([red, yellow], [yellow, red]))

        self.tab.koz_radius.setValue(12.0)   # same place, other radius: own colours
        koz, moving, red, yellow = colors()
        self.assertEqual((koz, moving), ([red], [yellow]))

        self.tab.koz_radius.setValue(5.0)    # same radius, ~5 m apart: own colours
        self.tab.mo_pos.set_value((self.tab.koz_pos.value()[0] + 0.000045,
                                   self.tab.koz_pos.value()[1]))
        self.tab._update_previews()
        koz, moving, red, yellow = colors()
        self.assertEqual((koz, moving), ([red], [yellow]))

    def test_without_a_declaration_every_tier_is_previewed(self):
        self.declare(None)
        self.assertTrue(all(v.active for v in self.tab.map.previews()))

    def test_map_draws_the_course_and_previews(self):
        self.declare(common_pb2.TIER_DISRUPTIVE)
        self.tab.map.grab()                  # paints: course, transit, preview, crosshair
        self.assertIsNotNone(self.tab.map.center_latlng())


class TestUnitsBesideNumbers(unittest.TestCase):
    """A unit inside a spin box gets typed over, pasted and copied with the number."""

    def spins(self, widget):
        return widget.findChildren(QAbstractSpinBox)

    def units(self, widget):
        return [w.text() for w in widget.findChildren(QLabel) if w.objectName() == "Unit"]

    def test_no_spin_box_has_a_unit_inside(self):
        with tempfile.TemporaryDirectory() as tmp:
            widgets = [Task4Tab(), CourseTab(Path(tmp) / "p.json"), RunStartTab(Path(tmp))]
            for widget in widgets:
                for spin in self.spins(widget):
                    self.assertEqual((spin.prefix(), spin.suffix()), ("", ""), spin.text())
                widget.deleteLater()

    def test_task4_units_are_labels_beside_the_numbers(self):
        tab = Task4Tab()
        self.assertEqual(sorted(self.units(tab)), sorted(["m", "°", "m/s", "m"]))
        tab.mo_speed.setValue(1.5)
        self.assertEqual(tab.mo_speed.text(), "1.50")
        tab.deleteLater()


class TestReporterUavFields(unittest.TestCase):
    def reporter(self, broker):
        vehicles = {"USV1": rx_common_pb2.TYPE_USV, "UAV1": rx_common_pb2.TYPE_UAV}
        tiers = (common_pb2.TIER_CORE,) + (common_pb2.TIER_NONE,) * 3
        r = report.GcsReporter("192.168.65.2", TEAM, vehicles, tiers, FENCE,
                               client_factory=broker.client, uav_ceiling_hae_m=35.0,
                               uav_pilot_callsign="Budi 123", uav_registration="53551")
        r._client.loop_start()
        return r

    def published(self, broker, suffix, cls):
        out = []
        for topic, payload in broker.published:
            if topic.endswith(suffix):
                msg = cls()
                msg.ParseFromString(payload)
                out.append(msg)
        return out

    def test_declaration_and_uav_heartbeat_carry_the_new_fields(self):
        broker = FakeBroker()
        r = self.reporter(broker)
        self.assertTrue(r.declare())
        decl = self.published(broker, f"{TEAM}/request", rx_requests_pb2.RxRequest)[-1]
        self.assertAlmostEqual(decl.run_declaration.uav_geofence_max_altitude_hae_m, 35.0)
        self.assertEqual(decl.run_declaration.uav_pilot_callsign, "Budi 123")

        for vid in ("USV1", "UAV1"):
            r.update(vid, lat=ALPHA[0][0], lng=ALPHA[0][1], state="AUTO")
            self.assertTrue(r.heartbeat(vid))
        uav = self.published(broker, f"{TEAM}/UAV1/report", rx_reports_pb2.RxReport)[-1]
        usv = self.published(broker, f"{TEAM}/USV1/report", rx_reports_pb2.RxReport)[-1]
        self.assertEqual(uav.heartbeat.uav_registration, "53551")
        self.assertEqual(usv.heartbeat.uav_registration, "")

    def test_cli_rejects_a_ceiling_above_50(self):
        fence = ";".join(f"{a},{b}" for a, b in FENCE)
        with self.assertRaises(SystemExit):
            report.main(["--host", "127.0.0.1", "--team", TEAM, "--vehicle", "UAV1",
                         "--geofence", fence, "--uav-ceiling", "60"])


if __name__ == "__main__":
    unittest.main()
