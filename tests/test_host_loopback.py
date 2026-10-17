"""End-to-end: report.py (GCS) -> broker -> host monitor UI, in one process.

Uses tests/fake_broker.py so it runs without mosquitto. The reporter and the
host UI run their real code paths: the reporter's heartbeat thread publishes at
2 Hz, the host MqttWorker decodes on that thread and signals the Qt UI.
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["ROBOCOMMAND_MAP_TILES"] = "0"          # no satellite fetches from tests
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from PyQt5.QtCore import QPointF
from PyQt5.QtWidgets import QApplication, QLabel, QPushButton

from fake_broker import FakeBroker
from report import GcsReporter
from robocommand_ui.proto_helper import (
    common_pb2, now_ts, rx_commands_pb2, rx_common_pb2, rx_course_pb2, rx_reports_pb2,
)

TEAM = "ITSN"
TOPIC_ROOT = "robocommand/robotx"
CORNERS = [(1.280329, 103.8556869), (1.2804716, 103.8554529), (1.2808993, 103.8557337),
           (1.2807567, 103.8559743), (1.280329, 103.8556869)]

app = QApplication.instance() or QApplication(["-platform", "offscreen"])


def drain(seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


class TestHostLoopback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from robocommand_ui.main_window import MainWindow
        cls.broker = FakeBroker()
        # RoboCommand publishes the retained course
        course = rx_course_pb2.RxCourse(
            course_id="ALPHA", pinger_freq_hz=25000, sent_at=now_ts(),
            corners=[common_pb2.LatLng(latitude=a, longitude=b) for a, b in CORNERS])
        cls.broker.publish(f"{TOPIC_ROOT}/course", course.SerializeToString(), retain=True)

        # Host console listens to everything and publishes through the same broker
        cls.presets_dir = tempfile.TemporaryDirectory()
        cls.run_dir = Path(cls.presets_dir.name) / "runs"
        from PyQt5.QtCore import QSettings
        cls.settings = QSettings(str(Path(cls.presets_dir.name) / "console.ini"), QSettings.IniFormat)
        cls.win = MainWindow(presets_path=Path(cls.presets_dir.name) / "presets.json",
                             run_log_dir=cls.run_dir, settings=cls.settings)
        cls.broker.subscribe(f"{TOPIC_ROOT}/#", lambda m: cls.win.mqtt._on_message(None, None, m))
        cls.host_published = []

        def host_publish(topic, payload, retain):
            cls.host_published.append(topic)
            cls.broker.publish(topic, payload, retain=retain)
            return None
        cls.win.mqtt.publish = host_publish
        cls.win._set_tabs_connected(True)

        # GCS reporter on the team side
        cls.reporter = GcsReporter(
            "192.168.65.2", TEAM,
            {"USV1": rx_common_pb2.TYPE_USV, "UAV1": rx_common_pb2.TYPE_UAV},
            (common_pb2.TIER_CORE, common_pb2.TIER_NONE, common_pb2.TIER_NONE, common_pb2.TIER_CORE),
            CORNERS, client_factory=cls.broker.client)
        cls.reporter.start()

        # Boats move north for 2.5 s while heartbeats go out at 2 Hz
        t0 = time.time()
        while time.time() - t0 < 2.5:
            dt = time.time() - t0
            cls.reporter.update("USV1", lat=1.2805 + dt * 1e-5, lng=103.8557, heading_deg=0,
                                spd_mps=1.1, state="AUTO")
            cls.reporter.update("UAV1", lat=1.2806, lng=103.8556 + dt * 1e-5, heading_deg=90,
                                altitude_hae_m=20, state="AUTO", flight_phase="AIRBORNE")
            drain(0.1)
        drain(0.3)
        cls.win.refresh_views()

    @classmethod
    def tearDownClass(cls):
        cls.reporter.stop()
        cls.win.close()
        cls.presets_dir.cleanup()

    def log_text(self):
        return "\n".join(self.win.log_panel._all_messages)

    def test_1_course_shown(self):
        self.assertEqual(len(self.win.course_map._canvas._course_points), 5)
        self.assertIn("ALPHA", self.win.course_id_label.text())

    def test_2_team_declared_and_listed(self):
        row = self.win.teams_panel.row_text(TEAM)
        self.assertIsNotNone(row)
        self.assertEqual(row[1], "DECLARED")
        self.assertEqual(row[2], "2/2")
        self.assertEqual([self.win.team_filter.itemText(i) for i in range(self.win.team_filter.count())],
                         ["All teams", TEAM])

    def test_2b_course_tab_republishes_retained_course(self):
        tab = self.win.course_tab
        declared = self.reporter.declaration_seq
        tab.set_fields("ALPHA", 25000, CORNERS[:-1])        # open ring: closed on publish
        self.assertTrue(tab.publish_btn.isEnabled())
        tab.publish_btn.click()
        drain(0.2)
        course = rx_course_pb2.RxCourse.FromString(self.broker._retained[f"{TOPIC_ROOT}/course"])
        self.assertEqual(len(course.corners), 5)
        self.assertIn("VALID", tab.broker_summary.text())
        self.assertEqual(self.reporter.declaration_seq, declared)     # GCS did not re-declare
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(course.sent_at.seconds))
        self.assertIn(f"Last published {stamp}", tab.last_published.text())
        self.assertIn("ALPHA", tab.last_published.text())
        self.assertIn(f"published {stamp}", tab.broker_summary.text())

    def test_2b2_pinning_corners_on_the_map_fills_the_table(self):
        from PyQt5.QtCore import QPoint, Qt
        from PyQt5.QtTest import QTest
        tab = self.win.course_tab
        saved = tab.read_corners()[0]
        tab.map.resize(600, 400)
        tab.center_lat.setValue(-7.263)
        tab.center_lng.setValue(112.793)
        tab._go_to_center()
        tab._clear_corners()
        self.assertEqual(tab.corners.rowCount(), 0)
        clicks = [QPoint(150, 100), QPoint(450, 100), QPoint(450, 300), QPoint(150, 300)]
        for pt in clicks:
            QTest.mouseClick(tab.map, Qt.LeftButton, Qt.NoModifier, pt)
        corners, error = tab.read_corners()
        self.assertEqual(error, "")
        self.assertEqual(len(corners), 4)
        lat, lng = tab.map.to_latlng(QPointF(150, 100))
        self.assertAlmostEqual(corners[0][0], lat, places=6)
        self.assertAlmostEqual(corners[0][1], lng, places=6)
        self.assertGreater(corners[0][0], corners[3][0])          # first pin is north
        self.assertIn("VALID", tab.validity.text())

        QTest.mouseClick(tab.map, Qt.RightButton, Qt.NoModifier, clicks[2])   # delete pin 3
        self.assertEqual(tab.corners.rowCount(), 3)
        tab.corners.item(0, 0).setText("-7.2620000")               # table edit moves the pin
        self.assertAlmostEqual(tab.map.corners()[0][0], -7.262)
        tab.set_fields("ALPHA", 25000, saved)                       # leave it as found

    def test_2c_run_start_tab_lists_the_declared_team(self):
        tab = self.win.run_start_tab
        self.assertEqual(tab.table.item(0, 0).text(), TEAM)
        self.assertEqual(tab.table.item(0, 1).text(), "DECLARED")
        self.assertEqual(tab.table.item(0, 2).text(), str(self.reporter.declaration_seq))
        self.assertEqual(tab.selected_team(), TEAM)         # the waiting team is preselected
        self.assertTrue(tab.start_btn.isEnabled())

    def test_2d_start_needs_every_declared_vehicle_live_and_auto(self):
        tab = self.win.run_start_tab
        self.reporter.update("USV1", lat=1.2806, lng=103.8557, heading_deg=0, state="MANUAL")
        drain(0.8)
        self.win.refresh_views()
        tab.select_team(TEAM)
        self.assertFalse(tab.start_btn.isEnabled())
        self.assertIn("USV1 MANUAL (needs AUTO)", tab.detail.text())
        self.assertEqual(tab.table.item(0, 4).text(), "1/2")
        self.reporter.update("USV1", lat=1.2806, lng=103.8557, heading_deg=0, state="AUTO")
        drain(0.8)
        self.win.refresh_views()
        self.assertTrue(tab.start_btn.isEnabled())
        self.assertEqual(tab.table.item(0, 4).text(), "2/2")

    def test_3_boat_movement_is_tracked(self):
        usv = self.win.fleet.vehicles[(TEAM, "USV1")]
        self.assertGreaterEqual(len(usv.trail), 4)
        self.assertGreater(usv.trail[-1][0], usv.trail[0][0])         # moved north
        self.assertAlmostEqual(usv.rate_hz(time.time()), 2.0, delta=0.5)
        self.assertEqual(usv.seq_missed + usv.seq_out_of_order, 0)
        canvas = self.win.course_map._canvas
        self.assertEqual(sorted(canvas._vehicles), [f"{TEAM}/UAV1", f"{TEAM}/USV1"])
        self.assertEqual(self.win.course_map._canvas._geofence_points, CORNERS)

    def test_4_vehicle_card(self):
        card = self.win.vehicle_monitor.card(TEAM, "UAV1")
        self.assertIsNotNone(card)
        self.assertEqual(card.status_label.text(), "ACTIVE")
        self.assertEqual(card._values["State"].text(), "AUTO")
        self.assertEqual(card._values["Flight"].text(), "AIRBORNE")
        self.assertIn("Hz", card.rate.value.text())

    def test_4b_allow_start_from_console(self):
        tab = self.win.run_start_tab
        usv = self.win.fleet.vehicles[(TEAM, "USV1")]
        before = len(usv.trail)
        tab.run_id.setValue(7)
        tab.start_btn.click()
        drain(0.3)
        self.win.refresh_views()
        self.assertLess(len(usv.trail), before)              # the new run starts with a clean map
        self.assertIn("[RUN START] ITSN run 7: map trails", self.log_text())
        self.assertEqual(self.reporter.run_id, 7)
        self.assertEqual(self.win.teams_panel.row_text(TEAM)[1], "ACTIVE")
        self.assertEqual(tab.start_btn.text(), "Restart run")

    def test_5_run_start_seen_by_both_sides(self):
        cmd = rx_commands_pb2.RxCommand(team_id=TEAM, seq=1, sent_at=now_ts(),
                                        run_start=rx_commands_pb2.RunStart(
                                            declaration_seq=self.reporter.declaration_seq, run_id=42))
        self.broker.publish(f"{TOPIC_ROOT}/{TEAM}/command", cmd.SerializeToString())
        drain(0.3)
        self.win.refresh_views()
        self.assertEqual(self.reporter.run_id, 42)
        row = self.win.teams_panel.row_text(TEAM)
        self.assertEqual((row[1], row[4]), ("ACTIVE", "42"))

    def test_6_task_report_drawn_on_map(self):
        sp = rx_reports_pb2.SafePassageReport(
            entry_position=common_pb2.LatLng(latitude=1.2805, longitude=103.8556),
            exit_position=common_pb2.LatLng(latitude=1.2807, longitude=103.8558),
            buoys=[rx_reports_pb2.BuoyDetection(
                position=common_pb2.LatLng(latitude=1.2806, longitude=103.8557),
                state=rx_common_pb2.BEACON_STATE_FLASHING_GREEN)])
        self.assertTrue(self.reporter.publish_report("USV1", "safe_passage", sp))
        drain(0.3)
        self.win.refresh_views()
        self.assertEqual(len(self.win.course_map._canvas._sp_buoys), 1)
        self.assertIn("safe_passage", self.log_text())

    def test_6b_task4_assistance_ack_readiness_confirm(self):
        tab = self.win.task4_tab
        self.assertEqual(tab.selected_team(), TEAM)
        # Task 4 declared CORE: only the Core panel can send
        self.assertEqual(tab.core.meta_label.text(), "declared")
        self.assertTrue(tab.core.isEnabled())
        self.assertFalse(tab.advanced.isEnabled())
        self.assertFalse(tab.disruptive.isEnabled())
        self.assertIn("CORE", tab.advanced.meta_label.text())
        sent_before = len(self.win.incidents.entries(TEAM))
        self._click(tab, "Send keep-out zone")                          # disabled: nothing sent
        self.assertEqual(len(self.win.incidents.entries(TEAM)), sent_before)
        tab.assist_type.setCurrentText("USV")
        tab.assist_pos.set_value((1.2806, 103.8557))
        self._click(tab, "Send assistance request")
        drain(0.2)
        entry = self.win.incidents.entries(TEAM)[0]
        self.assertEqual((entry.kind, entry.status), ("assistance_request", "WAITING ACK"))
        self.assertGreater(entry.seq, 1)                                  # after the RunStarts

        ack = rx_reports_pb2.IncidentAck(command_seq=entry.seq)
        self.assertTrue(self.reporter.publish_report("USV1", "incident_ack", ack))
        ready = rx_reports_pb2.ReadinessReport(command_seq=entry.seq)
        self.assertTrue(self.reporter.publish_report("USV1", "readiness", ready))
        drain(0.3)
        self.win.refresh_views()
        self.assertTrue(entry.status.startswith("READY USV1"), entry.status)
        report_seq = entry.readiness[1]
        self.assertEqual(tab.confirm_vehicle.currentText(), "USV1")
        self.assertEqual(tab.confirm_seq.value(), report_seq)

        self._click(tab, "Send readiness confirm")
        drain(0.2)
        self.assertEqual(entry.status, "CONFIRMED")
        sent = rx_commands_pb2.RxCommand.FromString(
            [pl for t, pl in self.broker.published if t == f"{TOPIC_ROOT}/{TEAM}/command"][-1])
        self.assertEqual(sent.readiness_confirm.report_seq, report_seq)
        self.assertEqual(sent.seq, entry.seq + 1)
        self.assertEqual(tab.history.item(0, 4).text(), "SENT")          # newest: the confirm

    @staticmethod
    def _click(tab, text):
        from PyQt5.QtWidgets import QPushButton
        [btn] = [b for b in tab.findChildren(QPushButton) if b.text() == text]
        btn.click()

    def test_7_bad_traffic_is_rejected_without_crashing(self):
        self.broker.publish(f"{TOPIC_ROOT}/{TEAM}/USV1/report", b"\xff\xff\xff")
        spoof = rx_reports_pb2.RxReport(team_id="OTHER", vehicle_id="USV1", seq=1,
                                        heartbeat=rx_reports_pb2.Heartbeat())
        self.broker.publish(f"{TOPIC_ROOT}/{TEAM}/USV1/report", spoof.SerializeToString())
        drain(0.3)
        log = self.log_text()
        self.assertIn("[ERROR] malformed payload", log)
        self.assertIn("[REJECT]", log)
        self.assertNotIn(("OTHER", "USV1"), self.win.fleet.vehicles)

    def test_8_team_filter(self):
        other = rx_reports_pb2.RxReport(
            team_id="RNRX", vehicle_id="USV1", seq=1,
            heartbeat=rx_reports_pb2.Heartbeat(position=common_pb2.LatLng(latitude=1.2806,
                                                                         longitude=103.8557)))
        self.broker.publish(f"{TOPIC_ROOT}/RNRX/USV1/report", other.SerializeToString())
        drain(0.3)
        self.win.refresh_views()
        self.assertEqual(len(self.win.course_map._canvas._vehicles), 3)
        self.win.team_filter.setCurrentText("RNRX")
        drain(0.1)
        self.assertEqual(list(self.win.course_map._canvas._vehicles), ["RNRX/USV1"])
        self.assertIsNone(self.win.vehicle_monitor.card(TEAM, "USV1"))
        self.win.team_filter.setCurrentText("All teams")

    def test_8a_map_clear_button_clears_trails_and_overlays(self):
        win = self.win
        win.fleet.teams[TEAM].pipeline = ((1.2806, 103.8557), [1])
        win.team_filter.setCurrentText(TEAM)
        win.refresh_views()
        clear_btn = [b for b in win.course_map.findChildren(QPushButton) if b.text() == "Clear"][0]
        clear_btn.click()
        self.assertTrue(all(len(v.trail) == 0 for v in win.fleet.vehicles_of(TEAM)))
        self.assertIsNone(win.fleet.teams[TEAM].pipeline)
        self.assertIsNone(win.course_map._canvas._pl_active)
        self.assertIn(f"[MAP] trails and task overlays cleared ({TEAM})", self.log_text())
        win.team_filter.setCurrentText("All teams")

    def test_8d_theme_toggle_switches_and_is_remembered(self):
        from robocommand_ui import theme
        win = self.win
        self.assertEqual(theme.mode(), theme.LIGHT)            # light by default
        win.theme_btn.click()
        self.assertEqual(theme.mode(), theme.DARK)
        self.assertEqual(self.settings.value("theme"), "dark")
        self.assertIn(theme.PALETTES["dark"]["BG"], app.styleSheet())
        dot = win.course_tab.findChildren(QLabel, "PanelDot")[0]
        self.assertNotIn(theme.PALETTES["light"]["ACCENT"], dot.styleSheet())
        win.theme_btn.click()
        self.assertEqual(theme.mode(), theme.LIGHT)
        self.assertIn(theme.PALETTES["light"]["BG"], app.styleSheet())

    def test_9b_gcs_link_loss_is_shown(self):
        self.reporter.stop()                    # GCS goes away: heartbeats stop
        for v in self.win.fleet.vehicles_of(TEAM):
            v.last_hb_time -= 120               # as if two minutes have passed
        self.win.team_filter.setCurrentText(TEAM)
        self.win.refresh_views()
        row = self.win.teams_panel.row_text(TEAM)
        self.assertTrue(row[2].startswith("LOST 2m"), row)
        self.assertIn("LINK LOST", self.win.run_chip.text())
        self.assertIn(f"[WARN] {TEAM} GCS link lost", self.log_text())
        self.assertEqual(self.win.vehicle_monitor.card(TEAM, "USV1").status_label.text(), "OFFLINE")
        self.assertIn("Broker", self.win.connection_bar.status_label.text())
        self.win.team_filter.setCurrentText("All teams")

    def test_8b_end_run_saves_the_log_and_waits_for_a_new_declaration(self):
        win, tab = self.win, self.win.run_start_tab
        win._confirm = lambda title, text: True
        win.refresh_views()
        tab.select_team(TEAM)
        self.assertEqual(win.fleet.teams[TEAM].run_state, "ACTIVE")
        self.assertTrue(tab.end_btn.isEnabled())
        tab.end_btn.click()
        team = win.fleet.teams[TEAM]
        self.assertEqual((team.run_state, team.last_run_id), ("ENDED", 42))
        self.assertEqual(win.incidents.entries(TEAM), [])
        logs = sorted(self.run_dir.glob(f"*_{TEAM}_run*.log"))
        self.assertEqual({p.name.split("_")[-1] for p in logs}, {"run42.log", "run7.log"})
        text = [p for p in logs if p.name.endswith("run42.log")][0].read_text()
        self.assertIn("ended by host", text)
        self.assertIn("assistance_request", text)          # Task 4 history in the summary
        self.assertIn("[RxCommand] ITSN seq=", text)
        runs = tab._runs
        self.assertEqual([r.run_id for r in runs], [42, 7])   # newest first, by Run ID
        self.assertEqual(tab.runs_table.item(0, 0).text(), "42")
        from robocommand_ui.run_replay import load_run
        replay = load_run(runs[0].replay_path)
        self.assertEqual(replay.course_id, "ALPHA")
        self.assertEqual(replay.vehicle_ids, ["UAV1", "USV1"])
        self.assertIn("USV1", replay.frame(replay.duration).vehicles)
        tab.runs_table.selectRow(0)
        self.assertTrue(tab.replay_btn.isEnabled())
        win.refresh_views()
        tab.select_team(TEAM)
        self.assertFalse(tab.start_btn.isEnabled())         # no restart without a new request
        self.assertFalse(tab.end_btn.isEnabled())
        self.assertIn("new_run", tab.detail.text())

        old_seq = team.declaration_seq
        self.assertTrue(self.reporter.declare())            # the team's next run request
        drain(0.3)
        win.refresh_views()
        tab.select_team(TEAM)
        self.assertEqual(team.run_state, "DECLARED")
        self.assertGreater(team.declaration_seq, old_seq)
        self.assertTrue(tab.start_btn.isEnabled())
        self.assertEqual(tab.run_id.value(), 43)

    def test_8c_reset_run_id_and_seq_for_a_team_without_a_run(self):
        win, tab = self.win, self.win.run_start_tab
        win._confirm = lambda title, text: True
        win.refresh_views()
        tab.select_team(TEAM)
        team = win.fleet.teams[TEAM]
        self.assertEqual(team.run_state, "DECLARED")            # after 8b's new declaration
        self.assertTrue(tab.reset_btn.isEnabled())
        self.assertGreater(win.sender.next_seq(TEAM), 1)
        tab.reset_btn.click()
        win.refresh_views()
        tab.select_team(TEAM)
        self.assertEqual(win.sender.next_seq(TEAM), 1)
        self.assertEqual(tab.run_id.value(), 1)
        self.assertIn("[RESET]", self.log_text())

    def test_9_host_publishes_only_what_the_operator_sent(self):
        allowed = {f"{TOPIC_ROOT}/course", f"{TOPIC_ROOT}/{TEAM}/command"}
        self.assertTrue(set(self.host_published) <= allowed, self.host_published)
        sent_lines = [line for line in self.win.log_panel._all_messages if "[SENT]" in line]
        self.assertEqual(len(sent_lines), len(self.host_published))


if __name__ == "__main__":
    unittest.main()
