# RoboCommand RobotX 2026 — Host Monitor + GCS Reporter

Two programs for the RobotX 2026 communications protocol (Team Handbook §3.4):

| Program | Runs on | Does |
|---|---|---|
| `run_ui.py` — **Host Monitor** (Qt) | The course RoboCommand host, e.g. `192.168.65.2` | Listens to everything teams report and shows each team's boat movement |
| `report.py` — **GCS Reporter** | The team GCS/OCS | Finds the course host, connects to it, declares the run, sends 2 Hz heartbeats |

```
 Team vehicles ⇄ Team GCS (report.py) ──MQTT/TCP 1883──▶ RoboCommand host 192.168.65.2
                                                          broker + Host Monitor (run_ui.py)
```

| Course | Team network (DHCP) | RoboCommand host |
|---|---|---|
| Alpha | 192.168.65.0/24 | 192.168.65.2 |
| Bravo | 192.168.66.0/24 | 192.168.66.2 |
| Charlie | 192.168.67.0/24 | 192.168.67.2 |
| Delta | 192.168.68.0/24 | 192.168.68.2 |
| Team Village demo | VLAN 70 | from the demo instructions (`--host`) |

## Requirements

- Python 3.9+, PyQt5 5.15+, paho-mqtt 2.x
- protobuf **at least** the version the vendored gencode under
  `robocommand/RobotX_2026/gen/python` was built with (currently 7.x). An older
  runtime fails at import with `VersionError: ... Runtime version cannot be older`.

```bash
pip install -r requirements.txt
```

## Host Monitor (on 192.168.65.2)

```bash
python3 run_ui.py        # or ./run_ui.sh, which also starts a local broker if none is running
```

Leave the preset on **This host (localhost)** and press **Connect**. The course
presets connect to a course broker from another machine instead.

The monitor subscribes to `robocommand/robotx/#` and **never publishes**, so it
cannot interfere with a run. It shows:

| Panel | Shows |
|---|---|
| **Course Map** | Course boundary and schematic, every reporting vehicle labelled `TEAM/VEHICLE` with heading and movement trail, the declared UAV geofence, and the latest Safe Passage / Pipeline reports |
| **Course Configuration** | Retained `RxCourse` and its §3.4.9 validity |
| **Teams on this course** | Per team: run state (IDLE → DECLARED → ACTIVE, or DECL MISMATCH when `RunStart.declaration_seq` does not match the declaration), live/declared vehicles, tiers, run_id, request/command seq |
| **Vehicle Telemetry** | Per vehicle: ACTIVE / STALE / OFFLINE, heartbeat rate vs the required 2 Hz, state, current task, position, speed/heading, attitude, flight phase, report seq health (missed / out of order / restarts), task report counts |
| **Message Log** | Requests, commands, task reports, task attempt start/end, and every rejected or malformed message |

The **Show** filter in the status strip narrows the map and cards to one team.

Checks applied to incoming traffic:

- Topic `team_id`/`vehicle_id` must match the decoded message, or it is rejected
- Payloads that don't decode as the topic's envelope are rejected and logged
- `RxReport.seq` per vehicle: gaps, repeats/regressions, and restarts at 1 are flagged
- `current_task` transitions are logged as task attempt start/end

## GCS Reporter (on the team GCS)

```bash
# Auto: list all course hosts, find the course this GCS got a DHCP address on,
# confirm that host answers on TCP 1883, and report to it.
python3 report.py --team ITSN --vehicle USV1 --vehicle UUV1 --tiers CORE,ADVANCED,NONE,NONE < nav.jsonl

# Or pin the course / host
python3 report.py --course bravo --team ITSN --vehicle USV1 < nav.jsonl
python3 report.py --host 10.0.70.5 --team ITSN --vehicle USV1 < nav.jsonl   # Team Village demo

# Test the host monitor without vehicles: orbit the course centre
python3 report.py --course local --team ITSN --vehicle USV1 --vehicle UUV1 --simulate
```

Course auto-detection logs each step:

```
Course hosts: Course Alpha=192.168.65.2, Course Bravo=192.168.66.2, ...
Local addresses: lo=127.0.0.1, eth0=192.168.65.37, wlan0=192.168.10.75
eth0 192.168.65.37 is on Course Alpha network 192.168.65.0/24
192.168.65.2:1883 reachable -> using Course Alpha
```

If no interface is on a course network, every host is probed in turn.

After connecting it follows the run start sequence: subscribe to the course and
its own command topic, validate `RxCourse`, publish one `RunDeclaration`, send a
heartbeat per declared vehicle at 2 Hz, then verify `RunStart.declaration_seq`
and record `run_id`. It reconnects and resubscribes on its own.

**Telemetry input:** one JSON object per line on stdin. Enum fields take names
or numbers; omitted fields keep their last value.

```json
{"vehicle_id": "USV1", "lat": 1.2806, "lng": 103.8557, "heading_deg": 90, "spd_mps": 1.5,
 "state": "AUTO", "current_task": "SAFE_PASSAGE"}
{"vehicle_id": "UAV1", "lat": 1.2807, "lng": 103.8558, "altitude_hae_m": 20, "flight_phase": "AIRBORNE"}
```

Fields: `lat lng spd_mps heading_deg roll_deg pitch_deg altitude_hae_m depth_m state current_task flight_phase`.
A vehicle's heartbeats start once it has a position.

**From your own code** (e.g. a ROS node), skip stdin:

```python
from report import GcsReporter
r = GcsReporter("192.168.65.2", "ITSN", {"USV1": 1}, tiers, geofence)
r.start()
r.update("USV1", lat=..., lng=..., heading_deg=..., state="AUTO")
r.publish_report("USV1", "safe_passage", safe_passage_report)   # any RxReport body
```

Declaring a UAV requires `--geofence "lat,lng;lat,lng;..."` (closed automatically,
at least 4 points). `--tiers` must not use `UNKNOWN`; use `NONE` for tasks not attempted.

## Local testing

```bash
./scripts/dev_broker.sh start                                  # mosquitto on 127.0.0.1:1883
python3 run_ui.py                                              # host monitor, connect to localhost
python3 report.py --course local --team ITSN --vehicle USV1 --simulate
```

`--simulate` waits for a valid retained `RxCourse`. Publish one as RoboCommand would:

```bash
docker compose -f robocommand/RobotX_2026/docker-compose.yml run --rm rc-test \
  python test_client.py course --course-id ALPHA --pinger-freq-hz 25000 \
    --corner-lats 1.280329 1.2804716 1.2808993 1.2807567 1.280329 \
    --corner-lngs 103.8556869 103.8554529 103.8557337 103.8559743 103.8556869
```

## Running the tests

```bash
./scripts/run_tests.sh                 # PYTHON=python3.10 ./scripts/run_tests.sh to pick an interpreter
```

| Suite | Needs |
|---|---|
| `test_course_validation.py`, `test_fleet_state.py`, `test_report.py` | nothing |
| `test_host_loopback.py` — report.py → host UI end to end through an in-process broker | nothing (headless Qt) |
| `test_live_broker.py` — `report.py --simulate` subprocess → real broker → host UI, incl. reconnect | a broker on `BROKER_HOST:BROKER_PORT` (default `127.0.0.1:1883`); skipped otherwise |

## Project layout

```
run_ui.py                     Host Monitor entry point
report.py                     GCS Reporter (CLI + GcsReporter class)
robocommand_ui/
  courses.py                  Course table, host resolution, DHCP-based course detection
  course_validation.py        RxCourse checks (§3.4.9)
  fleet_state.py              What every team/vehicle reported: trails, rate, seq, run state
  proto_helper.py             Protobuf imports + payload parsing + enum helpers
  sequence_tracker.py         Outgoing sequence counters (used by report.py)
  mqtt_worker.py              Listen-only MQTT client in a QThread
  main_window.py              Host Monitor window + signal wiring
  widgets/
    connection_bar.py         Broker selection + status
    course_panel.py           Decoded RxCourse display + validation
    course_map.py             Top-down map with vehicles, trails, geofence, task overlays
    teams_panel.py            Per-team run status
    vehicle_monitor.py        Per-vehicle telemetry cards
    log_panel.py              Filterable message log
tests/                        Unit, loopback and live-broker tests
```

## Troubleshooting

- **report.py: "Could not find a course RoboCommand host"**: the GCS has no DHCP
  address on 192.168.65–68.x, or the host doesn't answer on TCP 1883. Check that
  the right interface is in DHCP mode, with no static address, bridge or Internet
  sharing. Or pass `--course` / `--host`.
- **report.py holds heartbeats ("no position yet")**: no telemetry has arrived
  for that vehicle. Send at least `lat` and `lng`.
- **report.py never declares**: the retained `RxCourse` is missing or invalid
  (the log says which). It declares as soon as a valid course arrives.
- **Host shows a team as DECL MISMATCH**: RoboCommand's `RunStart.declaration_seq`
  doesn't match the team's latest `RunDeclaration` seq.
- **Host shows rate below 2 Hz or STALE**: heartbeats are late or lost between
  the GCS and the host. Check the GCS link and the report.py log.
- **Course panel shows INVALID**: the boundary isn't a closed polygon, a corner
  is out of range, or `pinger_freq_hz` is zero. The publisher must resend a valid course.
- **Parse errors / [REJECT] in the host log**: a payload isn't valid protobuf
  for its topic, or a topic's team/vehicle doesn't match the message body.
