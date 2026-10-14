"""Messages the host publishes as RoboCommand: RxCourse, RunStart and Task 4.

Replaces running ``test_client.py`` (``rc ...``) in a second terminal. The
console only publishes when the operator presses a button. RxCommand.seq is
kept per team and never goes backwards: each command takes one more than the
highest seq this console sent or saw on the broker for that team, so a
command sent from another tool can't make ours look stale to the GCS.

Qt-free so it can be unit-tested directly.
"""

from typing import Callable, Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple

from robocommand_ui.courses import TOPIC_ROOT
from robocommand_ui.proto_helper import (
    common_pb2, now_ts, rx_commands_pb2, rx_common_pb2, rx_course_pb2,
)

LatLng = Tuple[float, float]
COURSE_TOPIC = f"{TOPIC_ROOT}/course"

VEHICLE_TYPES = {
    "USV": rx_common_pb2.TYPE_USV,
    "UUV": rx_common_pb2.TYPE_UUV,
    "UAV": rx_common_pb2.TYPE_UAV,
}

# publish(topic, payload, retain) -> error text, or None when it went out
PublishFn = Callable[[str, bytes, bool], Optional[str]]


def command_topic(team_id: str) -> str:
    return f"{TOPIC_ROOT}/{team_id}/command"


def _latlng(point: LatLng):
    return common_pb2.LatLng(latitude=point[0], longitude=point[1])


def close_ring(corners: Sequence[LatLng]) -> List[LatLng]:
    """Return the corners with the first point repeated at the end if needed."""
    ring = list(corners)
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def build_course(course_id: str, pinger_freq_hz: int, corners: Sequence[LatLng]):
    return rx_course_pb2.RxCourse(
        course_id=course_id, pinger_freq_hz=pinger_freq_hz,
        corners=[_latlng(c) for c in corners], sent_at=now_ts())


def point_in_polygon(point: LatLng, ring: Sequence[LatLng]) -> bool:
    """Ray-casting test on lat/lng; fine at course scale (a few hundred metres)."""
    lat, lng = point
    inside = False
    n = len(ring)
    for i in range(n):
        (lat1, lng1), (lat2, lng2) = ring[i], ring[(i + 1) % n]
        if (lng1 > lng) != (lng2 > lng):
            cross = lat1 + (lng - lng1) * (lat2 - lat1) / (lng2 - lng1)
            if lat < cross:
                inside = not inside
    return inside


# ---- RxCommand bodies --------------------------------------------------------

def run_start(declaration_seq: int, run_id: int):
    return "run_start", rx_commands_pb2.RunStart(declaration_seq=declaration_seq, run_id=run_id)


def assistance_request(position: LatLng, vehicle_type: str):
    return "assistance_request", rx_commands_pb2.AssistanceRequest(
        position=_latlng(position), vehicle_type=VEHICLE_TYPES[vehicle_type])


def readiness_confirm(report_seq: int, vehicle_id: str):
    return "readiness_confirm", rx_commands_pb2.ReadinessConfirm(
        report_seq=report_seq, vehicle_id=vehicle_id)


def keep_out_zone(center: LatLng, radius_m: float, vehicle_type: str):
    return "keep_out_zone", rx_commands_pb2.KeepOutZone(
        center=_latlng(center), radius_m=radius_m, vehicle_type=VEHICLE_TYPES[vehicle_type])


def all_clear(vehicle_type: str):
    return "all_clear", rx_commands_pb2.AllClear(vehicle_type=VEHICLE_TYPES[vehicle_type])


def moving_object_alert(position: LatLng, heading_deg: float, speed_mps: float,
                        affected_types: Iterable[str]):
    return "moving_object_alert", rx_commands_pb2.MovingObjectAlert(
        position=_latlng(position), heading_deg=heading_deg, speed_mps=speed_mps,
        affected_vehicle_types=[VEHICLE_TYPES[t] for t in affected_types])


class SendResult(NamedTuple):
    ok: bool
    seq: int            # 0 for the course, which has no seq
    error: str


class CommandSender:
    """Publishes host messages and owns the per-team RxCommand.seq counter.

    ``seen_seq(team_id)`` returns the highest command seq observed on the
    broker for a team (the monitor sees our own commands come back too).
    """

    def __init__(self, publish: PublishFn, seen_seq: Callable[[str], int]):
        self._publish = publish
        self._seen_seq = seen_seq
        self._sent: Dict[str, int] = {}

    def next_seq(self, team_id: str) -> int:
        return max(self._sent.get(team_id, 0), self._seen_seq(team_id)) + 1

    def send_course(self, course) -> SendResult:
        err = self._publish(COURSE_TOPIC, course.SerializeToString(), True)
        return SendResult(err is None, 0, err or "")

    def clear_course(self) -> SendResult:
        """Remove the retained course from the broker (empty retained payload)."""
        err = self._publish(COURSE_TOPIC, b"", True)
        return SendResult(err is None, 0, err or "")

    def send_command(self, team_id: str, body: Tuple[str, object]) -> SendResult:
        if not team_id:
            return SendResult(False, 0, "no team selected")
        name, msg = body
        seq = self.next_seq(team_id)
        command = rx_commands_pb2.RxCommand(team_id=team_id, seq=seq, sent_at=now_ts())
        getattr(command, name).CopyFrom(msg)
        err = self._publish(command_topic(team_id), command.SerializeToString(), False)
        if err is not None:
            return SendResult(False, seq, err)
        self._sent[team_id] = seq
        return SendResult(True, seq, "")
