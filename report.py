#!/usr/bin/env python3
"""GCS reporter for RobotX 2026 RoboCommand (Team Handbook §3.4).

Runs on the team GCS/OCS. It finds the course RoboCommand host, connects to
its MQTT broker over TCP 1883, and follows the run start sequence:

  1. List every course host IP (65.2 / 66.2 / 67.2 / 68.2).
  2. Find which course network this GCS got a DHCP address on, and confirm
     that host answers on TCP 1883. That host is the broker.
  3. Subscribe to robocommand/robotx/course and .../<team_id>/command.
  4. Validate RxCourse, then publish one RunDeclaration.
  5. Publish a Heartbeat per declared vehicle at 2 Hz.
  6. Verify RunStart.declaration_seq and record run_id.

Telemetry comes from one of:
  --simulate     vehicles orbit the course centre (for testing the host UI)
  stdin (default) one JSON object per line, e.g.
      {"vehicle_id": "USV1", "lat": 1.2806, "lng": 103.8557,
       "heading_deg": 90, "spd_mps": 1.5, "state": "AUTO",
       "current_task": "SAFE_PASSAGE"}
  or import GcsReporter and call update() from your own nav code.

Examples:
  python3 report.py --team ITSN --vehicle USV1 --vehicle UAV1 --simulate
  python3 report.py --course alpha --team ITSN --vehicle USV1 < nav.jsonl
  python3 report.py --host 10.0.70.5 --team ITSN --vehicle USV1   # demo
"""

import argparse
import json
import logging
import math
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

import paho.mqtt.client as mqtt

from robocommand_ui.course_validation import validate_course
from robocommand_ui.courses import COURSES, MQTT_PORT, TOPIC_ROOT, detect_course, resolve_host
from robocommand_ui.proto_helper import (
    FLIGHT_STR_MAP, STATE_STR_MAP, TASK_STR_MAP, TIER_STR_MAP, TYPE_STR_MAP,
    common_pb2, now_ts, parse_mqtt_payload, rx_common_pb2, rx_reports_pb2, rx_requests_pb2,
)
from robocommand_ui.sequence_tracker import SequenceTracker

log = logging.getLogger("report")

HEARTBEAT_PERIOD_S = 0.5            # 2 Hz per vehicle (§3.4.11)
MAX_MSGS_PER_S = 5                  # per system, i.e. per vehicle (§3.4 publishing limit)

TELEMETRY_FIELDS = {
    "lat", "lng", "spd_mps", "heading_deg", "roll_deg", "pitch_deg",
    "altitude_hae_m", "depth_m", "state", "current_task", "flight_phase",
}


def infer_vehicle_type(vehicle_id: str) -> int:
    upper = vehicle_id.upper()
    for prefix in ("USV", "UUV", "UAV"):
        if upper.startswith(prefix):
            return TYPE_STR_MAP[f"TYPE_{prefix}"]
    return rx_common_pb2.TYPE_UNKNOWN


def enum_value(table: Dict[str, int], prefix: str, value) -> int:
    """Accept an enum as int, 'AUTO' or 'STATE_AUTO'."""
    if isinstance(value, int) and not isinstance(value, bool):
        if value not in table.values():
            raise ValueError(f"unknown value {value} (expected one of {sorted(table.values())})")
        return value
    name = str(value).upper()
    if not name.startswith(prefix):
        name = prefix + name
    if name not in table:
        raise ValueError(f"unknown value '{value}' (expected one of {', '.join(table)})")
    return table[name]


class GcsReporter:
    """One MQTT connection from the GCS to the course RoboCommand host."""

    def __init__(self, host: str, team_id: str, vehicles: Dict[str, int],
                 tiers: Tuple[int, int, int, int], geofence: List[Tuple[float, float]],
                 port: int = MQTT_PORT,
                 client_factory: Callable[[], mqtt.Client] = None,
                 on_course: Callable[[object], None] = None):
        self.host = host
        self.port = port
        self.team_id = team_id
        self.vehicles = dict(vehicles)
        self.tiers = tiers
        self.geofence = list(geofence)
        self.seq = SequenceTracker()
        self.course = None
        self.declaration_seq: Optional[int] = None
        self.run_id: Optional[int] = None
        self.connected = threading.Event()
        self._on_course_cb = on_course
        self._lock = threading.Lock()           # telemetry
        self._pub_lock = threading.RLock()      # seq allocation + publish + declaration
        self._telemetry: Dict[str, dict] = {vid: {} for vid in vehicles}
        self._warned_no_fix = set()
        self._sent_times: Dict[str, List[float]] = {}     # system -> publish times
        self._stop = threading.Event()
        self._hb_thread: Optional[threading.Thread] = None

        factory = client_factory or (lambda: mqtt.Client(mqtt.CallbackAPIVersion.VERSION2))
        self._client = factory()
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=10)

    # ---------------- lifecycle ----------------

    def start(self) -> None:
        log.info("Connecting to RoboCommand %s:%d as team %s", self.host, self.port, self.team_id)
        self._client.connect_async(self.host, self.port, keepalive=30)
        self._client.loop_start()
        self._hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._hb_thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._hb_thread:
            self._hb_thread.join(timeout=2)
        self._client.disconnect()
        self._client.loop_stop()

    # ---------------- telemetry input ----------------

    def update(self, vehicle_id: str, **fields) -> None:
        """Set the latest telemetry for a vehicle. Thread-safe.

        Enum fields accept ints or names ('AUTO', 'SAFE_PASSAGE', ...).
        """
        if vehicle_id not in self.vehicles:
            raise ValueError(f"vehicle '{vehicle_id}' was not declared "
                             f"(declared: {', '.join(self.vehicles)})")
        unknown = set(fields) - TELEMETRY_FIELDS
        if unknown:
            raise ValueError(f"unknown telemetry field(s): {', '.join(sorted(unknown))}")
        clean = dict(fields)
        if "state" in clean:
            clean["state"] = enum_value(STATE_STR_MAP, "STATE_", clean["state"])
        if "current_task" in clean:
            clean["current_task"] = enum_value(TASK_STR_MAP, "TASK_", clean["current_task"])
        if "flight_phase" in clean:
            clean["flight_phase"] = enum_value(FLIGHT_STR_MAP, "FLIGHT_PHASE_", clean["flight_phase"])
        for key in TELEMETRY_FIELDS - {"state", "current_task", "flight_phase"}:
            if key in clean:
                clean[key] = float(clean[key])
        if "lat" in clean and not -90.0 <= clean["lat"] <= 90.0:
            raise ValueError(f"lat {clean['lat']} out of range")
        if "lng" in clean and not -180.0 <= clean["lng"] <= 180.0:
            raise ValueError(f"lng {clean['lng']} out of range")
        with self._lock:
            self._telemetry[vehicle_id] = {**self._telemetry[vehicle_id], **clean}

    # ---------------- publishing ----------------

    def declare_once(self) -> bool:
        """Declare unless already declared. Called from the paho and heartbeat threads."""
        with self._pub_lock:
            if self.declaration_seq is not None:
                return True
            return self.declare()

    def declare(self) -> bool:
        """Publish a new RunDeclaration (always; use declare_once for the normal flow)."""
        with self._pub_lock:
            return self._declare_locked()

    def _declare_locked(self) -> bool:
        if not self.connected.is_set():
            return False
        request = rx_requests_pb2.RxRequest(
            team_id=self.team_id,
            seq=self.seq.get_next_request_seq(),
            sent_at=now_ts(),
            run_declaration=rx_requests_pb2.RunDeclaration(
                vehicle_ids=list(self.vehicles),
                task1_tier=self.tiers[0], task2_tier=self.tiers[1],
                task3_tier=self.tiers[2], task4_tier=self.tiers[3],
                uav_geofence=[common_pb2.LatLng(latitude=a, longitude=b) for a, b in self.geofence],
            ),
        )
        if not self._publish(f"{TOPIC_ROOT}/{self.team_id}/request", request, system=self.team_id):
            return False
        self.declaration_seq = request.seq
        self.run_id = None
        log.info("RunDeclaration seq=%d vehicles=%s", request.seq, list(self.vehicles))
        return True

    def heartbeat(self, vehicle_id: str) -> bool:
        with self._lock:
            t = dict(self._telemetry[vehicle_id])
        if "lat" not in t or "lng" not in t:
            if vehicle_id not in self._warned_no_fix:
                log.warning("%s has no position yet; heartbeat held until telemetry arrives", vehicle_id)
                self._warned_no_fix.add(vehicle_id)
            return False
        hb = rx_reports_pb2.Heartbeat(
            state=t.get("state", common_pb2.STATE_MANUAL),
            position=common_pb2.LatLng(latitude=t["lat"], longitude=t["lng"]),
            spd_mps=t.get("spd_mps", 0.0),
            heading_deg=t.get("heading_deg", 0.0),
            roll_deg=t.get("roll_deg", 0.0),
            pitch_deg=t.get("pitch_deg", 0.0),
            altitude_hae_m=t.get("altitude_hae_m", 0.0),
            depth_m=t.get("depth_m", 0.0),
            current_task=t.get("current_task", rx_common_pb2.TASK_NONE),
            vehicle_type=self.vehicles[vehicle_id],
            flight_phase=t.get("flight_phase", rx_common_pb2.FLIGHT_PHASE_UNKNOWN),
        )
        return self.publish_report(vehicle_id, "heartbeat", hb)

    def publish_report(self, vehicle_id: str, body_field: str, body) -> bool:
        """Publish any RxReport body (heartbeat, safe_passage, docking, ...).

        Allocation and publish happen under one lock so seqs go out in order,
        and no seq is consumed while disconnected.
        """
        with self._pub_lock:
            if not self.connected.is_set():
                return False
            report = rx_reports_pb2.RxReport(
                team_id=self.team_id,
                vehicle_id=vehicle_id,
                seq=self.seq.get_next_report_seq(vehicle_id),
                sent_at=now_ts(),
            )
            getattr(report, body_field).CopyFrom(body)
            return self._publish(f"{TOPIC_ROOT}/{self.team_id}/{vehicle_id}/report", report,
                                 system=vehicle_id)

    def _publish(self, topic: str, msg, system: str) -> bool:
        """Caller holds _pub_lock."""
        now = time.time()
        recent = [t for t in self._sent_times.get(system, []) if now - t < 1.0] + [now]
        self._sent_times[system] = recent
        if len(recent) > MAX_MSGS_PER_S:
            log.warning("%s publishing %d msgs/s, above the %d/s limit",
                        system, len(recent), MAX_MSGS_PER_S)
        info = self._client.publish(topic, msg.SerializeToString())
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            log.error("publish to %s failed rc=%s", topic, info.rc)
            return False
        return True

    def _heartbeat_loop(self) -> None:
        next_tick = time.monotonic()
        while not self._stop.is_set():
            try:
                if self.declaration_seq is None and self.course is not None:
                    self.declare_once()     # course arrived while disconnected: retry
                if self.declaration_seq is not None:
                    for vid in self.vehicles:
                        self.heartbeat(vid)
            except Exception:
                log.exception("heartbeat tick failed; continuing")
            next_tick += HEARTBEAT_PERIOD_S
            now = time.monotonic()
            if next_tick < now:
                next_tick = now         # after a stall, resume at 2 Hz instead of bursting
            self._stop.wait(next_tick - now)

    # ---------------- MQTT callbacks ----------------

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", False):
            log.error("Broker refused connection: %s", reason_code)
            return
        course_topic = f"{TOPIC_ROOT}/course"
        cmd_topic = f"{TOPIC_ROOT}/{self.team_id}/command"
        # Mark connected first: the retained course can arrive during subscribe.
        self.connected.set()
        client.subscribe(course_topic)
        client.subscribe(cmd_topic)
        log.info("Connected to %s:%d; subscribed to %s and %s",
                 self.host, self.port, course_topic, cmd_topic)
        if self.declaration_seq is not None:
            log.info("Reconnected: keeping declaration seq=%d and run_id=%s (no re-declare)",
                     self.declaration_seq, self.run_id)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self.connected.clear()
        log.warning("Disconnected (rc=%s); paho will reconnect and resubscribe", reason_code)

    def _on_message(self, client, userdata, msg):
        try:
            name, parsed = parse_mqtt_payload(msg.topic, msg.payload)
        except Exception as e:      # never let a bad payload stop reporting
            log.error("parse error on %s: %s", msg.topic, e)
            return
        if parsed is None:
            log.error("rejected malformed payload on %s (%d bytes)", msg.topic, len(msg.payload))
            return
        try:
            if name == "RxCourse":
                self._handle_course(parsed)
            elif name == "RxCommand":
                self._handle_command(parsed)
        except Exception:       # an exception here would end paho's network thread
            log.exception("error handling %s on %s", name, msg.topic)

    def _handle_course(self, course) -> None:
        issues = validate_course(course)
        if issues:
            log.error("RxCourse %s INVALID: %s", course.course_id or "<no id>", "; ".join(issues))
            return
        self.course = course
        log.info("RxCourse %s valid (pinger %d Hz, %d corners)",
                 course.course_id, course.pinger_freq_hz, len(course.corners))
        if self._on_course_cb:
            self._on_course_cb(course)
        self.declare_once()

    def _handle_command(self, command) -> None:
        if command.team_id and command.team_id != self.team_id:
            log.error("ignoring command for team %s", command.team_id)
            return
        self.seq.record_rx_command_seq(command.seq)
        body = command.WhichOneof("body")
        if body == "run_start":
            rs = command.run_start
            if rs.declaration_seq != self.declaration_seq:
                log.error("RunStart declaration_seq=%d does not match our declaration seq=%s; ignoring",
                          rs.declaration_seq, self.declaration_seq)
                return
            self.run_id = rs.run_id
            log.info("RunStart verified: run_id=%d", rs.run_id)
        else:
            log.info("RxCommand seq=%d %s", command.seq, body)


# ---------------- telemetry sources ----------------

def course_centre(course) -> Tuple[float, float, float]:
    """(lat, lng, radius_m) of a circle comfortably inside the course."""
    pts = [(c.latitude, c.longitude) for c in course.corners]
    lat = sum(p[0] for p in pts) / len(pts)
    lng = sum(p[1] for p in pts) / len(pts)
    m_per_deg_lat = 111_320.0
    m_per_deg_lng = m_per_deg_lat * math.cos(math.radians(lat))
    half_extent = min(
        (max(p[0] for p in pts) - min(p[0] for p in pts)) * m_per_deg_lat,
        (max(p[1] for p in pts) - min(p[1] for p in pts)) * m_per_deg_lng,
    ) / 2.0
    return lat, lng, max(5.0, half_extent * 0.5)


def run_simulation(reporter: GcsReporter, stop: threading.Event, speed_mps: float = 1.5) -> None:
    """Orbit every vehicle around the course centre once a valid course arrives."""
    while not stop.is_set() and reporter.course is None:
        stop.wait(0.2)
    if stop.is_set():
        return
    lat0, lng0, radius = course_centre(reporter.course)
    m_per_deg_lat = 111_320.0
    m_per_deg_lng = m_per_deg_lat * math.cos(math.radians(lat0))
    omega = speed_mps / radius
    t0 = time.monotonic()
    ids = list(reporter.vehicles)
    log.info("Simulating %s on a %.0f m orbit around %.6f, %.6f", ids, radius, lat0, lng0)
    while not stop.is_set():
        t = time.monotonic() - t0
        for i, vid in enumerate(ids):
            theta = omega * t + 2 * math.pi * i / len(ids)
            north, east = radius * math.cos(theta), radius * math.sin(theta)
            heading = (math.degrees(math.atan2(math.cos(theta), -math.sin(theta)))) % 360.0
            is_uav = reporter.vehicles[vid] == rx_common_pb2.TYPE_UAV
            reporter.update(
                vid, lat=lat0 + north / m_per_deg_lat, lng=lng0 + east / m_per_deg_lng,
                heading_deg=heading, spd_mps=speed_mps, state="AUTO",
                current_task="SAFE_PASSAGE" if reporter.run_id is not None else "NONE",
                altitude_hae_m=20.0 if is_uav else 0.0,
                flight_phase="AIRBORNE" if is_uav else "UNKNOWN",
            )
        stop.wait(0.1)


def run_stdin(reporter: GcsReporter, stop: threading.Event) -> None:
    """Read JSON-lines telemetry from stdin until EOF or stop."""
    for line in sys.stdin:
        if stop.is_set():
            break
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError("expected a JSON object")
            vid = data.pop("vehicle_id")
            reporter.update(vid, **data)
        except (ValueError, KeyError, TypeError) as e:
            log.error("bad telemetry line %r: %s", line[:120], e)


# ---------------- CLI ----------------

def parse_vehicle(spec: str) -> Tuple[str, int]:
    """'USV1' or 'USV1:UAV' -> (id, VehicleType)."""
    vid, _, vtype = spec.partition(":")
    if not vid:
        raise argparse.ArgumentTypeError(f"bad vehicle '{spec}'")
    vtype_value = enum_value(TYPE_STR_MAP, "TYPE_", vtype) if vtype else infer_vehicle_type(vid)
    if vtype_value == rx_common_pb2.TYPE_UNKNOWN:
        raise argparse.ArgumentTypeError(
            f"can't tell the type of '{vid}'; write it as {vid}:USV, {vid}:UUV or {vid}:UAV")
    return vid, vtype_value


def parse_geofence(text: str) -> List[Tuple[float, float]]:
    """'lat,lng;lat,lng;...' -> closed polygon (closes it if needed)."""
    pts = []
    for pair in text.split(";"):
        lat, lng = (float(x) for x in pair.split(","))
        pts.append((lat, lng))
    if pts and pts[0] != pts[-1]:
        pts.append(pts[0])
    return pts


def choose_host(args) -> str:
    if args.host:
        log.info("Using --host %s", args.host)
        return args.host
    if args.course != "auto":
        host = resolve_host(args.course)
        log.info("Using %s host %s", COURSES[args.course].name, host)
        return host
    det = detect_course()
    for line in det.log:
        log.info(line)
    if det.course is None:
        raise SystemExit("Could not find a course RoboCommand host. Check the GCS got a DHCP "
                         "address on 192.168.65-68.x, or pass --course / --host.")
    return det.course.host


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--course", default="auto", choices=["auto", *COURSES],
                   help="course to report to; 'auto' finds it from this GCS's DHCP address (default)")
    p.add_argument("--host", help="RoboCommand address override (needed for the Team Village demo)")
    p.add_argument("--port", type=int, default=MQTT_PORT)
    p.add_argument("--team", required=True, help="team_id exactly as issued")
    p.add_argument("--vehicle", action="append", required=True, type=parse_vehicle,
                   help="vehicle id, optionally with type: USV1 or USV1:USV (repeatable)")
    p.add_argument("--tiers", default="NONE,NONE,NONE,NONE",
                   help="Task 1-4 tiers, e.g. CORE,ADVANCED,NONE,NONE")
    p.add_argument("--geofence", default="", help="UAV geofence 'lat,lng;lat,lng;...'")
    p.add_argument("--simulate", action="store_true", help="orbit vehicles around the course centre")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    tiers = tuple(enum_value(TIER_STR_MAP, "TIER_", t.strip()) for t in args.tiers.split(","))
    if len(tiers) != 4:
        raise SystemExit("--tiers needs exactly 4 values")
    if common_pb2.TIER_UNKNOWN in tiers:
        raise SystemExit("--tiers must not use UNKNOWN; use NONE for tasks not attempted")
    vehicles = dict(args.vehicle)
    geofence = parse_geofence(args.geofence) if args.geofence else []
    if rx_common_pb2.TYPE_UAV in vehicles.values() and len(geofence) < 4:
        raise SystemExit("a UAV is declared: --geofence needs a closed polygon of at least 4 points")

    reporter = GcsReporter(choose_host(args), args.team, vehicles, tiers, geofence, port=args.port)
    reporter.start()
    stop = threading.Event()
    source = run_simulation if args.simulate else run_stdin
    try:
        source(reporter, stop)
        if not args.simulate:
            log.info("stdin closed; still sending last known telemetry. Ctrl+C to stop.")
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        reporter.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
