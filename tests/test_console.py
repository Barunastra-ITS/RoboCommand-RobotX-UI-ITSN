"""Unit tests for the host console's sending side (no broker, no Qt):
command building and seq, course presets, and Task 4 ack matching."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from robocommand_ui import commands
from robocommand_ui.course_presets import (
    BUILTIN_PRESETS, CoursePreset, delete_preset, load_user_presets, merged, save_preset,
)
from robocommand_ui.course_validation import validate_course
from robocommand_ui.incident_log import IncidentLog
from robocommand_ui.run_log import RunRecorder
from robocommand_ui.proto_helper import rx_commands_pb2, rx_common_pb2, rx_reports_pb2

TEAM = "ITSN"
SQUARE = [(-7.261, 112.791), (-7.261, 112.795), (-7.265, 112.795), (-7.265, 112.791)]


class FakeBroker:
    def __init__(self, error=None):
        self.sent = []
        self.error = error

    def publish(self, topic, payload, retain):
        if self.error is None:
            self.sent.append((topic, payload, retain))
        return self.error


class TestCourse(unittest.TestCase):
    def test_close_ring_repeats_first_corner_once(self):
        ring = commands.close_ring(SQUARE)
        self.assertEqual(ring[-1], SQUARE[0])
        self.assertEqual(commands.close_ring(ring), ring)

    def test_built_course_is_valid(self):
        course = commands.build_course("ALPHA", 25000, commands.close_ring(SQUARE))
        self.assertEqual(validate_course(course), [])
        self.assertTrue(course.HasField("sent_at"))

    def test_point_in_polygon(self):
        ring = commands.close_ring(SQUARE)
        self.assertTrue(commands.point_in_polygon((-7.263, 112.793), ring))
        self.assertFalse(commands.point_in_polygon((-7.270, 112.793), ring))
        self.assertFalse(commands.point_in_polygon((1.28, 103.85), ring))

    def test_send_course_is_retained_and_clear_sends_empty_payload(self):
        broker = FakeBroker()
        sender = commands.CommandSender(broker.publish, lambda t: 0)
        course = commands.build_course("ALPHA", 25000, commands.close_ring(SQUARE))
        self.assertTrue(sender.send_course(course).ok)
        self.assertTrue(sender.clear_course().ok)
        self.assertEqual([(t, r) for t, _, r in broker.sent],
                         [(commands.COURSE_TOPIC, True), (commands.COURSE_TOPIC, True)])
        self.assertEqual(broker.sent[1][1], b"")


class TestCommandSender(unittest.TestCase):
    def test_seq_increases_per_team(self):
        broker = FakeBroker()
        sender = commands.CommandSender(broker.publish, lambda t: 0)
        first = sender.send_command(TEAM, commands.run_start(3, 1))
        second = sender.send_command(TEAM, commands.all_clear("USV"))
        other = sender.send_command("RNRX", commands.all_clear("USV"))
        self.assertEqual((first.seq, second.seq, other.seq), (1, 2, 1))
        self.assertEqual(broker.sent[0][0], f"robocommand/robotx/{TEAM}/command")
        self.assertFalse(broker.sent[0][2])

    def test_seq_continues_after_commands_seen_on_broker(self):
        broker = FakeBroker()
        seen = {TEAM: 9}
        sender = commands.CommandSender(broker.publish, lambda t: seen.get(t, 0))
        self.assertEqual(sender.send_command(TEAM, commands.all_clear("UUV")).seq, 10)

    def test_failed_publish_does_not_use_up_the_seq(self):
        broker = FakeBroker(error="not connected to the broker")
        sender = commands.CommandSender(broker.publish, lambda t: 0)
        result = sender.send_command(TEAM, commands.all_clear("USV"))
        self.assertFalse(result.ok)
        self.assertIn("not connected", result.error)
        self.assertEqual(sender.next_seq(TEAM), 1)

    def test_reset_restarts_one_teams_seq(self):
        broker = FakeBroker()
        seen = {TEAM: 0}
        sender = commands.CommandSender(broker.publish, lambda t: seen[t] if t in seen else 0)
        sender.send_command(TEAM, commands.all_clear("USV"))
        sender.send_command("RNRX", commands.all_clear("USV"))
        sender.reset(TEAM)
        self.assertEqual(sender.next_seq(TEAM), 1)
        self.assertEqual(sender.next_seq("RNRX"), 2)

    def test_no_team_is_refused(self):
        sender = commands.CommandSender(FakeBroker().publish, lambda t: 0)
        self.assertFalse(sender.send_command("", commands.all_clear("USV")).ok)

    def test_command_bodies_decode(self):
        broker = FakeBroker()
        sender = commands.CommandSender(broker.publish, lambda t: 0)
        bodies = [
            commands.run_start(4, 2),
            commands.assistance_request((-7.263, 112.793), "UAV"),
            commands.readiness_confirm(17, "USV1"),
            commands.keep_out_zone((-7.263, 112.793), 20.0, "USV"),
            commands.all_clear("USV"),
            commands.moving_object_alert((-7.262, 112.792), 90.0, 1.5, ["USV", "UUV"]),
        ]
        for body in bodies:
            self.assertTrue(sender.send_command(TEAM, body).ok)
        decoded = [rx_commands_pb2.RxCommand.FromString(p) for _, p, _ in broker.sent]
        self.assertEqual([c.WhichOneof("body") for c in decoded], [name for name, _ in bodies])
        self.assertTrue(all(c.team_id == TEAM for c in decoded))
        self.assertEqual(decoded[0].run_start.declaration_seq, 4)
        self.assertEqual(decoded[1].assistance_request.vehicle_type, rx_common_pb2.TYPE_UAV)
        self.assertEqual(decoded[2].readiness_confirm.vehicle_id, "USV1")
        self.assertAlmostEqual(decoded[3].keep_out_zone.radius_m, 20.0)
        self.assertEqual(list(decoded[5].moving_object_alert.affected_vehicle_types),
                         [rx_common_pb2.TYPE_USV, rx_common_pb2.TYPE_UUV])


class TestCoursePresets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sub" / "presets.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_builtins_are_valid_courses(self):
        for p in BUILTIN_PRESETS:
            course = commands.build_course(p.course_id, p.pinger_freq_hz, p.corners)
            self.assertEqual(validate_course(course), [], p.name)

    def test_missing_file_means_no_user_presets(self):
        self.assertEqual(load_user_presets(self.path), [])

    def test_save_replace_and_delete(self):
        lake = CoursePreset("Lake", "BRAVO", 27000, tuple(commands.close_ring(SQUARE)))
        save_preset(self.path, lake)
        save_preset(self.path, CoursePreset("Lake", "CHARLIE", 26000, lake.corners))
        user = load_user_presets(self.path)
        self.assertEqual([(p.name, p.course_id, p.pinger_freq_hz) for p in user],
                         [("Lake", "CHARLIE", 26000)])
        self.assertEqual(user[0].corners, lake.corners)
        self.assertFalse(user[0].builtin)
        self.assertEqual(delete_preset(self.path, "Lake"), [])

    def test_user_preset_overrides_builtin_of_same_name(self):
        name = BUILTIN_PRESETS[0].name
        mine = CoursePreset(name, "MINE", 1, BUILTIN_PRESETS[0].corners)
        presets = merged([mine])
        self.assertEqual(presets[name].course_id, "MINE")
        self.assertEqual(len(presets), len(BUILTIN_PRESETS))

    def test_corrupt_file_raises_value_error(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json")
        with self.assertRaises(ValueError):
            load_user_presets(self.path)


def report(seq, body, vehicle="USV1", **fields):
    msg = rx_reports_pb2.RxReport(team_id=TEAM, vehicle_id=vehicle, seq=seq)
    getattr(msg, body).CopyFrom(
        {"incident_ack": rx_reports_pb2.IncidentAck,
         "readiness": rx_reports_pb2.ReadinessReport}[body](**fields))
    return msg


class TestIncidentLog(unittest.TestCase):
    def test_assistance_request_flow(self):
        log = IncidentLog()
        entry = log.record(TEAM, 5, "assistance_request", "USV to ...")
        self.assertEqual(entry.status, "WAITING ACK")
        self.assertIn("acked", log.on_report(TEAM, "USV1", report(40, "incident_ack", command_seq=5)))
        self.assertIn("EN ROUTE", entry.status)
        self.assertIn("R=41", log.on_report(TEAM, "USV1", report(41, "readiness", command_seq=5)))
        self.assertEqual(entry.status, "READY USV1 R=41")
        self.assertIs(log.pending_readiness(TEAM), entry)
        log.mark_confirmed(TEAM, "USV1", 41)
        self.assertEqual(entry.status, "CONFIRMED")
        self.assertIsNone(log.pending_readiness(TEAM))

    def test_keep_out_needs_ack_and_moving_object_does_not(self):
        log = IncidentLog()
        koz = log.record(TEAM, 1, "keep_out_zone", "")
        moving = log.record(TEAM, 2, "moving_object_alert", "")
        log.on_report(TEAM, "USV1", report(9, "incident_ack", command_seq=1))
        self.assertEqual(koz.status, "ACKED USV1")
        self.assertEqual(moving.status, "SENT")

    def test_ack_for_unknown_seq_is_flagged(self):
        line = IncidentLog().on_report(TEAM, "USV1", report(9, "incident_ack", command_seq=77))
        self.assertTrue(line.startswith("[WARN]"))

    def test_other_reports_are_ignored(self):
        hb = rx_reports_pb2.RxReport(team_id=TEAM, vehicle_id="USV1", seq=1,
                                     heartbeat=rx_reports_pb2.Heartbeat())
        self.assertIsNone(IncidentLog().on_report(TEAM, "USV1", hb))

    def test_entries_are_per_team_newest_first(self):
        log = IncidentLog()
        log.record(TEAM, 1, "all_clear", "", now=100.0)
        log.record(TEAM, 2, "all_clear", "", now=200.0)
        log.record("RNRX", 1, "all_clear", "", now=300.0)
        self.assertEqual([e.seq for e in log.entries(TEAM)], [2, 1])
        self.assertEqual(len(log.entries()), 3)


class TestRunRecorder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "runs"

    def tearDown(self):
        self.tmp.cleanup()

    def test_log_covers_only_the_run_and_is_written_on_finish(self):
        rec = RunRecorder(self.dir)
        rec.note("before the run")
        rec.begin(TEAM, run_id=7, declaration_seq=3, now=1000.0)
        self.assertTrue(rec.is_active(TEAM))
        rec.note("[RxReport] ITSN/USV1 seq=5 incident_ack")
        path = rec.finish(TEAM, "ended by host", ["Summary line"], now=1065.0)
        self.assertFalse(rec.is_active(TEAM))
        text = path.read_text()
        self.assertIn(f"_{TEAM}_run7.log", path.name)
        self.assertIn("run_id 7", text)
        self.assertIn("declaration seq 3", text)
        self.assertIn("1m05s", text)
        self.assertIn("ended by host", text)
        self.assertIn("Summary line", text)
        self.assertIn("incident_ack", text)
        self.assertNotIn("before the run", text)

    def test_finish_without_a_run_writes_nothing(self):
        rec = RunRecorder(self.dir)
        self.assertIsNone(rec.finish(TEAM, "x", [], now=1.0))
        self.assertFalse(self.dir.exists())

    def test_runs_of_two_teams_are_separate(self):
        rec = RunRecorder(self.dir)
        rec.begin(TEAM, 1, 1, now=10.0)
        rec.begin("RNRX", 2, 1, now=10.0)
        rec.note("shared line")
        a = rec.finish(TEAM, "done", [], now=20.0)
        self.assertTrue(rec.is_active("RNRX"))
        self.assertIn("shared line", a.read_text())

    def test_incident_log_can_forget_one_team(self):
        log = IncidentLog()
        log.record(TEAM, 1, "all_clear", "")
        log.record("RNRX", 1, "all_clear", "")
        log.clear_team(TEAM)
        self.assertEqual([e.team_id for e in log.entries()], ["RNRX"])


if __name__ == "__main__":
    unittest.main()
