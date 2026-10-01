# RoboCommand RobotX 2026 — OCS Qt UI

Operator Control Station (OCS) application for RobotX 2026. It connects to the
RoboCommand MQTT broker, receives course configuration and team commands, and
publishes vehicle-attributed reports on behalf of your fleet.

Per the Team Handbook §3.4, **only the OCS connects to RoboCommand**. This
application is that endpoint — it never connects to vehicles, and it must not
be run on a vehicle.

## What it does

The UI is split into two pages (tabs), plus a connection bar on top and a
message log pinned at the bottom so it stays visible on both pages.

**Page 1 — Monitoring** (read-only, for the big screen)

| Panel | Purpose |
|---|---|
| **Course Map (top-down)** | Big tactical view: course boundary, standard course schematic (pontoons + UAV L/R, Safe Passage, pipeline, Coordinated Logistics platform, seawall), UAV geofence, live vehicle positions with heading vectors, Safe Passage buoys colored by beacon state, and the pipeline survey |
| **Course Configuration** | Decoded `RxCourse`: course_id, pinger frequency, boundary corners, plus a handbook §3.4.9 validity check (closed ring, corner ranges, non-zero pinger frequency) |
| **Vehicle Telemetry** | Read-only, per vehicle: heartbeat activity (ACTIVE / STALE / OFFLINE with age), state, current task, position, speed/heading, attitude, flight phase, report sequence, the task reports it has sent, and the last command addressed to it |
| **Received Commands** | `RxCommand` stream with run state (`IDLE` → `DECLARED` → `ACTIVE`) |
| **Sequence Numbers** | Request sequence, last command sequence, per-vehicle report sequences |

**Page 2 — Sending / Testing**

| Panel | Purpose |
|---|---|
| **Pre-Run Declaration** | `RunDeclaration` with per-task tiers and UAV geofence validation |
| **Send Reports** | Heartbeat (manual or 2 Hz auto), Task 1 Safe Passage, Task 2 Pipeline Survey, Task 3 Docking/Firefighting, Task 3/2 Resource Delivery, Task 4 IncidentAck / ReadinessReport |

**Always visible**

| Panel | Purpose |
|---|---|
| **Connection bar** | Course preset picker (Alpha / Bravo / Charlie / Delta / Team Village), broker host/port, team_id, connect state |
| **Message Log** | Filterable log of everything sent and received |

Protocol rules implemented from the handbook:

- Topic layout `robocommand/robotx/<team_id>/<vehicle_id>/report`, `…/request`, `…/command`, `…/course`
- Per-vehicle report sequence counters that start at 1 and never decrease within a run
- Team-request sequence counter, monotonic across the session
- Commands with a `team_id` that does not match the configured team are ignored
- Malformed protobuf payloads are logged and rejected; the app keeps running
- Automatic reconnect with automatic resubscription after broker loss
- One MQTT connection used for all traffic (no reconnect-per-message)
- Heartbeat rate of 2 Hz via the auto-heartbeat toggle
- UAV geofence must be a closed polygon (first point == last point) and must have at least 4 points when a UAV is declared
- Received `RxCourse` is validated before a run (handbook §3.4.9): boundary must be a closed ring, corners must be in range, pinger frequency must be non-zero. An invalid course is shown and logged rather than silently accepted
- `TIER_NONE` is used to mean "not attempting"; `TIER_UNKNOWN` is never sent deliberately

## Requirements

- Python 3.9+
- PyQt5 5.15+
- paho-mqtt 2.x
- protobuf 5.x (matches the schemas checked in under `robocommand/RobotX_2026`)

```bash
pip install -r requirements.txt
```

## Setup

### 1. Broker

The RoboCommand test environment is already vendored in this repository at
`robocommand/RobotX_2026`. It runs Mosquitto plus a logging server.

```bash
docker compose -f robocommand/RobotX_2026/docker-compose.yml up -d
```

That exposes the broker on `localhost:1883` and starts a test server that
decodes and logs every message that crosses the broker.

If you do not have Docker, a bare Mosquitto works for local development:

```bash
./scripts/dev_broker.sh start     # Mosquitto on 127.0.0.1:1883
./scripts/dev_broker.sh stop
```

### 2. Run the UI

```bash
python3 run_ui.py
```

or with the launcher (checks deps and starts the broker if Docker is present):

```bash
./run_ui.sh
```

### 3. Connect

In the UI:

1. Pick a preset — `Team Village Demo` for integration testing, or the course
   you are actually on (Alpha = `192.168.65.2`, Bravo = `192.168.66.2`,
   Charlie = `192.168.67.2`, Delta = `192.168.68.2`).
2. Set **Team ID** to the exact identifier issued by RoboNation.
3. Press **Connect**.

On a competition course the OCS interface must be a DHCP client; the course
subnets are `192.168.65–68.0/24` with the RoboCommand host as the default
gateway. Do not configure a static address, and do not bridge that interface
with any other network.

### 4. Team Village test sequence (handbook §3.4.14)

```bash
# Terminal 1 — test server (already running via docker compose above)

# Terminal 2 — publish a retained course as RoboCommand would on startup
docker compose -f robocommand/RobotX_2026/docker-compose.yml run --rm rc-test \
  python test_client.py course --course-id ALPHA --pinger-freq-hz 25000
```

Then, in the UI:

1. Confirm the course panel and course map populate.
2. Set your team_id and press **Connect**.
3. Enter your vehicles in **Pre-Run Declaration** (e.g. `USV1, UUV1, UAV1`),
   pick a tier for each task, enter the UAV geofence, press
   **Send RunDeclaration**.
4. Enable **Start Auto Heartbeat (2 Hz)** so every declared vehicle reports
   `STATE_AUTO`.
5. Simulate RoboCommand starting the run:

   ```bash
   docker compose -f robocommand/RobotX_2026/docker-compose.yml run --rm rc-test \
     python test_client.py run-start --declaration-seq 1 --run-id 42
   ```

   The run state panel should move to `ACTIVE` and record the run_id.
6. Exercise Task 4 commands and the corresponding UI responses:

   ```bash
   # RoboCommand -> OCS: assistance request
   docker compose -f robocommand/RobotX_2026/docker-compose.yml run --rm rc-test \
     python test_client.py assistance-request --vehicle-type uuv --lat 1.2806 --lng 103.8557
   ```

   Then send `IncidentAck` and `ReadinessReport` from the UI's
   **Task 3/4 Reports** tab, referencing the command sequence shown in the
   command log.

7. Disconnect and reconnect — the UI must recover and resubscribe on its own.

Note that `test_client.py` defaults to team `RNRX`; when testing alongside
another team in the Village you must set `--team <your_id>` on every
subcommand so traffic stays distinguishable.

## Running the tests

The tests start their own throwaway Mosquitto broker on port 18830 and drive
the real UI headless.

```bash
./scripts/run_tests.sh
```

or individually:

```bash
python3 tests/test_course_validation.py  # course validity rules (no broker needed)
python3 tests/test_ui_integration.py     # end-to-end protocol/UI checks
python3 tests/test_robustness.py         # malformed payloads, wrong-team
                                         # commands, 2 Hz rate, reconnect
```

The compose-stack suite drives the UI against the broker the README tells an
operator to run, using the vendored `rc_test/test_client.py` as the
RoboCommand-side peer. Start that broker first:

```bash
docker compose -f robocommand/RobotX_2026/docker-compose.yml up -d broker
python3 tests/test_compose_stack.py
```

Note that `test_client.py course` publishes a 4-corner boundary whose first
and last points differ, so it is deliberately invalid under §3.4.9. The
compose-stack test asserts that the UI decodes it *and* flags it rather than
silently accepting it.

## Project layout

```
run_ui.py                     Entry point
requirements.txt              Python dependencies
scripts/dev_broker.sh         Local Mosquitto for development
scripts/run_tests.sh          Runs the whole test suite
tests/                        Headless integration + unit tests
robocommand_ui/
  proto_helper.py             Protobuf imports + topic parsing + enum helpers
  sequence_tracker.py         Per-vehicle and team sequence counters
  mqtt_worker.py              MQTT client in a QThread; publishes/receives
  main_window.py              Two pages (Monitoring / Sending) + signal wiring
  widgets/
    connection_bar.py         Broker/team configuration + status
    course_panel.py           Decoded RxCourse display + validation
    course_map.py             Top-down tactical map (boundary, schematic,
                              geofence, vehicles, Safe Passage buoys, pipeline)
    vehicle_monitor.py        Read-only per-vehicle telemetry monitor
    run_declaration_panel.py  RunDeclaration editor
    commands_reports_panel.py Incoming commands + report senders
    sequence_panel.py         Sequence counters and run state
    log_panel.py              Filterable message log
```

## Troubleshooting

- **Course panel shows INVALID** — the retained `RxCourse` is not usable per §3.4.9.
  Typical causes: the boundary is not a closed polygon (first corner must equal
  last), a corner is outside ±90/±180, or `pinger_freq_hz` is zero. RoboCommand
  validates the UAV geofence against the course boundary, so an unusable
  boundary would stall the run at RunStart. Ask course staff to republish a
  valid course, or for Team Village testing publish one yourself:
  ```bash
  docker compose -f robocommand/RobotX_2026/docker-compose.yml run --rm rc-test \
    python test_client.py course --course-id ALPHA --pinger-freq-hz 25000 \
      --corner-lats 1.280329 1.2804716 1.2808993 1.2807567 1.280329 \
      --corner-lngs 103.8556869 103.8554529 103.8557337 103.8559743 103.8556869
  ```
- **OCS gets no IP address** — confirm the right Ethernet interface is in DHCP
  mode and that IP forwarding, bridges, and Internet sharing are disabled on it.
- **Address assigned but cannot connect** — confirm the gateway is the course
  RoboCommand address and that the application targets that address. Course
  networks deliberately have no Internet access, so `ping` of an external host
  is not a valid test.
- **RoboCommand ignores a publication** — check topic spelling and capitalization,
  that the topic carries your assigned `team_id`, that a report's topic
  `vehicle_id` matches `RxReport.vehicle_id`, that the top-level envelope type is
  correct, and that exactly one `oneof` body is populated.
- **Command received but response rejected** — confirm the response references the
  correct `command_seq`, is attributed to the intended vehicle, and that report
  sequence counters were not reset mid-run.
- **Parse errors in the log** — the payload is not a valid protobuf for that
  topic's schema, or a different schema version is in use. Use the competition
  schema release unchanged.
