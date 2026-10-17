# Host Guide — running RoboCommand on 192.168.65.2

How to run the course host side on this laptop: the MQTT broker and the host
console (`run_ui.py`). The console both monitors the teams and publishes the
RoboCommand messages (course, RunStart, Task 4) from its tabs — see **2.3**.
`test_client.py` (section 3) is only needed for faking the GCS side.

```
 GCS (nala2-report)  ──MQTT/TCP 1883──▶  THIS LAPTOP 192.168.65.2
 ros2 run nala2_report report             mosquitto broker  +  run_ui.py (monitor)
                                          test_client.py    (you, acting as RoboCommand)
```

All commands below run from the repo root:

```bash
cd ~/github/barunastra-its/RoboCommand-RobotX-UI-ITSN
```

---

## 1. One-time setup

| Step | Command | Why |
|---|---|---|
| Broker as a system service | `sudo ./scripts/setup_host_broker.sh` | Installs mosquitto, listens on `0.0.0.0:1883`, anonymous, starts on boot. Undo: `sudo ./scripts/setup_host_broker.sh remove` |
| DHCP for team GCSs | `sudo ./scripts/dhcp/install_dhcp.sh` (`IFACE=… ` for another port than `enp12s0`) | Serves Course Alpha `192.168.65.0/24`, Bravo `.66`, Charlie `.67`, Delta `.68` and Demo `.70` (VLAN 70) (teams get `.15–.254`). dhcpd answers only on the subnet of the wired IP, and a NetworkManager hook restarts it when the link comes up, so **changing course = set the wired IP to that course's `.2`** (e.g. `nmcli con mod robocommand ipv4.addresses 192.168.66.2/24 && nmcli con up robocommand`). Undo: `sudo ./scripts/dhcp/install_dhcp.sh remove` |
| Python | use `python3.10` (alias `py310`) | The vendored protobuf code needs protobuf ≥ 7.35. `python3.10` has 7.36; plain `python3` (3.12) has 6.33 and fails with `VersionError` |

## 2. Every session

### 2.1 Check the broker

```bash
systemctl is-active mosquitto          # must print: active
sudo systemctl start mosquitto         # if it doesn't
```

### 2.2 Start the host monitor

```bash
python3.10 run_ui.py
```

`run_ui.py` takes **no command-line parameters**. Everything is set in the window:

| Control (header) | Meaning |
|---|---|
| Preset | `This host (localhost)` when running on 192.168.65.2 (normal). `Course Alpha/Bravo/Charlie/Delta (….2)` to watch a course broker from another machine |
| Host / Port | Broker address and port, filled by the preset (default `localhost` / `1883`) |
| Connect / Disconnect | Start / stop the broker link. Listens on `robocommand/robotx/#`; publishes only from the send buttons in the tabs |
| `● Broker connected` | This monitor's link to the broker — **not** the GCS |
| `All teams` | Team filter for the map and vehicle cards |

| Status (header chips) | Meaning |
|---|---|
| `COURSE ALPHA` | Retained RxCourse received; red `INVALID` if it fails §3.4.9 |
| `ITSN DECLARED` / `ACTIVE · RUN 1` | Run state of the team on the course |
| `· LINK LOST 2m05s` | The GCS sent heartbeats, then stopped |
| `· NO HEARTBEAT 8m00s` | The GCS declared but never sent a heartbeat (vehicles not publishing) |
| `2/3 LIVE` | Vehicles with a heartbeat in the last 2.5 s |

Map: scroll = zoom, drag = pan, **Shift+drag** = rotate, compass (top right) = back to north-up,
double-click or **Fit** = re-fit, **Trails** = toggle tracks,
**Clear** = remove the trails and Task 1/2 overlays of the team shown (all teams when *All teams*);
boats stay on the map. RunStart does the same for its team automatically.

**Light / Dark mode** (right end of the tab bar) switches the theme; light is the default and
the choice is remembered.

`./run_ui.sh` does the same but also installs missing deps and starts a broker if none is
listening. It calls `python3`, so prefer `python3.10 run_ui.py` on this laptop.

### 2.3 Acting as RoboCommand from the tabs (no `rc` terminal)

| Tab | Steps | Same as |
|---|---|---|
| **Course** | Pick a preset in the **Presets** list on the left (built-in: `Danau 8`, `Promontory SG`): its corners, pinger and map centre fill in. **Course ID** is filled from the course this host serves (its address: `192.168.65.2` → `ALPHA`, `.66.2` → `BRAVO`, `.67.2` → `CHARLIE`, `.68.2` → `DELTA`, `.70.2` → `DEMO`); **This host** puts it back after an edit. **Pinger frequency** is a plain number in Hz → **Publish course (retained)**; *Last published* under the button shows when. **+ Add preset** saves the fields as a new preset (asks a name); **Update preset** overwrites the loaded one without asking (enabled once you change something); **Delete preset** removes a saved one. Saved in `~/.config/robocommand_ui/course_presets.json`. The ring is closed for you | `rc course …` |
| **Run start** | When the GCS declares, the team appears as **DECLARED** (preselected) → set Run ID → **Allow start**. Enabled only when **every declared vehicle is LIVE and in AUTO** (column *Live+Auto* `n/n`); otherwise the panel lists what is missing (e.g. `USV1 MANUAL (needs AUTO)`, `UAV1 no heartbeat`). On RunStart the team's trails and Task 1/2 overlays are cleared from the map, so every run starts on a clean map | `rc run-start --team ITSN --declaration-seq <seq> --run-id <n>` |
| **Run start → End run** | Run over (time up, judge's call) → select the ACTIVE team → **End run** → confirm. Nothing is sent (the handbook has no run-end message); the run log is saved to `~/.local/share/robocommand_ui/runs/<date>_<team>_run<id>.log` (plus a `.json` replay) and the team shows **ENDED**. The run appears under **Finished runs** by Run ID. Ask the GCS for the next run (`ros2 service call /nala2_report/new_run std_srvs/srv/Trigger`); its new declaration shows as DECLARED with the next Run ID suggested | — |
| **Run start → Finished runs** | Select a Run ID → **Replay** (or double-click): the course, UAV geofence, task overlays and every vehicle's track for that run, with Play/Pause, a timeline and 1×–50× speed. **Open log** opens the text log | — |
| **Run start → Reset run ID & seq** | Bottom of the panel, enabled only between runs (DECLARED or ENDED). Next Run ID back to 1 and this team's command seq back to 1 — e.g. at the start of a new day. Do it after the team's new declaration (or `new_run`): until then the GCS drops a repeated seq as a duplicate | — |
| **Task 4 → Core** | Vehicle type + point → **Send assistance request**. When the ReadinessReport arrives, *Vehicle ID* and *Report seq R* fill themselves in → **Send readiness confirm** | `assistance-request`, `readiness-confirm` |
| **Task 4 → Advanced** | Type + centre + radius → **Send keep-out zone**; later **Send all clear** | `keep-out-zone`, `all-clear` |
| **Task 4 → Disruptive** | Point + heading + speed + affected types → **Send moving object alert**; send again to move it | `moving-object-alert` |

- Positions default to the course centre; each shows *Inside / Outside the course*.
- **Boundary map** (Course tab, right): the **Centre** fields follow the map as you drag or zoom
  it, so they always show where you are; or type a lat/lng → **Go** (or Enter) to jump. Click the
  satellite map to drop a corner — it fills the table; click an edge to insert one, drag a pin to
  move it, right-click a pin to delete it, wheel to zoom, **Shift+drag** to rotate; the compass
  (top right) turns it back to north-up. Editing the table moves the pins.
  **Fit corners** zooms to the pins, **Clear pins** removes them. Loading a preset centres the map.
- **Imagery offline:** the course network has no Internet. Open the Course tab over your course
  once while online; tiles are cached in `~/.cache/robocommand_ui/tiles` and show offline. Without
  them the maps fall back to a grid (pinning still works). `ROBOCOMMAND_MAP_TILES=0` turns imagery off.
- **Sent commands** (Task 4) lists every command with its seq and the team's answer:
  `WAITING ACK` → `ACKED USV1 · EN ROUTE` → `READY USV1 R=n` → `CONFIRMED`.
- Seq continues across all tabs (RunStart, then Task 4) and never restarts while the app
  runs, so the one-session rule of 4.2 is automatic.
- Every send is logged on the Map tab as `[SENT] ITSN seq=n …`.

Sections 3–4 below describe the same messages with `test_client.py`, which you still need
only for faking the GCS side (3.6).

---

## 3. Publishing as RoboCommand — `test_client.py`

### 3.1 PYTHONPATH

`test_client.py` imports the generated protobuf modules (`common_pb2`, `robotx/…`) from
`robocommand/RobotX_2026/gen/python`. That folder is not installed as a package, so put it on
`PYTHONPATH` for the command:

```bash
PYTHONPATH=robocommand/RobotX_2026/gen/python python3.10 robocommand/RobotX_2026/rc_test/test_client.py <global options> <subcommand> <subcommand options>
```

Shortcut for this shell session (all examples below use it):

```bash
alias rc='PYTHONPATH=robocommand/RobotX_2026/gen/python python3.10 robocommand/RobotX_2026/rc_test/test_client.py --broker localhost'
```

Without a subcommand (`rc` alone) it opens an interactive prompt where you type subcommands
one after another on the same connection.

### 3.2 Global options — go **before** the subcommand

| Option | Default | Meaning |
|---|---|---|
| `--broker HOST` | `$BROKER_HOST` or `localhost` | Broker to publish to. On this laptop: `localhost` |
| `--port PORT` | `$BROKER_PORT` or `1883` | Broker TCP port |

`rc --broker localhost course …` ✔ `rc course --broker localhost …` ✘ (argparse error)

### 3.3 Course — draws the map (do this first)

```bash
rc course --course-id ALPHA --pinger-freq-hz 25000 \
  --corner-lats -7.261 -7.261 -7.265 -7.265 -7.261 \
  --corner-lngs 112.791 112.795 112.795 112.791 112.791
```

| Option | Default | Meaning |
|---|---|---|
| `--course-id ID` | `RX2026-A` | Course name shown in the UI and sent to the GCS |
| `--pinger-freq-hz HZ` | `27000` | Acoustic pinger frequency (integer Hz, must be non-zero) |
| `--corner-lats LAT …` | `21.310 21.310 21.305 21.305` | Boundary latitudes in order around the course |
| `--corner-lngs LNG …` | `-157.890 -157.884 -157.884 -157.890` | Boundary longitudes, same count and order as the lats |

- Published **retained** on `robocommand/robotx/course`: it stays on the broker, the GCS gets it
  on connect, and the monitor redraws it on reconnect.
- The **first and last corner must be the same point** (closed ring), otherwise the course is
  INVALID and the GCS will not declare. The defaults are open *and* in Hawaii — always pass
  your own corners.
- Check what is retained: `rc receive-course` (no options).
- Remove the retained course: `mosquitto_pub -h localhost -t robocommand/robotx/course -r -n`

### 3.4 RunStart — moves the team to ACTIVE

Send after the team shows **DECLARED** (hover the team row for its declaration seq).

```bash
rc run-start --team ITSN --declaration-seq 1 --run-id 1
```

| Option | Default | Meaning |
|---|---|---|
| `--team ID` | `RNRX` | Team to start. **Always pass `--team ITSN`** |
| `--declaration-seq N` | `1` | Must equal the `seq` of the team's RunDeclaration, or the GCS ignores it and the UI shows `DECL MISMATCH` |
| `--run-id N` | `1` | Run number the GCS records |

### 3.5 Task 4 commands (RoboCommand → GCS)

Published on `robocommand/robotx/<team>/command`. Every one takes `--team` (default `RNRX`).

| Subcommand | Option | Default | Meaning |
|---|---|---|---|
| `assistance-request` (Core) | `--lat` / `--lng` | `1.2806142` / `103.8557120` | Where the vehicle must go and loiter |
| | `--vehicle-type` | `usv` | `usv`, `uuv`, `uav` |
| `keep-out-zone` (Advanced) | `--lat` / `--lng` | `1.2806142` / `103.8557120` | Hazard centre |
| | `--radius-m` | `15.0` | Keep-out radius in metres |
| | `--vehicle-type` | `usv` | `unknown`, `usv`, `uuv`, `uav` |
| `all-clear` (Advanced) | `--vehicle-type` | `usv` | Vehicle type the keep-out zone is lifted for |
| `moving-object-alert` (Disruptive) | `--lat` / `--lng` | `1.2806142` / `103.8557120` | Moving object position |
| | `--heading` | `0.0` | Object heading, degrees |
| | `--speed` | `0.0` | Object speed, m/s |
| | `--affected-vehicle-types` | `usv` | One or more of `unknown usv uuv uav` |
| `readiness-confirm` | `--report-seq` | `1` | `seq` of the vehicle's ReadinessReport being confirmed |
| | `--vehicle-id` | `USV1` | Vehicle whose ReadinessReport is confirmed |

Step-by-step order for each tier: see **section 4**.

### 3.6 Faking the GCS side (testing the monitor without a GCS)

Normally the GCS sends these. Use them to check the monitor alone. Every one takes `--team`
(default `RNRX`) and, where listed, `--vehicle` (vehicle ID in the topic and message).

| Subcommand | Option | Default | Meaning |
|---|---|---|---|
| `run-declaration` | `--vehicles ID …` | `USV1 UUV1 UAV1` | Vehicles in the run |
| | `--task1` … `--task4` | `unknown` | Tier per task: `none core advanced disruptive` (don't send `unknown`) |
| | `--geofence-lats` / `--geofence-lngs` | a closed 5-point ring near Singapore | UAV geofence, closed ring |
| `heartbeat` | `--vehicle` | `USV1` | Vehicle ID |
| | `--state` | `auto` | `unknown killed manual auto` |
| | `--vehicle-type` | `usv` | `unknown usv uuv uav` |
| | `--lat` / `--lng` | `1.2806142` / `103.8557120` | Position |
| | `--speed` / `--heading` | `0.0` / `0.0` | m/s, degrees |
| `pipeline-survey` | `--vehicle` | `UUV1` | |
| | `--lat` / `--lng` | `1.2806142` / `103.8557120` | Active buoy position |
| | `--segments` | `intact damaged intact` | Ordered list of `unknown intact damaged` |
| `resource-delivery` | `--vehicle` | `UAV1` | |
| | `--task` | `infra-survey-repair` | `unknown none safe-passage infra-survey-repair coordinated-logistics dynamic-incident` |
| | `--resource-color` | `any` | `unknown red green blue any` |
| | `--delivery-circle-color` | `red` | same colours |
| `docking` | `--vehicle` / `--bay-id` | `USV1` / `1` | Bay docked in |
| `firefighting` | `--vehicle` / `--window-id` | `USV1` / `1` | Window sprayed |
| `incident-ack` | `--vehicle` / `--command-seq` | `USV1` / `1` | `seq` of the RxCommand acknowledged |
| `readiness-report` | `--vehicle` / `--command-seq` | `USV1` / `1` | `seq` of the AssistanceRequest it is ready for |

One `heartbeat` call sends **one** message; the monitor marks the vehicle STALE after 2.5 s.
For continuous movement use the fake GCS instead:

```bash
python3.10 report.py --course local --team ITSN --vehicle USV1 --vehicle UUV1 --simulate
```

| Option | Default | Meaning |
|---|---|---|
| `--course` | `auto` | `auto` (detect from DHCP), `alpha bravo charlie delta demo local` |
| `--host` / `--port` | — / `1883` | Broker override (wins over `--course`) |
| `--team` | required | Team ID |
| `--vehicle` | required, repeatable | `USV1` or `ID:TYPE` (`boat1:USV`) |
| `--tiers` | `NONE,NONE,NONE,NONE` | Task 1–4 tiers |
| `--geofence` | — | `"lat,lng;lat,lng;…"`, required when a UAV is declared |
| `--simulate` | off | Orbit the course centre; otherwise read JSON telemetry lines on stdin |

---

## 4. Giving Task 4 as host (Dynamic Incident Response)

Task 4 is the only task where **you** start the action: you send an incident command, the team's
GCS answers with reports. Section 3.5 lists the options; this section is the order to send them in.

### 4.1 Before you give anything

| Check | Where |
|---|---|
| Team is `ACTIVE · RUN n` | Header chip / teams panel. Don't send Task 4 to a team that is only DECLARED |
| Declared Task 4 tier | Tier column in the teams panel. Each tier has its **own** chain — Core: assistance request + readiness confirm; Advanced: keep-out zone + all clear; Disruptive: moving object alert. The Task 4 tab enables only the declared tier's panel |
| Vehicle of the targeted type is LIVE | Vehicle cards. Commands are addressed by **vehicle type**, not ID |
| Positions are inside the course | Pick `--lat/--lng` inside the course boundary on the map (the 3.5 defaults are in Singapore) |

### 4.2 Use one interactive session for the whole run

`RxCommand.seq` comes from a counter inside `test_client.py` that starts at 1 **every time the
script starts**. One-shot calls (`rc run-start …`, then `rc assistance-request …`) therefore all
go out as `seq=1`, and a GCS that checks for increasing seq can drop them. Open one session and
send RunStart and every Task 4 command from it:

```bash
rc                       # opens the robotx> prompt on one connection
robotx> run-start --team ITSN --declaration-seq 1 --run-id 1          # seq=1
robotx> assistance-request --team ITSN ...                             # seq=2, 3, ...
```

The monitor log prints each command as `[RxCommand] ITSN seq=<n> <body>`. Note the seq: the
team's IncidentAck must quote it.

### 4.3 Core — assistance request

Two commands in (request, confirm), two reports out (ack, readiness). Host = this laptop;
GCS = `nala2_report` on the team side.

**Before the run**

| # | Who | Action |
|---|---|---|
| 1 | GCS | Declare Task 4 Core: `ros2 run nala2_report report --ros-args -p team_id:=ITSN -p task4_tier:=core …` (declares only `vehicle_ids`, default `['USV1']`) |
| 2 | Host | Teams panel shows Task 4 tier **CORE**. Open one session: `rc` → `robotx>` |
| 3 | Both | Sync clocks (NTP / `date`). The GCS warns on any command whose `sent_at` is > 5 s old |
| 4 | Host | `robotx> run-start --team ITSN --declaration-seq <decl seq> --run-id 1` → team `ACTIVE` |

**Assistance request**

| # | Who | Action | Seen at |
|---|---|---|---|
| 5 | Host | `robotx> assistance-request --team ITSN --vehicle-type usv --lat -7.263 --lng 112.793` — note **seq N** | Monitor log `[RxCommand] ITSN seq=N assistance_request` |
| 6 | GCS (auto) | `report` republishes it on ROS `/system/mission/command`: `command_type=CMD_TASK4_ASSISTANCE`, `command_seq=N`, `target_vehicle`, `position` | GCS dashboard command feed |
| 7 | GCS (vehicle stack) | Publishes `/system/vehicle/usv/task4/incident_ack` with `command_seq: N` straight away | — |
| 8 | Host | Wait for the ack | `[RxReport] ITSN/USV1 seq=<a> incident_ack` |
| 9 | GCS (vehicle) | Break off the current task, transit to the point, loiter | Map: USV1 moves to the point and circles |
| 10 | GCS (vehicle stack) | Once on station, publishes `/system/vehicle/usv/task4/readiness` with `command_seq: N` (once per incident) | — |
| 11 | Host | Wait for readiness — note its **report seq R** (not N) | `[RxReport] ITSN/USV1 seq=R readiness` |

**Readiness confirm**

| # | Who | Action | Seen at |
|---|---|---|---|
| 12 | Host | `robotx> readiness-confirm --team ITSN --report-seq R --vehicle-id USV1` | `[RxCommand] ITSN seq=N+1 readiness_confirm` |
| 13 | GCS (auto) | Forwarded as `CMD_TASK4_READINESS_CONFIRM` with `report_seq=N` (the relay translates R back to the assistance seq the boat knows; `detail` keeps `rc_report_seq=R`), `target_vehicle` from `USV1` | GCS log `ReadinessConfirm report seq=R -> assistance command seq=N` |
| 14 | GCS (vehicle) | Resume the task it was doing before the request. No ack for the confirm | Map: USV1 leaves the point |

Repeat with `--vehicle-type uuv` / `uav` (and `--vehicle-id UUV1` / `UAV1`) if the judges want
each type tested.

**Bench without an autonomy stack:** nothing publishes the ack or the readiness
(`report_inject` always uses `command_seq=1`). The GCS can send them by hand:

```bash
ros2 topic pub --once /system/vehicle/usv/task4/incident_ack rx_msgs/msg/IncidentAck "{command_seq: N}"
ros2 topic pub --once /system/vehicle/usv/task4/readiness rx_msgs/msg/ReadinessReport "{command_seq: N}"
```

### 4.4 Advanced — keep-out zone, then all clear

Two commands in, two acks out. No ReadinessReport / ReadinessConfirm here — those belong to
the Core assistance request (4.3). Host = this laptop; GCS = `nala2_report` on the team side.

**Before the run**

| # | Who | Action |
|---|---|---|
| 1 | GCS | Declare Task 4 Advanced: `ros2 run nala2_report report --ros-args -p team_id:=ITSN -p task4_tier:=advanced …` |
| 2 | Host | Teams panel shows Task 4 tier **ADV**. Open one session: `rc` → `robotx>` |
| 3 | Both | Sync clocks (NTP / `date`). The GCS warns on any command whose `sent_at` is > 5 s old (`possible stale/replayed message or clock skew`) |
| 4 | Host | `robotx> run-start --team ITSN --declaration-seq <decl seq> --run-id 1` → team `ACTIVE` |

**Keep-out zone**

| # | Who | Action | Seen at |
|---|---|---|---|
| 5 | Host | `robotx> keep-out-zone --team ITSN --vehicle-type usv --lat -7.263 --lng 112.793 --radius-m 20` — note **seq N** | Monitor log `[RxCommand] ITSN seq=N keep_out_zone` |
| 6 | GCS (auto) | `report` republishes it on ROS `/system/mission/command`: `command_type=CMD_TASK4_KEEP_OUT_ZONE`, `command_seq=N`, centre, `radius_m` | GCS dashboard command feed |
| 7 | GCS (vehicle stack) | Publishes `/system/vehicle/usv/task4/incident_ack` with `command_seq: N`. `report` does **not** ack by itself — it only forwards this topic | — |
| 8 | Host | Wait for the ack | `[RxReport] ITSN/USV1 seq=<r> incident_ack` |
| 9 | GCS (vehicle) | Avoid the circle, keep doing its current task | Map: trail stays outside the radius |

**All clear**

| # | Who | Action | Seen at |
|---|---|---|---|
| 10 | Host | `robotx> all-clear --team ITSN --vehicle-type usv` — note **seq M** | `[RxCommand] ITSN seq=M all_clear` |
| 11 | GCS (auto) | Forwarded as `CMD_TASK4_ALL_CLEAR`, `command_seq=M` | GCS dashboard |
| 12 | GCS (vehicle stack) | Publishes `incident_ack` with `command_seq: M`, drops the no-go constraint | — |
| 13 | Host | Wait for the second ack | `[RxReport] ITSN/USV1 seq=<r+1> incident_ack` |

`all-clear` has no position — it lifts the keep-out zone for that vehicle type.

**Bench without an autonomy stack:** nothing publishes the ack (`report_inject` always acks
`command_seq=1`, which won't match). The GCS can ack by hand after each command:

```bash
ros2 topic pub --once /system/vehicle/usv/task4/incident_ack rx_msgs/msg/IncidentAck "{command_seq: N}"
```

Only target vehicle types the team declared and that show LIVE (for ITSN: `usv`).

### 4.5 Disruptive — moving object alert

Commands in, **no reports out** — there is no ack for a moving object alert. You judge it on the
map. Host = this laptop; GCS = `nala2_report` on the team side.

**Before the run**

| # | Who | Action |
|---|---|---|
| 1 | GCS | Declare Task 4 Disruptive: `ros2 run nala2_report report --ros-args -p team_id:=ITSN -p task4_tier:=disruptive …` |
| 2 | Host | Teams panel shows Task 4 tier **DIS**. Open one session: `rc` → `robotx>` |
| 3 | Both | Sync clocks (NTP / `date`). The GCS warns on any command whose `sent_at` is > 5 s old |
| 4 | Host | `robotx> run-start --team ITSN --declaration-seq <decl seq> --run-id 1` → team `ACTIVE` |

**Moving object alert**

| # | Who | Action | Seen at |
|---|---|---|---|
| 5 | Host | `robotx> moving-object-alert --team ITSN --lat -7.262 --lng 112.792 --heading 90 --speed 1.5 --affected-vehicle-types usv uuv` — note **seq N** | Monitor log `[RxCommand] ITSN seq=N moving_object_alert` |
| 6 | GCS (auto) | `report` republishes it on ROS `/system/mission/command`: `command_type=CMD_TASK4_MOVING_OBJECT`, `command_seq=N`, `position`, `heading_deg`, `speed_mps` | GCS dashboard command feed |
| 7 | GCS (vehicle) | Every affected vehicle keeps more than **10 m** from the object (predict its track from heading and speed) | Map: trails stay clear of the object position |
| 8 | Host | To move the object, send the alert again with the new position — each send gets a new seq (N+1, N+2, …) | One `[RxCommand]` line per update |

How the GCS passes it on: with **one** affected type, `report` sets the ROS `Command.target_vehicle`
to that type, so only that vehicle reacts; with several, `target_vehicle` is `TYPE_UNKNOWN` (every
vehicle reacts). `Command.detail` always lists them, e.g. `affected=USV,UUV`.

### 4.6 If the team does not answer

| Symptom | Check |
|---|---|
| No `incident_ack` | Team still ACTIVE? Vehicle of that type LIVE? `--team` exactly `ITSN`? |
| `incident_ack` but no `readiness` | Vehicle still transiting, or the point is unreachable — check the map |
| Command ignored after a restart of `rc` | seq restarted at 1 — keep the same `robotx>` session for the whole run |
| `[WARN] … seq` notices on reports | GCS repeated a report; ask the team before re-sending. A single `missed ~100 report(s)` right after the GCS relay restarted is expected — it resumes 100 past its saved counter so no seq is ever reused |
| Command sent twice by mistake | The GCS drops a repeated `seq`; send a **new** command instead (the console always uses a new seq) |

---

## 5. Typical bench run

```bash
# this laptop — one terminal, one app
python3.10 run_ui.py          # Connect (This host)
#   Course tab:    preset "Danau 8" (or pin your own on the map) → Publish course (retained)

# GCS — on the GCS machine (192.168.65.x)
ros2 run nala2_report report           # declares once the course arrives (vehicle_ids default USV1)
ros2 run nala2_report report_inject    # synthetic vehicle heartbeats if no boats

#   Run start tab: ITSN shows DECLARED → Allow start
#   Task 4 tab:    send the tier's commands, watch "Sent commands" for the answers

#   Run over:      Run start tab → End run (saves the run log; team shows ENDED)

# next run on the SAME course: the GCS keeps its declaration across reconnects and
# restarts, so ask it for a fresh one (a different course re-declares by itself)
ros2 service call /nala2_report/new_run std_srvs/srv/Trigger
#   Run start tab: the team is DECLARED again → Allow start (Run ID suggested +1)
```

## 6. Troubleshooting

| You see | Cause / fix |
|---|---|
| `VersionError … Runtime version cannot be older` | Use `python3.10`, not `python3` |
| `ModuleNotFoundError: common_pb2` | `PYTHONPATH` missing or not run from the repo root |
| `error: unrecognized arguments: --broker` | Put `--broker` before the subcommand |
| Map says *Waiting for RxCourse* | No retained course: Course tab → **Publish course** |
| Course chip red `INVALID` | First and last corner differ, a corner out of range, or pinger 0 |
| Team stuck `DECLARED` | Run start tab → select the team → **Allow start** |
| `NO HEARTBEAT` | GCS declared but vehicles aren't publishing `/system/vehicle/*/heartbeat` — start them or `report_inject` |
| `LINK LOST` | GCS stopped or the cable/Wi-Fi dropped |
| `DECL MISMATCH` | RunStart declaration seq ≠ the team's declaration seq. The GCS does **not** pass this RunStart to the boat; use **Allow start** (it takes the seq from the declaration) |
| Team never `DECLARED` | GCS log `RunDeclaration NOT sent: …` — a UAV declared without a geofence, a geofence point outside the course, or a bad `vehicle_ids`. Fix the GCS parameter |
| `ACTIVE` but the boat does not move | Check the GCS log for `RunStart verified` — or `NOT forwarded` (declaration mismatch) |
| Vehicle shown that the OCS no longer declares | A new RunDeclaration replaces the team's vehicle list: vehicles left out are removed from the map and cards (`ITSN/UAV1 removed: not in the new declaration`). A vehicle that reports without being declared is still drawn, with `[WARN] ITSN/UAV1 reports but is not declared` in the log |
| Same team re-declares between runs | Expected after `new_run` or a different course; Run start lists the new declaration seq |
| Team stuck `ENDED` | You ended the run; the GCS has not declared again. GCS: `ros2 service call /nala2_report/new_run std_srvs/srv/Trigger` |
| Where is the run log? | `~/.local/share/robocommand_ui/runs/` — one `.log` + `.json` replay per run (replay it from Run start → Finished runs) (also written when a team re-declares mid-run or the console closes during a run) |
| GCS can't reach the host | `systemctl is-active mosquitto`; the GCS needs an address on the course network: `systemctl status isc-dhcp-server` (installed by `scripts/dhcp/install_dhcp.sh`, see §1) |
| Map kept old trails after a run start | Fixed: the console clears the map as soon as its RunStart is sent, and subscribes at QoS 1. **Clear** on the Map tab does it by hand |
