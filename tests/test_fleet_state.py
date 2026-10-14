"""Unit tests for the host-side FleetState model (no broker, no Qt)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from robocommand_ui.fleet_state import FleetState, parse_topic
from robocommand_ui.proto_helper import (
    common_pb2, rx_commands_pb2, rx_common_pb2, rx_reports_pb2, rx_requests_pb2,
)

TEAM = "ITSN"


def heartbeat(seq, lat=1.2806, lng=103.8557, task=rx_common_pb2.TASK_NONE,
              vehicle="USV1", team=TEAM):
    return rx_reports_pb2.RxReport(
        team_id=team, vehicle_id=vehicle, seq=seq,
        heartbeat=rx_reports_pb2.Heartbeat(
            state=common_pb2.STATE_AUTO,
            position=common_pb2.LatLng(latitude=lat, longitude=lng),
            vehicle_type=rx_common_pb2.TYPE_USV,
            current_task=task,
        ),
    )


def declaration(seq, vehicles=("USV1",)):
    return rx_requests_pb2.RxRequest(
        team_id=TEAM, seq=seq,
        run_declaration=rx_requests_pb2.RunDeclaration(
            vehicle_ids=list(vehicles), task1_tier=common_pb2.TIER_CORE,
            task2_tier=common_pb2.TIER_NONE, task3_tier=common_pb2.TIER_NONE,
            task4_tier=common_pb2.TIER_NONE,
        ),
    )


def run_start(declaration_seq, run_id=7):
    return rx_commands_pb2.RxCommand(
        team_id=TEAM, seq=1,
        run_start=rx_commands_pb2.RunStart(declaration_seq=declaration_seq, run_id=run_id),
    )


class TestParseTopic(unittest.TestCase):
    def test_handbook_topics(self):
        self.assertEqual(parse_topic("robocommand/robotx/course"), ("course", None, None))
        self.assertEqual(parse_topic("robocommand/robotx/ITSN/request"), ("request", "ITSN", None))
        self.assertEqual(parse_topic("robocommand/robotx/ITSN/command"), ("command", "ITSN", None))
        self.assertEqual(parse_topic("robocommand/robotx/ITSN/USV1/report"),
                         ("report", "ITSN", "USV1"))

    def test_rejects_other_layouts(self):
        for topic in ("robocommand/roboboat/ITSN/request", "robocommand/robotx/ITSN",
                      "robocommand/robotx/ITSN/USV1/extra/report", "other/topic"):
            self.assertIsNone(parse_topic(topic), topic)


class TestMovement(unittest.TestCase):
    def test_heartbeats_build_a_trail_per_vehicle(self):
        fleet = FleetState()
        for i in range(1, 4):
            fleet.ingest_report(TEAM, "USV1", heartbeat(i, lat=1.0 + i * 1e-5), now=100.0 + i * 0.5)
        v = fleet.vehicles[(TEAM, "USV1")]
        self.assertEqual(len(v.trail), 3)
        self.assertAlmostEqual(v.trail[-1][0], 1.00003)
        self.assertEqual(v.last_seq, 3)

    def test_rate_reflects_2hz(self):
        fleet = FleetState()
        for i in range(1, 11):
            fleet.ingest_report(TEAM, "USV1", heartbeat(i), now=100.0 + i * 0.5)
        v = fleet.vehicles[(TEAM, "USV1")]
        self.assertAlmostEqual(v.rate_hz(now=105.0), 2.0, places=3)

    def test_vehicles_are_separated_by_team(self):
        fleet = FleetState()
        fleet.ingest_report("A", "USV1", heartbeat(1, team="A"))
        fleet.ingest_report("B", "USV1", heartbeat(1, team="B"))
        self.assertEqual(fleet.team_ids(), ["A", "B"])
        self.assertEqual([v.key for v in fleet.vehicles_of("B")], [("B", "USV1")])


class TestValidation(unittest.TestCase):
    def test_topic_message_mismatch_is_rejected(self):
        fleet = FleetState()
        notices = fleet.ingest_report(TEAM, "USV2", heartbeat(1, vehicle="USV1"))
        self.assertTrue(notices[0].startswith("[REJECT]"))
        self.assertEqual(fleet.vehicles, {})

    def test_seq_gap_and_regression(self):
        fleet = FleetState()
        fleet.ingest_report(TEAM, "USV1", heartbeat(1))
        gap = fleet.ingest_report(TEAM, "USV1", heartbeat(4))
        back = fleet.ingest_report(TEAM, "USV1", heartbeat(3))
        v = fleet.vehicles[(TEAM, "USV1")]
        self.assertEqual(v.seq_missed, 2)
        self.assertEqual(v.seq_out_of_order, 1)
        self.assertEqual(v.last_seq, 4)
        self.assertIn("missed 2", gap[0])
        self.assertIn("not increasing", back[0])

    def test_stale_and_duplicate_reports_do_not_move_the_boat(self):
        fleet = FleetState()
        for seq in (1, 2, 3):
            fleet.ingest_report(TEAM, "USV1", heartbeat(seq, lat=float(seq)))
        dup = fleet.ingest_report(TEAM, "USV1", heartbeat(3, lat=9.0))
        old = fleet.ingest_report(TEAM, "USV1", heartbeat(2, lat=9.0))
        v = fleet.vehicles[(TEAM, "USV1")]
        self.assertEqual(v.last_hb.position.latitude, 3.0)
        self.assertEqual([p[0] for p in v.trail], [1.0, 2.0, 3.0])
        self.assertIn("dropped", dup[0])
        self.assertIn("dropped", old[0])
        self.assertEqual(v.seq_restarts, 0)

    def test_seq_restart_is_not_an_error(self):
        fleet = FleetState()
        fleet.ingest_report(TEAM, "USV1", heartbeat(5))
        notices = fleet.ingest_report(TEAM, "USV1", heartbeat(1))
        self.assertIn("restarted", notices[0])
        self.assertEqual(fleet.vehicles[(TEAM, "USV1")].seq_restarts, 1)

    def test_task_transitions_are_reported(self):
        fleet = FleetState()
        first = fleet.ingest_report(TEAM, "USV1", heartbeat(1, task=rx_common_pb2.TASK_NONE))
        self.assertEqual(first, [])             # no attempt was running, nothing ended
        start = fleet.ingest_report(TEAM, "USV1", heartbeat(2, task=rx_common_pb2.TASK_SAFE_PASSAGE))
        end = fleet.ingest_report(TEAM, "USV1", heartbeat(3, task=rx_common_pb2.TASK_NONE))
        self.assertIn("started task attempt SAFE_PASSAGE", start[0])
        self.assertIn("ended task attempt SAFE_PASSAGE", end[0])


class TestTeamLink(unittest.TestCase):
    def test_link_follows_newest_heartbeat(self):
        fleet = FleetState()
        self.assertEqual(fleet.team_link(TEAM, now=100.0), ("NO DATA", None))
        fleet.ingest_report(TEAM, "USV1", heartbeat(1), now=100.0)
        fleet.ingest_report(TEAM, "UAV1", heartbeat(1, vehicle="UAV1"), now=90.0)
        self.assertEqual(fleet.team_link(TEAM, now=101.0)[0], "UP")      # USV1 still fresh
        state, age = fleet.team_link(TEAM, now=160.0)
        self.assertEqual(state, "LOST")
        self.assertAlmostEqual(age, 60.0)


class TestTeamLinkWithoutHeartbeats(unittest.TestCase):
    def test_declared_but_silent_gcs(self):
        fleet = FleetState()
        fleet.ingest_request(TEAM, declaration(1, ("USV1", "UAV1")), now=100.0)
        state, age = fleet.team_link(TEAM, now=580.0)
        self.assertEqual(state, "NO HEARTBEAT")
        self.assertAlmostEqual(age, 480.0)
        fleet.ingest_report(TEAM, "USV1", heartbeat(1), now=600.0)
        self.assertEqual(fleet.team_link(TEAM, now=600.5)[0], "UP")


class TestRunState(unittest.TestCase):
    def test_declared_then_active(self):
        fleet = FleetState()
        self.assertEqual(fleet.team(TEAM).run_state, "IDLE")
        fleet.ingest_request(TEAM, declaration(3, ("USV1", "UAV1")))
        team = fleet.teams[TEAM]
        self.assertEqual(team.run_state, "DECLARED")
        self.assertIn((TEAM, "UAV1"), fleet.vehicles)
        fleet.ingest_command(TEAM, run_start(3))
        self.assertEqual(team.run_state, "ACTIVE")
        self.assertEqual(team.run_id, 7)

    def test_run_start_with_wrong_declaration_seq_is_flagged(self):
        fleet = FleetState()
        fleet.ingest_request(TEAM, declaration(3))
        notices = fleet.ingest_command(TEAM, run_start(2))
        self.assertEqual(fleet.teams[TEAM].run_state, "DECL MISMATCH")
        self.assertIn("does not match", notices[0])

    def test_run_start_without_seen_declaration_is_not_a_mismatch(self):
        fleet = FleetState()            # host connected after the team declared
        notices = fleet.ingest_command(TEAM, run_start(3))
        self.assertEqual(fleet.teams[TEAM].run_state, "ACTIVE")
        self.assertIn("not seen", notices[0])

    def test_host_ends_the_run_and_a_new_declaration_reopens_it(self):
        fleet = FleetState()
        fleet.ingest_request(TEAM, declaration(3))
        fleet.ingest_command(TEAM, run_start(3, run_id=7))
        self.assertEqual(fleet.end_run(TEAM), 7)
        team = fleet.teams[TEAM]
        self.assertEqual((team.run_state, team.run_id, team.last_run_id), ("ENDED", None, 7))
        fleet.ingest_request(TEAM, declaration(4))            # the team's next run request
        self.assertEqual(team.run_state, "DECLARED")
        fleet.ingest_command(TEAM, run_start(4, run_id=8))
        self.assertEqual(team.run_state, "ACTIVE")

    def test_ending_a_team_without_a_run_does_nothing(self):
        fleet = FleetState()
        fleet.ingest_request(TEAM, declaration(3))
        self.assertIsNone(fleet.end_run(TEAM))
        self.assertIsNone(fleet.end_run("NOPE"))
        self.assertEqual(fleet.teams[TEAM].run_state, "DECLARED")

    def test_task_report_contents_are_kept_for_the_map(self):
        fleet = FleetState()
        report = rx_reports_pb2.RxReport(
            team_id=TEAM, vehicle_id="USV1", seq=1,
            safe_passage=rx_reports_pb2.SafePassageReport(
                entry_position=common_pb2.LatLng(latitude=1.0, longitude=2.0),
                exit_position=common_pb2.LatLng(latitude=1.1, longitude=2.1),
                buoys=[rx_reports_pb2.BuoyDetection(
                    position=common_pb2.LatLng(latitude=1.05, longitude=2.05),
                    state=rx_common_pb2.BEACON_STATE_FLASHING_RED)],
            ),
        )
        fleet.ingest_report(TEAM, "USV1", report)
        entry, _, buoys = fleet.teams[TEAM].safe_passage
        self.assertEqual(entry, (1.0, 2.0))
        self.assertEqual(buoys[0][2], rx_common_pb2.BEACON_STATE_FLASHING_RED)
        self.assertEqual(fleet.vehicles[(TEAM, "USV1")].reports, {"safe_passage": 1})


if __name__ == "__main__":
    unittest.main()
