"""End-to-end: report.py (GCS) -> broker -> host monitor UI, in one process.

Uses tests/fake_broker.py so it runs without mosquitto. The reporter and the
host UI run their real code paths: the reporter's heartbeat thread publishes at
2 Hz, the host MqttWorker decodes on that thread and signals the Qt UI.
"""

import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from PyQt5.QtWidgets import QApplication

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

        # Host monitor listens to everything
        cls.win = MainWindow()
        cls.broker.subscribe(f"{TOPIC_ROOT}/#", lambda m: cls.win.mqtt._on_message(None, None, m))

        # GCS reporter on the team side
        cls.reporter = GcsReporter(
            "192.168.65.2", TEAM,
            {"USV1": rx_common_pb2.TYPE_USV, "UAV1": rx_common_pb2.TYPE_UAV},
            (common_pb2.TIER_CORE, common_pb2.TIER_NONE, common_pb2.TIER_NONE, common_pb2.TIER_NONE),
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

    def test_9_host_never_publishes(self):
        host_topics = {t for t, _ in self.broker.published
                       if not t.startswith(f"{TOPIC_ROOT}/{TEAM}/") and t != f"{TOPIC_ROOT}/course"
                       and not t.startswith(f"{TOPIC_ROOT}/RNRX/")}
        self.assertEqual(host_topics, set())
        self.assertFalse(hasattr(self.win.mqtt, "_publish"))


if __name__ == "__main__":
    unittest.main()
