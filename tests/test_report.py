"""Unit tests for report.py (GCS reporter) and course host selection."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import report
from fake_broker import FakeBroker
from robocommand_ui.courses import COURSES, course_for_address, detect_course, resolve_host
from robocommand_ui.proto_helper import (
    common_pb2, now_ts, rx_commands_pb2, rx_common_pb2, rx_course_pb2, rx_reports_pb2,
    rx_requests_pb2,
)

TEAM = "ITSN"
CORNERS = [(1.280329, 103.8556869), (1.2804716, 103.8554529), (1.2808993, 103.8557337),
           (1.2807567, 103.8559743), (1.280329, 103.8556869)]


def course_msg(closed=True):
    pts = CORNERS if closed else CORNERS[:-1]
    return rx_course_pb2.RxCourse(
        course_id="ALPHA", pinger_freq_hz=25000, sent_at=now_ts(),
        corners=[common_pb2.LatLng(latitude=a, longitude=b) for a, b in pts])


def make_reporter(broker, vehicles=None):
    vehicles = vehicles or {"USV1": rx_common_pb2.TYPE_USV}
    tiers = (common_pb2.TIER_CORE, common_pb2.TIER_NONE, common_pb2.TIER_NONE, common_pb2.TIER_NONE)
    r = report.GcsReporter("192.168.65.2", TEAM, vehicles, tiers, [], client_factory=broker.client)
    r._client.loop_start()          # connect + subscribe, without the heartbeat thread
    return r


def published(broker, suffix, cls):
    out = []
    for topic, payload in broker.published:
        if topic.endswith(suffix):
            msg = cls()
            msg.ParseFromString(payload)
            out.append((topic, msg))
    return out


class TestCourseHosts(unittest.TestCase):
    def test_resolve_each_course(self):
        self.assertEqual(resolve_host("alpha"), "192.168.65.2")
        self.assertEqual(resolve_host("Delta"), "192.168.68.2")
        self.assertEqual(resolve_host("demo", "10.0.70.5"), "10.0.70.5")
        with self.assertRaises(ValueError):
            resolve_host("demo")
        with self.assertRaises(ValueError):
            resolve_host("echo")

    def test_address_to_course(self):
        self.assertEqual(course_for_address("192.168.66.40"), COURSES["bravo"])
        self.assertIsNone(course_for_address("192.168.10.75"))
        self.assertIsNone(course_for_address("not-an-ip"))

    def test_detect_picks_the_course_of_the_dhcp_address(self):
        probed = []

        def probe(host):
            probed.append(host)
            return True

        det = detect_course(probe=probe, addresses=[("lo", "127.0.0.1"), ("wlan0", "192.168.10.75"),
                                                    ("eth0", "192.168.67.23")])
        self.assertEqual(det.course, COURSES["charlie"])
        self.assertEqual((det.interface, det.local_address), ("eth0", "192.168.67.23"))
        self.assertEqual(probed, ["192.168.67.2"])
        self.assertIn("Course Alpha=192.168.65.2", det.log[0])   # every host listed

    def test_detect_requires_the_host_to_answer(self):
        det = detect_course(probe=lambda h: False, addresses=[("eth0", "192.168.65.30")])
        self.assertIsNone(det.course)
        self.assertTrue(any("not reachable" in line for line in det.log))

    def test_detect_falls_back_to_probing_every_host(self):
        det = detect_course(probe=lambda h: h == "192.168.68.2", addresses=[("eth0", "10.1.1.5")])
        self.assertEqual(det.course, COURSES["delta"])


class TestCliParsing(unittest.TestCase):
    def test_vehicle_spec(self):
        self.assertEqual(report.parse_vehicle("USV1"), ("USV1", rx_common_pb2.TYPE_USV))
        self.assertEqual(report.parse_vehicle("drone:UAV"), ("drone", rx_common_pb2.TYPE_UAV))

    def test_vehicle_type_must_be_known(self):
        import argparse
        with self.assertRaises(argparse.ArgumentTypeError):
            report.parse_vehicle("boat1")
        self.assertEqual(report.parse_vehicle("boat1:USV"), ("boat1", rx_common_pb2.TYPE_USV))

    def test_enum_ints_are_range_checked(self):
        from robocommand_ui.proto_helper import STATE_STR_MAP
        self.assertEqual(report.enum_value(STATE_STR_MAP, "STATE_", 3), 3)
        with self.assertRaises(ValueError):
            report.enum_value(STATE_STR_MAP, "STATE_", 2 ** 40)

    def test_geofence_is_closed(self):
        pts = report.parse_geofence("1,2;1,3;2,3;2,2")
        self.assertEqual(pts[0], pts[-1])
        self.assertEqual(len(pts), 5)

    def test_uav_requires_geofence(self):
        with self.assertRaises(SystemExit):
            report.main(["--course", "alpha", "--team", TEAM, "--vehicle", "UAV1"])

    def test_tier_unknown_rejected(self):
        with self.assertRaises(SystemExit):
            report.main(["--course", "alpha", "--team", TEAM, "--vehicle", "USV1",
                         "--tiers", "CORE,UNKNOWN,NONE,NONE"])


class TestReporter(unittest.TestCase):
    def test_subscribes_to_course_and_own_command_topic(self):
        broker = FakeBroker()
        make_reporter(broker)
        filters = [f for f, _ in broker._subs]
        self.assertEqual(filters, ["robocommand/robotx/course", f"robocommand/robotx/{TEAM}/command"])

    def test_valid_course_triggers_one_declaration(self):
        broker = FakeBroker()
        broker.publish("robocommand/robotx/course", course_msg().SerializeToString(), retain=True)
        r = make_reporter(broker)
        reqs = published(broker, f"{TEAM}/request", rx_requests_pb2.RxRequest)
        self.assertEqual(len(reqs), 1)
        self.assertEqual(list(reqs[0][1].run_declaration.vehicle_ids), ["USV1"])
        self.assertEqual(r.declaration_seq, reqs[0][1].seq)
        broker.publish("robocommand/robotx/course", course_msg().SerializeToString(), retain=True)
        self.assertEqual(len(published(broker, f"{TEAM}/request", rx_requests_pb2.RxRequest)), 1)

    def test_invalid_course_does_not_declare(self):
        broker = FakeBroker()
        broker.publish("robocommand/robotx/course", course_msg(closed=False).SerializeToString())
        r = make_reporter(broker)
        broker.publish("robocommand/robotx/course", course_msg(closed=False).SerializeToString())
        self.assertIsNone(r.declaration_seq)
        self.assertEqual(published(broker, "/request", rx_requests_pb2.RxRequest), [])

    def test_heartbeat_topic_fields_and_per_vehicle_seq(self):
        broker = FakeBroker()
        r = make_reporter(broker, {"USV1": rx_common_pb2.TYPE_USV, "UAV1": rx_common_pb2.TYPE_UAV})
        self.assertFalse(r.heartbeat("USV1"))           # no fix yet: held
        r.update("USV1", lat=1.2806, lng=103.8557, heading_deg=90, spd_mps=1.5,
                 state="AUTO", current_task="SAFE_PASSAGE")
        r.update("UAV1", lat=1.2807, lng=103.8558, state="STATE_MANUAL")
        for _ in range(2):
            self.assertTrue(r.heartbeat("USV1"))
        self.assertTrue(r.heartbeat("UAV1"))
        usv = published(broker, f"{TEAM}/USV1/report", rx_reports_pb2.RxReport)
        uav = published(broker, f"{TEAM}/UAV1/report", rx_reports_pb2.RxReport)
        self.assertEqual([m.seq for _, m in usv], [1, 2])
        self.assertEqual([m.seq for _, m in uav], [1])
        hb = usv[-1][1].heartbeat
        self.assertEqual((usv[-1][1].team_id, usv[-1][1].vehicle_id), (TEAM, "USV1"))
        self.assertEqual(hb.state, common_pb2.STATE_AUTO)
        self.assertEqual(hb.current_task, rx_common_pb2.TASK_SAFE_PASSAGE)
        self.assertEqual(hb.vehicle_type, rx_common_pb2.TYPE_USV)
        self.assertAlmostEqual(hb.heading_deg, 90.0)

    def test_concurrent_declare_once_publishes_one_declaration(self):
        import threading
        broker = FakeBroker()
        r = make_reporter(broker)
        threads = [threading.Thread(target=r.declare_once) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(published(broker, "/request", rx_requests_pb2.RxRequest)), 1)

    def test_no_seq_consumed_while_disconnected(self):
        broker = FakeBroker()
        r = make_reporter(broker)
        r.update("USV1", lat=1.0, lng=2.0)
        self.assertTrue(r.heartbeat("USV1"))
        r.connected.clear()
        self.assertFalse(r.heartbeat("USV1"))
        self.assertFalse(r.heartbeat("USV1"))
        r.connected.set()
        self.assertTrue(r.heartbeat("USV1"))
        seqs = [m.seq for _, m in published(broker, "/USV1/report", rx_reports_pb2.RxReport)]
        self.assertEqual(seqs, [1, 2])

    def test_update_validates_input(self):
        r = make_reporter(FakeBroker())
        with self.assertRaises(ValueError):
            r.update("USV9", lat=1.0)
        with self.assertRaises(ValueError):
            r.update("USV1", lat=95.0)
        with self.assertRaises(ValueError):
            r.update("USV1", altitude=3.0)
        with self.assertRaises(ValueError):
            r.update("USV1", state="FLYING")

    def test_run_start_is_verified_against_declaration(self):
        broker = FakeBroker()
        broker.publish("robocommand/robotx/course", course_msg().SerializeToString(), retain=True)
        r = make_reporter(broker)
        cmd_topic = f"robocommand/robotx/{TEAM}/command"

        wrong = rx_commands_pb2.RxCommand(team_id=TEAM, seq=1, run_start=rx_commands_pb2.RunStart(
            declaration_seq=r.declaration_seq + 5, run_id=9))
        broker.publish(cmd_topic, wrong.SerializeToString())
        self.assertIsNone(r.run_id)

        other_team = rx_commands_pb2.RxCommand(team_id="OTHER", seq=2, run_start=rx_commands_pb2.RunStart(
            declaration_seq=r.declaration_seq, run_id=8))
        broker.publish(cmd_topic, other_team.SerializeToString())
        self.assertIsNone(r.run_id)

        right = rx_commands_pb2.RxCommand(team_id=TEAM, seq=3, run_start=rx_commands_pb2.RunStart(
            declaration_seq=r.declaration_seq, run_id=42))
        broker.publish(cmd_topic, right.SerializeToString())
        self.assertEqual(r.run_id, 42)

    def test_malformed_command_does_not_raise(self):
        broker = FakeBroker()
        r = make_reporter(broker)
        broker.publish(f"robocommand/robotx/{TEAM}/command", b"\xff\xff\xff")
        self.assertIsNone(r.run_id)

    def test_course_centre_orbit_is_inside_course(self):
        lat, lng, radius = report.course_centre(course_msg())
        self.assertTrue(1.2803 < lat < 1.2809)
        self.assertTrue(103.8554 < lng < 103.8560)
        self.assertGreater(radius, 5.0)


if __name__ == "__main__":
    unittest.main()
