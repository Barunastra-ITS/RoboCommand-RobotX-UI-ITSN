"""Main window of the RoboCommand host monitor.

Runs on the course RoboCommand host (e.g. 192.168.65.2 for Course Alpha) and
shows what every team's GCS/OCS reports to it: the boat movement on a course
map, per-vehicle telemetry, and each team's run status. It only listens on
``robocommand/robotx/#`` and never publishes.

Layout: a header (brand, course/run/live chips, team filter, connection),
the course map with the log drawer beneath it, and a right rail with teams,
vehicles and the course summary.
"""

import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow, QScrollArea,
    QSplitter, QVBoxLayout, QWidget,
)

from robocommand_ui import theme
from robocommand_ui.course_validation import validate_course
from robocommand_ui.fleet_state import STALE_SECONDS, FleetState
from robocommand_ui.mqtt_worker import MqttWorker
from robocommand_ui.widgets.connection_bar import ConnectionBar
from robocommand_ui.widgets.course_map import CourseMapWidget
from robocommand_ui.widgets.course_panel import CoursePanel
from robocommand_ui.widgets.log_panel import LogPanel
from robocommand_ui.widgets.panel import make_chip, set_chip
from robocommand_ui.widgets.teams_panel import RUN_COLORS, TeamsPanel, format_age
from robocommand_ui.widgets.vehicle_monitor import VehicleMonitorPanel

ALL_TEAMS = "All teams"
REFRESH_MS = 500            # matches the 2 Hz heartbeat rate
RAIL_WIDTH = 440


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RoboCommand Host Monitor — RobotX 2026")
        self.setMinimumSize(1280, 780)
        self.resize(1560, 960)
        app = QApplication.instance()
        if app is not None:
            theme.apply(app)

        self.fleet = FleetState()
        self._team_links = {}       # team_id -> last logged link state
        self.mqtt = MqttWorker(self)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_header())
        layout.addWidget(self._build_body(), 1)

        self.statusBar().showMessage("Ready. Choose the broker and press Connect.")
        self._connect_signals()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh_views)
        self._refresh_timer.start(REFRESH_MS)

    # ---------- builders ----------
    def _build_header(self):
        header = QFrame()
        header.setObjectName("Header")
        row = QHBoxLayout(header)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(10)

        brand = QVBoxLayout()
        brand.setSpacing(0)
        title = QLabel("ROBOCOMMAND")
        title.setObjectName("Brand")
        sub = QLabel("Host monitor · listen-only")
        sub.setObjectName("BrandSub")
        brand.addWidget(title)
        brand.addWidget(sub)
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
        divider.setStyleSheet(f"background: {theme.BORDER};")
        row.addWidget(divider)

        self.connection_bar = ConnectionBar()
        row.addWidget(self.connection_bar)
        return header

    def _build_body(self):
        body = QSplitter(Qt.Horizontal)
        body.setHandleWidth(10)

        left = QSplitter(Qt.Vertical)
        left.setHandleWidth(10)
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
        wl.setContentsMargins(10, 10, 10, 10)
        wl.addWidget(body)
        return wrap

    # ---------- signal wiring ----------
    def _connect_signals(self):
        self.connection_bar.connect_requested.connect(self._on_connect)
        self.connection_bar.disconnect_requested.connect(self._on_disconnect)

        self.mqtt.connected.connect(self._on_mqtt_connected)
        self.mqtt.disconnected.connect(self._on_mqtt_disconnected)
        self.mqtt.connection_error.connect(self._on_mqtt_error)
        self.mqtt.log_message.connect(self.log_panel.append_log)
        self.mqtt.course_received.connect(self._on_course_received)
        self.mqtt.report_received.connect(self._on_report)
        self.mqtt.request_received.connect(self._on_request)
        self.mqtt.command_received.connect(self._on_command)

    # ---------- connection ----------
    def _on_connect(self, host: str, port: int):
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
        self.statusBar().showMessage(f"Monitoring {self.mqtt.broker} (listen-only)")

    def _on_mqtt_disconnected(self):
        self.connection_bar.set_connected(False)
        self.statusBar().showMessage("Disconnected.")

    def _on_mqtt_error(self, err: str):
        self.connection_bar.set_error(err)
        self.statusBar().showMessage(f"Connection error: {err}")

    # ---------- received ----------
    def _on_course_received(self, course):
        issues = validate_course(course)
        self.course_panel.update_course(course)
        self.course_map.set_course(course)
        name = course.course_id or "<no id>"
        if issues:
            set_chip(self.course_id_label, f"COURSE {name} · INVALID", theme.FAULT)
            self.course_id_label.setToolTip("; ".join(issues))
            msg = f"Course {name} INVALID: {issues[0]}"
            self.statusBar().showMessage(msg)
            self.log_panel.append_log(f"[ERROR] {msg}")
        else:
            set_chip(self.course_id_label, f"COURSE {name}", theme.TEXT_MUTED)
            self.course_id_label.setToolTip(f"{course.pinger_freq_hz} Hz pinger, "
                                            f"{len(course.corners)} corners")
            self.log_panel.append_log(f"[RxCourse] {name} valid")

    def _on_report(self, team_id: str, vehicle_id: str, report):
        is_new = (team_id, vehicle_id) not in self.fleet.vehicles
        self._log_notices(self.fleet.ingest_report(team_id, vehicle_id, report))
        body = report.WhichOneof("body")
        if body and body != "heartbeat":
            self.log_panel.append_log(f"[RxReport] {team_id}/{vehicle_id} seq={report.seq} {body}")
        if is_new and (team_id, vehicle_id) in self.fleet.vehicles:
            self.log_panel.append_log(f"New vehicle reporting: {team_id}/{vehicle_id}")
            self._sync_team_filter()

    def _on_request(self, team_id: str, request):
        self.log_panel.append_log(
            f"[RxRequest] {team_id} seq={request.seq} {request.WhichOneof('body')}")
        self._log_notices(self.fleet.ingest_request(team_id, request))
        self._sync_team_filter()

    def _on_command(self, team_id: str, command):
        self.log_panel.append_log(
            f"[RxCommand] {team_id} seq={command.seq} {command.WhichOneof('body')}")
        self._log_notices(self.fleet.ingest_command(team_id, command))
        self._sync_team_filter()

    # ---------- views ----------
    def selected_team(self):
        text = self.team_filter.currentText()
        return None if text in ("", ALL_TEAMS) else text

    def refresh_views(self):
        now = time.time()
        team = self.selected_team()
        self.course_map.show_fleet(self.fleet, team, now)
        self.vehicle_monitor.refresh(self.fleet, team, now)
        self.teams_panel.refresh(self.fleet, now)
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
                self.log_panel.append_log(
                    f"[WARN] {tid} GCS link lost: no heartbeat for {format_age(age)}")
            elif link == "UP" and previous == "LOST":
                self.log_panel.append_log(f"{tid} GCS link restored")

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

    def _log_notices(self, notices):
        for line in notices:
            self.log_panel.append_log(line)

    def closeEvent(self, event):
        self.mqtt.stop()
        self.mqtt.wait(2000)
        event.accept()
