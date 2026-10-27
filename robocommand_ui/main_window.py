"""Main window of the RoboCommand host console.

Runs on the course RoboCommand host (e.g. 192.168.65.2 for Course Alpha). It
shows what every team's GCS/OCS reports to it, and sends what RoboCommand
sends, so no ``test_client.py`` terminal is needed:

- **Map**: boat movement on the course map, telemetry, teams, message log
- **Course**: edit and publish the retained RxCourse, with saved presets
- **Run start**: teams that declared a run; pick one and allow the start
- **Task 1**: the light beacons (HTTP over the devices' WiFi)
- **Task 3**: the docking bays: water collected, start / stop per tier
- **Task 4**: Core / Advanced / Disruptive incident commands and their acks

Nothing is published unless the operator presses a send button.
"""

import time

from PyQt5.QtCore import QSettings, Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from robocommand_ui import commands, theme
from robocommand_ui.course_validation import validate_course
from robocommand_ui.courses import host_course
from robocommand_ui.fleet_state import STALE_SECONDS, FleetState
from robocommand_ui.proto_helper import task_tier_name
from robocommand_ui.incident_log import IncidentLog
from robocommand_ui.run_log import RunRecorder, format_duration
from robocommand_ui.mqtt_worker import MqttWorker
from robocommand_ui.widgets.connection_bar import ConnectionBar
from robocommand_ui.widgets.course_map import CourseMapWidget
from robocommand_ui.widgets.course_panel import CoursePanel
from robocommand_ui.widgets.course_tab import CourseTab
from robocommand_ui.widgets.log_panel import LogPanel
from robocommand_ui.widgets.panel import make_chip, set_chip
from robocommand_ui.widgets.run_start_tab import RunStartTab
from robocommand_ui.widgets.task1_tab import Task1Tab
from robocommand_ui.widgets.task3_tab import Task3Tab
from robocommand_ui.widgets.task4_tab import Task4Tab
from robocommand_ui.widgets.teams_panel import RUN_COLORS, TeamsPanel, format_age
from robocommand_ui.widgets.vehicle_monitor import VehicleMonitorPanel

ALL_TEAMS = "All teams"
REFRESH_MS = 500            # matches the 2 Hz heartbeat rate
RAIL_WIDTH = 440
THEME_KEY = "theme"


def course_center(ring):
    """Mean of the distinct corners, or None without a course."""
    points = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    if not points:
        return None
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


class MainWindow(QMainWindow):
    def __init__(self, presets_path=None, run_log_dir=None, settings=None):
        super().__init__()
        self.setWindowTitle("RoboCommand")
        self.setMinimumSize(1280, 780)
        self.resize(1560, 960)
        self._settings = settings if settings is not None else QSettings("RoboCommand", "HostConsole")
        saved = str(self._settings.value(THEME_KEY, theme.DEFAULT_MODE))
        theme.set_mode(saved if saved in theme.PALETTES else theme.DEFAULT_MODE)
        app = QApplication.instance()
        if app is not None:
            theme.apply(app)

        self.fleet = FleetState()
        self._team_links = {}       # team_id -> last logged link state
        self.mqtt = MqttWorker(self)
        self.incidents = IncidentLog()
        self.sender = commands.CommandSender(self._publish, self._seen_command_seq)
        self._presets_path = presets_path
        self.recorder = RunRecorder(run_log_dir)
        self._course = None             # (ring, course_id) of the retained RxCourse

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_header())
        layout.addWidget(self._build_tabs(), 1)

        self.statusBar().showMessage("Ready")
        self._connect_signals()
        self.course_tab.set_rc_course(host_course())

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh_views)
        self._refresh_timer.start(REFRESH_MS)

    # ---------- builders ----------
    def _build_header(self):
        header = QFrame()
        header.setObjectName("Header")
        row = QHBoxLayout(header)
        row.setContentsMargins(20, 12, 20, 12)
        row.setSpacing(10)

        brand = QVBoxLayout()
        brand.setSpacing(2)
        title = QLabel("RoboCommand")
        title.setObjectName("Brand")
        brand.addWidget(title)
        row.addLayout(brand)
        row.addSpacing(14)

        self.course_id_label = make_chip("COURSE —", theme.IDLE)
        self.course_id_label.setToolTip("Retained RxCourse and its validity")
        row.addWidget(self.course_id_label)
        self.run_chip = make_chip("NO TEAMS", theme.IDLE)
        self.run_chip.setToolTip("Run state of the team on this course")
        row.addWidget(self.run_chip)
        self.live_chip = make_chip("0 LIVE", theme.IDLE)
        self.live_chip.setToolTip("Vehicles with a heartbeat in the last 2.5 s")
        row.addWidget(self.live_chip)
        row.addStretch()

        self.team_filter = QComboBox()
        self.team_filter.addItem(ALL_TEAMS)
        self.team_filter.setMinimumWidth(120)
        self.team_filter.setCursor(Qt.PointingHandCursor)
        self.team_filter.setToolTip("Show one team on the map and in the vehicle list")
        self.team_filter.currentIndexChanged.connect(self.refresh_views)
        row.addWidget(self.team_filter)

        divider = QFrame()
        divider.setFixedSize(1, 24)
        divider.setObjectName("Divider")
        row.addWidget(divider)

        self.connection_bar = ConnectionBar()
        row.addWidget(self.connection_bar)

        clock = QVBoxLayout()
        clock.setSpacing(0)
        self.clock_label = QLabel("")
        self.clock_label.setObjectName("Clock")
        self.clock_label.setAlignment(Qt.AlignRight)
        self.clock_date = QLabel("")
        self.clock_date.setObjectName("ClockDate")
        self.clock_date.setAlignment(Qt.AlignRight)
        clock.addWidget(self.clock_label)
        clock.addWidget(self.clock_date)
        row.addSpacing(8)
        row.addLayout(clock)
        self._tick_clock()
        return header

    def _label_theme_btn(self):
        dark = theme.mode() == theme.DARK
        self.theme_btn.setText("Light mode" if dark else "Dark mode")

    def _toggle_theme(self):
        theme.set_mode(theme.LIGHT if theme.mode() == theme.DARK else theme.DARK)
        self._settings.setValue(THEME_KEY, theme.mode())
        app = QApplication.instance()
        if app is not None:
            theme.apply(app)
        self._label_theme_btn()
        self.refresh_views()

    def _tick_clock(self):
        now = time.localtime()
        self.clock_label.setText(time.strftime("%H:%M:%S", now))
        self.clock_date.setText(time.strftime("%a %d %b %Y", now))

    def _build_body(self):
        body = QSplitter(Qt.Horizontal)
        body.setHandleWidth(16)

        left = QSplitter(Qt.Vertical)
        left.setHandleWidth(16)
        self.course_map = CourseMapWidget()
        left.addWidget(self.course_map)
        self.log_panel = LogPanel()
        self.log_panel.setMinimumHeight(110)
        left.addWidget(self.log_panel)
        left.setStretchFactor(0, 4)
        left.setStretchFactor(1, 1)
        left.setSizes([700, 180])
        body.addWidget(left)

        rail = QWidget()
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(0, 0, 4, 0)
        rail_layout.setSpacing(10)
        self.teams_panel = TeamsPanel()
        rail_layout.addWidget(self.teams_panel)
        self.vehicle_monitor = VehicleMonitorPanel()
        rail_layout.addWidget(self.vehicle_monitor)
        self.course_panel = CoursePanel()
        rail_layout.addWidget(self.course_panel)
        rail_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(rail)
        scroll.setMinimumWidth(380)
        body.addWidget(scroll)
        body.setStretchFactor(0, 1)
        body.setStretchFactor(1, 0)
        body.setSizes([1560 - RAIL_WIDTH, RAIL_WIDTH])

        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(20, 16, 20, 16)
        wl.addWidget(body)
        return wrap

    def _build_tabs(self):
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._build_body(), "MAP")
        self.course_tab = CourseTab(self._presets_path)
        self.tabs.addTab(self.course_tab, "COURSE")
        self.run_start_tab = RunStartTab(self.recorder.directory)
        self.tabs.addTab(self.run_start_tab, "RUN START")
        self.task1_tab = Task1Tab(self._settings)
        self.tabs.addTab(self.task1_tab, "TASK 1")
        self.task3_tab = Task3Tab(self._settings)
        self.tabs.addTab(self.task3_tab, "TASK 3")
        self.task4_tab = Task4Tab()
        self.tabs.addTab(self.task4_tab, "TASK 4")

        corner = QWidget()
        corner.setObjectName("TabCorner")       # same surface as the tab bar
        corner_row = QHBoxLayout(corner)
        corner_row.setContentsMargins(0, 4, 20, 4)
        self.theme_btn = QPushButton()
        self.theme_btn.setObjectName("Ghost")
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.setToolTip("Switch between light and dark mode (remembered)")
        self.theme_btn.clicked.connect(self._toggle_theme)
        self._label_theme_btn()
        corner_row.addWidget(self.theme_btn)
        self.tabs.setCornerWidget(corner, Qt.TopRightCorner)
        return self.tabs

    # ---------- signal wiring ----------
    def _connect_signals(self):
        self.connection_bar.connect_requested.connect(self._on_connect)
        self.connection_bar.disconnect_requested.connect(self._on_disconnect)

        self.mqtt.connected.connect(self._on_mqtt_connected)
        self.mqtt.disconnected.connect(self._on_mqtt_disconnected)
        self.mqtt.connection_error.connect(self._on_mqtt_error)
        self.mqtt.log_message.connect(self._log)
        self.mqtt.course_received.connect(self._on_course_received)
        self.mqtt.course_cleared.connect(self._on_course_cleared)
        self.mqtt.report_received.connect(self._on_report)
        self.mqtt.request_received.connect(self._on_request)
        self.mqtt.command_received.connect(self._on_command)

        self.course_map.clear_requested.connect(self._clear_map)
        self.course_tab.publish_requested.connect(self._publish_course)
        self.course_tab.clear_requested.connect(self._clear_course)
        self.course_tab.log.connect(self._log)
        self.run_start_tab.start_requested.connect(self._start_run)
        self.run_start_tab.end_requested.connect(self._end_run)
        self.run_start_tab.reset_requested.connect(self._reset_counters)
        self.task4_tab.command_requested.connect(self._send_task4)
        self.task1_tab.log.connect(self._log)
        self.task3_tab.log.connect(self._log)

    # ---------- connection ----------
    def _on_connect(self, host: str, port: int):
        self.course_tab.set_rc_course(host_course(host if host not in ("localhost", "127.0.0.1") else ""))
        self.fleet.clear()
        self._team_links = {}
        self.course_map.clear()
        self._sync_team_filter()
        self.refresh_views()
        self.mqtt.start_monitoring(host, port)

    def _on_disconnect(self):
        self.mqtt.stop()

    def _on_mqtt_connected(self):
        self.connection_bar.set_connected(True)
        self._set_tabs_connected(True)
        self.statusBar().showMessage(f"Connected to {self.mqtt.broker}")

    def _on_mqtt_disconnected(self):
        self.connection_bar.set_connected(False)
        self._set_tabs_connected(False)
        self.statusBar().showMessage("Disconnected.")

    def _on_mqtt_error(self, err: str):
        self.connection_bar.set_error(err)
        self._set_tabs_connected(False)
        self.statusBar().showMessage(f"Connection error: {err}")

    def _set_tabs_connected(self, connected: bool):
        self.run_start_tab.set_connected(connected)
        self.task4_tab.set_connected(connected)

    # ---------- sending (as RoboCommand) ----------
    def _publish(self, topic: str, payload: bytes, retain: bool):
        return self.mqtt.publish(topic, payload, retain)

    def _seen_command_seq(self, team_id: str) -> int:
        team = self.fleet.teams.get(team_id)
        return team.last_command_seq if team else 0

    def _report_send(self, what: str, result) -> bool:
        if result.ok:
            self.statusBar().showMessage(f"Sent {what}")
            return True
        msg = f"Could not send {what}: {result.error}"
        self._log(f"[ERROR] {msg}")
        self.statusBar().showMessage(msg)
        QMessageBox.warning(self, "Not sent", msg)
        return False

    def _confirm(self, title: str, text: str) -> bool:
        return QMessageBox.question(self, title, text) == QMessageBox.Yes

    def _publish_course(self, course):
        active = [t.team_id for t in self.fleet.teams.values() if t.run_state == "ACTIVE"]
        if active and not self._confirm(
                "Replace the course?",
                f"{', '.join(active)} is running. Publishing a new course changes the boundary "
                f"its GCS uses mid-run. Publish anyway?"):
            return
        if self._report_send(f"course {course.course_id}", self.sender.send_course(course)):
            self.course_tab.mark_published(course)
            self._log(f"[SENT] RxCourse {course.course_id} "
                                      f"({len(course.corners)} corners, retained)")

    def _clear_course(self):
        if self._report_send("course clear", self.sender.clear_course()):
            self._log("[SENT] cleared retained RxCourse")

    def _start_run(self, team_id: str, declaration_seq: int, run_id: int):
        team = self.fleet.teams.get(team_id)
        blockers = self.fleet.start_blockers(team_id)
        if blockers:
            msg = f"{team_id} not ready to start: {'; '.join(blockers)}"
            self.statusBar().showMessage(msg)
            QMessageBox.warning(self, "Not ready", msg + "\n\nEvery declared vehicle must be "
                                "LIVE and in AUTO.")
            return
        if team is not None and team.run_state == "ACTIVE" and not self._confirm(
                "Restart run?", f"{team_id} is already ACTIVE (run {team.run_id}). "
                                f"Send RunStart again with run {run_id}?"):
            return
        self._send_command(team_id, commands.run_start(declaration_seq, run_id),
                           f"decl seq={declaration_seq} run_id={run_id}")

    def _send_task4(self, team_id: str, body, summary: str):
        team = self.fleet.teams.get(team_id)
        state = team.run_state if team else "unknown"
        if state != "ACTIVE" and not self._confirm(
                "Team not active", f"{team_id} is {state}, not ACTIVE. Send {body[0]} anyway?"):
            return
        self._send_command(team_id, body, summary)

    def _send_command(self, team_id: str, body, summary: str):
        name, msg = body
        result = self.sender.send_command(team_id, body)
        if not self._report_send(f"{name} to {team_id}", result):
            return
        self._log(f"[SENT] {team_id} seq={result.seq} {name}: {summary}")
        if name == "run_start":
            # Clear the map now; don't depend on the broker echoing our RunStart back
            self._log_notices(self.fleet.apply_run_start(team_id, result.seq, msg))
            self._on_run_started(team_id)
        else:
            self.incidents.record(team_id, result.seq, name, summary)
        if name == "readiness_confirm":
            self.incidents.mark_confirmed(team_id, msg.vehicle_id, msg.report_seq)
        self.refresh_views()

    # ---------- received ----------
    def _on_course_received(self, course):
        issues = validate_course(course)
        self.course_panel.update_course(course)
        self.course_map.set_course(course)
        self.course_tab.show_broker_course(course)
        ring = [(c.latitude, c.longitude) for c in course.corners]
        self.task4_tab.set_course(ring, course_center(ring))
        self._course = (ring, course.course_id)
        self.recorder.set_course(ring, course.course_id)
        name = course.course_id or "<no id>"
        if issues:
            set_chip(self.course_id_label, f"COURSE {name} · INVALID", theme.FAULT)
            self.course_id_label.setToolTip("; ".join(issues))
            msg = f"Course {name} INVALID: {issues[0]}"
            self.statusBar().showMessage(msg)
            self._log(f"[ERROR] {msg}")
        else:
            set_chip(self.course_id_label, f"COURSE {name}", theme.TEXT_MUTED)
            self.course_id_label.setToolTip(f"{course.pinger_freq_hz} Hz pinger, "
                                            f"{len(course.corners)} corners")
            self._log(f"[RxCourse] {name} valid")

    def _on_course_cleared(self):
        self.course_tab.show_broker_course(None)
        set_chip(self.course_id_label, "COURSE —", theme.IDLE)
        self._log("[RxCourse] retained course cleared")

    def _on_report(self, team_id: str, vehicle_id: str, report):
        is_new = (team_id, vehicle_id) not in self.fleet.vehicles
        track = self.fleet.vehicles.get((team_id, vehicle_id))
        hb_before = track.last_hb_time if track else None
        self._log_notices(self.fleet.ingest_report(team_id, vehicle_id, report))
        self._record_report(team_id, vehicle_id, report, hb_before)
        body = report.WhichOneof("body")
        if body and body != "heartbeat":
            self._log(f"[RxReport] {team_id}/{vehicle_id} seq={report.seq} {body}")
            matched = self.incidents.on_report(team_id, vehicle_id, report)
            if matched:
                self._log(matched)
        if is_new and (team_id, vehicle_id) in self.fleet.vehicles:
            self._log(f"New vehicle reporting: {team_id}/{vehicle_id}")
            self._sync_team_filter()

    def _record_report(self, team_id: str, vehicle_id: str, report, hb_before):
        """Feed the run replay with what the map just drew (accepted reports only)."""
        if not self.recorder.is_active(team_id):
            return
        track = self.fleet.vehicles.get((team_id, vehicle_id))
        body = report.WhichOneof("body")
        team = self.fleet.teams.get(team_id)
        if body == "heartbeat" and track is not None and track.last_hb_time != hb_before:
            self.recorder.track(team_id, vehicle_id, track.last_hb)
        elif body == "safe_passage" and team is not None:
            self.recorder.task(team_id, "safe_passage", team.safe_passage)
        elif body == "pipeline_survey" and team is not None:
            self.recorder.task(team_id, "pipeline", team.pipeline)

    def _on_request(self, team_id: str, request):
        if request.WhichOneof("body") == "run_declaration" and self.recorder.is_active(team_id):
            self._close_run_log(team_id, "team declared a new run")     # new run request
        self._log(
            f"[RxRequest] {team_id} seq={request.seq} {request.WhichOneof('body')}")
        self._log_notices(self.fleet.ingest_request(team_id, request))
        self._sync_team_filter()

    def _on_command(self, team_id: str, command):
        echo = self.fleet.is_applied_run_start(team_id, command)
        notices = self.fleet.ingest_command(team_id, command)
        self._log(
            f"[RxCommand] {team_id} seq={command.seq} {command.WhichOneof('body')}")
        if command.WhichOneof("body") == "run_start" and not echo:
            self._on_run_started(team_id)       # RunStart from another tool
        self._log_notices(notices)
        self._sync_team_filter()

    def _on_run_started(self, team_id: str):
        """FleetState has applied a RunStart: start the run log, show the clean map."""
        team = self.fleet.teams.get(team_id)
        if team is None:
            return
        if self.recorder.is_active(team_id):
            self._close_run_log(team_id, f"superseded by RunStart run_id={team.run_id}")
        self.recorder.begin(team_id, team.run_id, team.declaration_seq,
                            course=self._course, geofence=team.geofence)
        self._log(f"[RUN START] {team_id} run {team.run_id}: map trails and task "
                  f"overlays cleared")
        self.refresh_views()

    def _clear_map(self):
        """Map tab Clear: drop trails and task overlays of the team shown (or all)."""
        team = self.selected_team()
        self.fleet.clear_drawings(team)
        self._log(f"[MAP] trails and task overlays cleared ({team or 'all teams'})")
        self.refresh_views()

    # ---------- run end (host only: the protocol has no run-end message) ----------
    def _end_run(self, team_id: str):
        team = self.fleet.teams.get(team_id)
        if team is None or team.run_id is None:
            return
        if not self._confirm(
                "End run?", f"End {team_id} run {team.run_id}?\n\nThe run log is saved and "
                            f"the team waits for its next RunDeclaration. Nothing is sent to "
                            f"the team (the protocol has no run-end message)."):
            return
        path = self._close_run_log(team_id, "ended by host")
        run_id = self.fleet.end_run(team_id)
        self.incidents.clear_team(team_id)
        where = f"log saved to {path}" if path else "no log (run started before this console connected)"
        self._log(f"[RUN END] {team_id} run {run_id} ended by host; {where}")
        self.statusBar().showMessage(f"{team_id} run {run_id} ended — {where}")
        self.refresh_views()

    def _reset_counters(self, team_id: str):
        team = self.fleet.teams.get(team_id)
        if team is None or team.run_id is not None:
            return
        if not self._confirm(
                "Reset run ID & seq?",
                f"Restart {team_id} at Run ID 1 and command seq 1?\n\nOnly do this between runs: "
                f"until {team_id} declares a new run, its GCS drops a repeated seq as a duplicate."):
            return
        self.sender.reset(team_id)
        self.fleet.reset_counters(team_id)
        self._log(f"[RESET] {team_id} run ID -> 1, command seq -> 1")
        self.statusBar().showMessage(f"{team_id}: next Run ID 1, next command seq 1")
        self.refresh_views()

    def _close_run_log(self, team_id: str, reason: str):
        path = self.recorder.finish(team_id, reason, self._run_summary(team_id))
        if path is not None:
            self.run_start_tab.reload_runs()
        if path is not None and reason != "ended by host":
            self._log(f"[RUN LOG] {team_id} previous run closed ({reason}); saved to {path}")
        return path

    def _run_summary(self, team_id: str):
        now = time.time()
        team = self.fleet.teams.get(team_id)
        lines = []
        if team is not None:
            tiers = " ".join(task_tier_name(t) for t in team.tiers)
            lines.append(f"declared vehicles {', '.join(team.declared_vehicles) or '—'}  ·  "
                         f"tiers T1–T4 {tiers}")
        for v in self.fleet.vehicles_of(team_id):
            age = v.age(now)
            seen = "never" if age is None else f"{format_duration(age)} ago"
            reports = ", ".join(f"{k}×{n}" for k, n in sorted(v.reports.items())) or "none"
            lines.append(f"{v.vehicle_id}: last heartbeat {seen}, report seq {v.last_seq}, "
                         f"missed {v.seq_missed}, out of order {v.seq_out_of_order}, "
                         f"restarts {v.seq_restarts}; task reports: {reports}")
        for e in reversed(self.incidents.entries(team_id)):
            lines.append(f"Task 4 seq={e.seq} {e.kind} ({e.summary}) -> {e.status}")
        return lines

    # ---------- views ----------
    def selected_team(self):
        text = self.team_filter.currentText()
        return None if text in ("", ALL_TEAMS) else text

    def refresh_views(self):
        now = time.time()
        team = self.selected_team()
        self._tick_clock()
        self.course_map.show_fleet(self.fleet, team, now)
        self.vehicle_monitor.refresh(self.fleet, team, now)
        self.teams_panel.refresh(self.fleet, now)
        self.run_start_tab.refresh(self.fleet, now)
        self.task4_tab.refresh(self.fleet, self.incidents, self.sender.next_seq, now)
        self._log_link_changes(now)
        self._refresh_header(team, now)

    def _log_link_changes(self, now):
        for tid in self.fleet.team_ids():
            link, age = self.fleet.team_link(tid, now)
            previous = self._team_links.get(tid)
            if link == previous:
                continue
            self._team_links[tid] = link
            if link == "LOST":
                self._log(
                    f"[WARN] {tid} GCS link lost: no heartbeat for {format_age(age)}")
            elif link == "NO HEARTBEAT" and age > STALE_SECONDS:
                self._log(
                    f"[WARN] {tid} GCS sent no heartbeats ({format_age(age)} since its last "
                    f"message); is the vehicle side publishing?")
            elif link == "NO HEARTBEAT":
                self._team_links.pop(tid, None)     # re-check once the grace period passes
                continue
            elif link == "UP" and previous in ("LOST", "NO HEARTBEAT"):
                self._log(f"{tid} GCS link restored")

    def _refresh_header(self, team, now):
        teams = [self.fleet.teams[t] for t in self.fleet.team_ids() if team in (None, t)]
        if not teams:
            set_chip(self.run_chip, "NO TEAMS", theme.IDLE)
        elif len(teams) == 1:
            t = teams[0]
            run = t.run_state + (f" · RUN {t.run_id}" if t.run_id is not None else "")
            link, age = self.fleet.team_link(t.team_id, now)
            if link == "LOST":
                set_chip(self.run_chip, f"{t.team_id} {run} · LINK LOST {format_age(age)}", theme.FAULT)
            elif link == "NO HEARTBEAT" and age > STALE_SECONDS:
                set_chip(self.run_chip, f"{t.team_id} {run} · NO HEARTBEAT {format_age(age)}", theme.FAULT)
            else:
                set_chip(self.run_chip, f"{t.team_id} {run}", RUN_COLORS.get(t.run_state, theme.IDLE))
        else:
            set_chip(self.run_chip, f"{len(teams)} TEAMS", theme.TEXT_MUTED)

        tracks = self.fleet.vehicles_of(team)
        live = sum(1 for v in tracks if v.age(now) is not None and v.age(now) <= STALE_SECONDS)
        if not tracks:
            set_chip(self.live_chip, "0 LIVE", theme.IDLE)
        else:
            set_chip(self.live_chip, f"{live}/{len(tracks)} LIVE",
                     theme.OK if live == len(tracks) else theme.WARN)

    def _sync_team_filter(self):
        known = [self.team_filter.itemText(i) for i in range(1, self.team_filter.count())]
        teams = self.fleet.team_ids()
        if known == teams:
            return
        current = self.team_filter.currentText()
        self.team_filter.blockSignals(True)
        self.team_filter.clear()
        self.team_filter.addItems([ALL_TEAMS, *teams])
        self.team_filter.setCurrentText(current if current in teams else ALL_TEAMS)
        self.team_filter.blockSignals(False)

    def _log(self, text: str):
        self.log_panel.append_log(text)
        self.recorder.note(f"[{time.strftime('%H:%M:%S')}] {text}")

    def _log_notices(self, notices):
        for line in notices:
            self._log(line)

    def closeEvent(self, event):
        for team_id in self.recorder.active_teams():
            self._close_run_log(team_id, "console closed during the run")
        self.mqtt.stop()
        self.mqtt.wait(2000)
        for tab in (self.task1_tab, self.task3_tab):
            tab.runner.wait()           # device calls time out within TIMEOUT_S
        event.accept()
