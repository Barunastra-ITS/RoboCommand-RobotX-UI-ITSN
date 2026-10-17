"""Host-side model of everything teams report to RoboCommand.

The host UI (running on the course RoboCommand address, e.g. 192.168.65.2)
subscribes to ``robocommand/robotx/#`` and feeds every decoded envelope here.
This module keeps, per team and per vehicle:

- the latest heartbeat and a bounded position trail (the boat movement)
- heartbeat rate against the 2 Hz requirement (handbook §3.4.11)
- RxReport.seq checks: gaps, duplicates/regressions, restarts (§3.4.8)
- current_task transitions that start/end task attempts
- the team's RunDeclaration and whether RunStart.declaration_seq matches it
- the latest Task 1 / Task 2 report contents for drawing on the map

It is Qt-free and has no I/O, so it can be unit-tested directly.
"""

import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

from robocommand_ui.courses import TOPIC_ROOT
from robocommand_ui.proto_helper import common_pb2, robot_state_name, rx_common_pb2, rx_task_name

TRAIL_LENGTH = 1200          # 10 minutes at 2 Hz
RATE_WINDOW_S = 5.0
EXPECTED_HB_HZ = 2.0
STALE_SECONDS = 2.5          # 2 Hz heartbeats: >2.5 s means several were missed
OFFLINE_SECONDS = 30.0
APPLIED_RUN_STARTS = 16       # RunStarts remembered per team to recognise their echoes

LatLng = Tuple[float, float]


class VehicleTrack:
    def __init__(self, team_id: str, vehicle_id: str):
        self.team_id = team_id
        self.vehicle_id = vehicle_id
        self.vehicle_type = rx_common_pb2.TYPE_UNKNOWN
        self.last_hb = None
        self.last_hb_time = 0.0
        self.last_seq = 0
        self.trail: Deque[LatLng] = deque(maxlen=TRAIL_LENGTH)
        self.hb_times: Deque[float] = deque(maxlen=64)
        self.seq_missed = 0
        self.seq_out_of_order = 0
        self.seq_restarts = 0
        self.reports: Dict[str, int] = {}
        self.current_task = rx_task_name(rx_common_pb2.TASK_UNKNOWN)

    @property
    def key(self) -> Tuple[str, str]:
        return (self.team_id, self.vehicle_id)

    def age(self, now: float) -> Optional[float]:
        return None if self.last_hb is None else now - self.last_hb_time

    def rate_hz(self, now: float) -> float:
        recent = [t for t in self.hb_times if now - t <= RATE_WINDOW_S]
        if len(recent) < 2:
            return 0.0
        span = recent[-1] - recent[0]
        return (len(recent) - 1) / span if span > 0 else 0.0


class TeamState:
    def __init__(self, team_id: str):
        self.team_id = team_id
        self.declaration_seq: Optional[int] = None
        self.declared_vehicles: List[str] = []
        self.undeclared_warned: set = set()       # vehicles already warned as undeclared
        self.tiers: Tuple[int, int, int, int] = (0, 0, 0, 0)
        self.geofence: List[LatLng] = []
        self.last_request_seq = 0
        self.last_command_seq = 0
        # (seq, run_id, declaration_seq) of RunStarts already applied, newest last: an
        # echo of any of them (late, reordered or a QoS 1 duplicate) is not a new run
        self.run_start_keys: Deque[Tuple[int, int, int]] = deque(maxlen=APPLIED_RUN_STARTS)
        self.last_seen: Optional[float] = None    # last message from the team's GCS
        self.run_id: Optional[int] = None
        self.run_start_declaration_seq: Optional[int] = None
        # Set when the host ended the run; cleared by the team's next declaration
        self.ended = False
        self.last_run_id: Optional[int] = None
        # Latest Task 1 / Task 2 report contents for the map
        self.safe_passage: Optional[Tuple[LatLng, LatLng, List[Tuple[float, float, int]]]] = None
        self.pipeline: Optional[Tuple[LatLng, List[int]]] = None

    @property
    def run_state(self) -> str:
        if self.ended and self.run_id is None:
            return "ENDED"
        if self.run_id is not None:
            # Requests are not retained: a host that connected after the team
            # declared never saw the declaration, so it can't call a mismatch.
            if (self.declaration_seq is not None
                    and self.run_start_declaration_seq != self.declaration_seq):
                return "DECL MISMATCH"
            return "ACTIVE"
        if self.declaration_seq is not None:
            return "DECLARED"
        return "IDLE"


def parse_topic(topic: str) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
    """Split a RoboCommand topic into (kind, team_id, vehicle_id).

    Returns None for topics outside the handbook layout.
    """
    root = TOPIC_ROOT.split("/")
    parts = topic.strip("/").split("/")
    if parts[:len(root)] != root:
        return None
    rest = parts[len(root):]
    if rest == ["course"]:
        return ("course", None, None)
    if len(rest) == 2 and rest[1] in ("request", "command"):
        return (rest[1], rest[0], None)
    if len(rest) == 3 and rest[2] == "report":
        return ("report", rest[0], rest[1])
    return None


class FleetState:
    """All teams and vehicles seen on the broker."""

    def __init__(self):
        self.teams: Dict[str, TeamState] = {}
        self.vehicles: Dict[Tuple[str, str], VehicleTrack] = {}

    def clear(self) -> None:
        self.teams = {}
        self.vehicles = {}

    def team(self, team_id: str) -> TeamState:
        if team_id not in self.teams:
            self.teams[team_id] = TeamState(team_id)
        return self.teams[team_id]

    def vehicle(self, team_id: str, vehicle_id: str) -> VehicleTrack:
        key = (team_id, vehicle_id)
        if key not in self.vehicles:
            self.team(team_id)
            self.vehicles[key] = VehicleTrack(team_id, vehicle_id)
        return self.vehicles[key]

    def team_ids(self) -> List[str]:
        return sorted(self.teams)

    def team_link(self, team_id: str, now: Optional[float] = None) -> Tuple[str, Optional[float]]:
        """State of a team's GCS link, judged from what it sends.

        MQTT clients can't see each other's connections, so the host can only
        tell a GCS is gone when its messages stop. Returns (state, age_s):
        "UP" when any vehicle heartbeat is fresh, "LOST" when heartbeats came
        and then stopped, "NO HEARTBEAT" when the GCS sent something (e.g. a
        RunDeclaration) but never a heartbeat (age = since its last message),
        "NO DATA" when nothing has come from the team's GCS at all.
        """
        now = time.time() if now is None else now
        ages = [v.age(now) for v in self.vehicles_of(team_id) if v.last_hb is not None]
        if not ages:
            team = self.teams.get(team_id)
            if team is not None and team.last_seen is not None:
                return "NO HEARTBEAT", now - team.last_seen
            return "NO DATA", None
        newest = min(ages)
        return ("UP" if newest <= STALE_SECONDS else "LOST"), newest

    def vehicles_of(self, team_id: Optional[str] = None) -> List[VehicleTrack]:
        tracks = [v for v in self.vehicles.values() if team_id in (None, v.team_id)]
        return sorted(tracks, key=lambda v: v.key)

    # ---------------- ingestion ----------------
    # Each ingest returns human-readable notices for the operator log.

    def ingest_report(self, topic_team: str, topic_vehicle: str, report,
                      now: Optional[float] = None) -> List[str]:
        now = time.time() if now is None else now
        notices = []
        if report.team_id != topic_team or report.vehicle_id != topic_vehicle:
            return [f"[REJECT] report topic {topic_team}/{topic_vehicle} does not match "
                    f"message {report.team_id}/{report.vehicle_id}"]

        team = self.team(topic_team)
        team.last_seen = now
        if (team.declared_vehicles and topic_vehicle not in team.declared_vehicles
                and topic_vehicle not in team.undeclared_warned):
            team.undeclared_warned.add(topic_vehicle)
            notices.append(f"[WARN] {topic_team}/{topic_vehicle} reports but is not declared "
                           f"(declared: {', '.join(team.declared_vehicles)})")
        v = self.vehicle(topic_team, topic_vehicle)
        accepted, seq_notices = self._check_seq(v, report.seq)
        notices.extend(seq_notices)
        if not accepted:
            return notices          # stale or duplicate: don't move the boat backwards

        body = report.WhichOneof("body")
        if body is None:
            return notices + [f"[WARN] {topic_team}/{topic_vehicle} report seq={report.seq} has no body"]
        if body == "heartbeat":
            notices.extend(self._apply_heartbeat(v, report.heartbeat, now))
        else:
            v.reports[body] = v.reports.get(body, 0) + 1
            self._apply_task_report(self.team(topic_team), body, report)
        return notices

    def ingest_request(self, topic_team: str, request, now: Optional[float] = None) -> List[str]:
        if request.team_id != topic_team:
            return [f"[REJECT] request topic team {topic_team} does not match message {request.team_id}"]
        team = self.team(topic_team)
        team.last_seen = time.time() if now is None else now
        notices = []
        if request.seq <= team.last_request_seq:
            notices.append(f"[WARN] {topic_team} request seq {request.seq} not increasing "
                           f"(last {team.last_request_seq})")
        team.last_request_seq = max(team.last_request_seq, request.seq)

        if request.WhichOneof("body") == "run_declaration":
            decl = request.run_declaration
            team.declaration_seq = request.seq
            team.declared_vehicles = list(decl.vehicle_ids)
            team.tiers = (decl.task1_tier, decl.task2_tier, decl.task3_tier, decl.task4_tier)
            team.geofence = [(p.latitude, p.longitude) for p in decl.uav_geofence]
            team.run_id = None
            team.run_start_declaration_seq = None
            team.ended = False
            team.undeclared_warned = set()
            # The declaration is the team's vehicle list: drop leftovers from an older one
            for v in self.vehicles_of(topic_team):
                if v.vehicle_id not in team.declared_vehicles:
                    del self.vehicles[v.key]
                    notices.append(f"{topic_team}/{v.vehicle_id} removed: not in the new declaration")
            for vid in team.declared_vehicles:
                self.vehicle(topic_team, vid)
            notices.append(f"{topic_team} declared run seq={request.seq} "
                           f"vehicles={team.declared_vehicles}")
        return notices

    def ingest_command(self, topic_team: str, command, now: Optional[float] = None) -> List[str]:
        if command.team_id and command.team_id != topic_team:
            return [f"[REJECT] command topic team {topic_team} does not match message {command.team_id}"]
        team = self.team(topic_team)
        team.last_command_seq = max(team.last_command_seq, command.seq)
        if command.WhichOneof("body") == "run_start":
            if self.is_applied_run_start(topic_team, command):
                return []           # our own RunStart coming back: already applied on send
            return self.apply_run_start(topic_team, command.seq, command.run_start)
        return []

    def is_applied_run_start(self, team_id: str, command) -> bool:
        """Is this RxCommand the RunStart already applied (our own, echoed back)?"""
        team = self.teams.get(team_id)
        if team is None or command.WhichOneof("body") != "run_start":
            return False
        rs = command.run_start
        return (command.seq, rs.run_id, rs.declaration_seq) in team.run_start_keys

    def apply_run_start(self, team_id: str, seq: int, rs) -> List[str]:
        """A RunStart for the team: new run, clean map.

        The console calls this as soon as its own RunStart is published, so the
        map is cleared even if the broker's echo of it never arrives; the echo
        (same seq) is then ignored instead of clearing a second time.
        """
        team = self.team(team_id)
        team.run_start_keys.append((seq, rs.run_id, rs.declaration_seq))
        team.last_command_seq = max(team.last_command_seq, seq)
        self.clear_drawings(team_id)
        team.ended = False
        team.run_id = rs.run_id
        team.run_start_declaration_seq = rs.declaration_seq
        if team.declaration_seq is None:
            return [f"{team_id} RunStart run_id={rs.run_id} (declaration not seen by "
                    f"this host; declaration_seq={rs.declaration_seq})"]
        if rs.declaration_seq != team.declaration_seq:
            return [f"[WARN] {team_id} RunStart declaration_seq={rs.declaration_seq} "
                    f"does not match declaration seq={team.declaration_seq}"]
        return [f"{team_id} RunStart run_id={rs.run_id}"]

    def start_blockers(self, team_id: str, now: Optional[float] = None) -> List[str]:
        """Why the team's run can't start yet; empty when it can.

        Every declared vehicle must be live (heartbeat within STALE_SECONDS)
        and reporting STATE_AUTO.
        """
        now = time.time() if now is None else now
        team = self.teams.get(team_id)
        if team is None or not team.declared_vehicles:
            return ["no vehicles declared"]
        blockers = []
        for vid in team.declared_vehicles:
            v = self.vehicles.get((team_id, vid))
            age = None if v is None else v.age(now)
            if age is None:
                blockers.append(f"{vid} no heartbeat")
            elif age > STALE_SECONDS:
                blockers.append(f"{vid} stale ({age:.1f} s)")
            elif v.last_hb.state != common_pb2.STATE_AUTO:
                blockers.append(f"{vid} {robot_state_name(v.last_hb.state)} (needs AUTO)")
        return blockers

    def clear_drawings(self, team_id: Optional[str] = None) -> None:
        """Forget trails and Task 1 / Task 2 overlays (one team, or every team).

        Run start does this for the team; the Map tab's Clear button for any.
        Positions are kept, so live boats stay on the map.
        """
        for tid in ([team_id] if team_id is not None else list(self.teams)):
            team = self.team(tid)
            team.safe_passage = None
            team.pipeline = None
            for v in self.vehicles_of(tid):
                v.trail.clear()

    def reset_counters(self, team_id: str) -> None:
        """Forget the team's command seq and last run id (host restarts numbering)."""
        team = self.teams.get(team_id)
        if team is not None:
            team.last_command_seq = 0
            team.run_start_keys.clear()
            team.last_run_id = None

    def end_run(self, team_id: str) -> Optional[int]:
        """The host ends a team's run (there is no protocol message for it).

        The team shows ENDED until it sends a new RunDeclaration. Returns the
        run_id that ended, or None when the team had no run in progress.
        """
        team = self.teams.get(team_id)
        if team is None or team.run_id is None:
            return None
        team.last_run_id = team.run_id
        team.run_id = None
        team.run_start_declaration_seq = None
        team.ended = True
        return team.last_run_id

    # ---------------- internals ----------------

    @staticmethod
    def _check_seq(v: VehicleTrack, seq: int) -> Tuple[bool, List[str]]:
        """Return (accept, notices). Stale and duplicate reports are not applied."""
        name = f"{v.team_id}/{v.vehicle_id}"
        last = v.last_seq
        if last == 0 or seq == last + 1:
            v.last_seq = seq
            return True, []
        if seq == 1 and last > 1:
            v.last_seq = seq
            v.seq_restarts += 1
            return True, [f"{name} report seq restarted at 1 (was {last})"]
        if seq > last + 1:
            v.last_seq = seq
            v.seq_missed += seq - last - 1
            return True, [f"[WARN] {name} missed {seq - last - 1} report(s) (seq {last} -> {seq})"]
        v.seq_out_of_order += 1
        return False, [f"[WARN] {name} report seq {seq} not increasing (last {last}); dropped"]

    @staticmethod
    def _apply_heartbeat(v: VehicleTrack, hb, now: float) -> List[str]:
        notices = []
        v.vehicle_type = hb.vehicle_type
        v.last_hb = hb
        v.last_hb_time = now
        v.hb_times.append(now)
        if hb.HasField("position"):
            v.trail.append((hb.position.latitude, hb.position.longitude))
        task = rx_task_name(hb.current_task)
        if task != v.current_task:
            name = f"{v.team_id}/{v.vehicle_id}"
            if task == "NONE":
                if v.current_task not in ("NONE", "UNKNOWN"):
                    notices.append(f"{name} ended task attempt {v.current_task}")
            elif task != "UNKNOWN":
                notices.append(f"{name} started task attempt {task}")
            v.current_task = task
        return notices

    @staticmethod
    def _apply_task_report(team: TeamState, body: str, report) -> None:
        if body == "safe_passage":
            sp = report.safe_passage
            team.safe_passage = (
                (sp.entry_position.latitude, sp.entry_position.longitude),
                (sp.exit_position.latitude, sp.exit_position.longitude),
                [(b.position.latitude, b.position.longitude, b.state) for b in sp.buoys],
            )
        elif body == "pipeline_survey":
            ps = report.pipeline_survey
            team.pipeline = (
                (ps.active_buoy_position.latitude, ps.active_buoy_position.longitude),
                list(ps.segments),
            )
