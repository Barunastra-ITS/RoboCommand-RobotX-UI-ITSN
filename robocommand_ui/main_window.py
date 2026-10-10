"""Main window of the RoboCommand host monitor.

Runs on the course RoboCommand host (e.g. 192.168.65.2 for Course Alpha) and
shows what every team's GCS/OCS reports to it: the boat movement on a course
map, per-vehicle telemetry, and each team's run status. It only listens on
``robocommand/robotx/#`` and never publishes.

Layout: connection bar, status strip with a team filter, then the course map
(left) beside course config, team status and vehicle cards (right), with the
message log pinned at the bottom.
"""

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow, QScrollArea, QSplitter,
    QVBoxLayout, QWidget,
)

from robocommand_ui.course_validation import validate_course
from robocommand_ui.fleet_state import FleetState
from robocommand_ui.mqtt_worker import MqttWorker
from robocommand_ui.widgets.connection_bar import ConnectionBar
from robocommand_ui.widgets.course_map import CourseMapWidget
from robocommand_ui.widgets.course_panel import CoursePanel
from robocommand_ui.widgets.log_panel import LogPanel
from robocommand_ui.widgets.teams_panel import TeamsPanel
from robocommand_ui.widgets.vehicle_monitor import VehicleMonitorPanel

ALL_TEAMS = "All teams"
REFRESH_MS = 500            # matches the 2 Hz heartbeat rate

STRIP_STYLE = """
    QFrame#statusStrip {
        background-color: #11111b;
        border-bottom: 1px solid #313244;
    }
    QFrame#statusStrip QLabel {
        color: #cdd6f4;
        font-size: 12px;
        padding: 0 6px;
    }
    QComboBox {
        background-color: #313244;
        color: #cdd6f4;
        border: 1px solid #45475a;
        border-radius: 4px;
        padding: 2px 8px;
    }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RoboCommand RobotX 2026 — Host Monitor")
        self.setMinimumSize(1280, 800)
        self.resize(1520, 940)
        self._apply_dark_theme()

        self.fleet = FleetState()
        self.mqtt = MqttWorker(self)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.connection_bar = ConnectionBar()
        main_layout.addWidget(self.connection_bar)
        main_layout.addWidget(self._build_status_strip())
        main_layout.addWidget(self._build_monitor_page(), 1)

        self.log_panel = LogPanel()
        self.log_panel.log_view.setFixedHeight(150)
        main_layout.addWidget(self.log_panel)

        self.statusBar().showMessage("Ready. Choose the broker and press Connect.")
        self.statusBar().setStyleSheet("background-color: #11111b; color: #6c7086;")

        self._connect_signals()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh_views)
        self._refresh_timer.start(REFRESH_MS)

    # ---------- builders ----------
    def _build_status_strip(self):
        strip = QFrame()
        strip.setObjectName("statusStrip")
        strip.setStyleSheet(STRIP_STYLE)
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(10, 4, 10, 4)
        self.course_id_label = QLabel("Course: ---")
        self.course_id_label.setStyleSheet("color: #89b4fa;")
        layout.addWidget(self.course_id_label)
        layout.addWidget(QLabel("Show:"))
        self.team_filter = QComboBox()
        self.team_filter.addItem(ALL_TEAMS)
        self.team_filter.setMinimumWidth(120)
        self.team_filter.currentIndexChanged.connect(self.refresh_views)
        layout.addWidget(self.team_filter)
        layout.addStretch()
        layout.addWidget(QLabel("RoboCommand  RobotX 2026  Host Monitor (listen-only)"))
        return strip

    def _build_monitor_page(self):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(6, 6, 6, 6)
        split = QSplitter(Qt.Horizontal)

        self.course_map = CourseMapWidget()
        split.addWidget(self.course_map)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 6, 0)
        right_layout.setSpacing(6)
        self.course_panel = CoursePanel()
        right_layout.addWidget(self.course_panel)
        self.teams_panel = TeamsPanel()
        right_layout.addWidget(self.teams_panel)
        self.vehicle_monitor = VehicleMonitorPanel()
        right_layout.addWidget(self.vehicle_monitor, 1)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setWidget(right)
        right_scroll.setStyleSheet("QScrollArea { border: none; background-color: #1e1e2e; }")
        split.addWidget(right_scroll)

        split.setSizes([900, 560])
        page_layout.addWidget(split)
        return page

    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e2e; }
            QWidget { background-color: #1e1e2e; color: #cdd6f4; }
            QScrollBar:vertical { background: #1e1e2e; width: 10px; }
            QScrollBar::handle:vertical { background: #45475a; border-radius: 5px; }
            QScrollBar:horizontal { background: #1e1e2e; height: 10px; }
            QScrollBar::handle:horizontal { background: #45475a; border-radius: 5px; }
            QScrollBar::add-line, QScrollBar::sub-line { height: 0px; width: 0px; }
        """)

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
        self.course_id_label.setText(f"Course: {course.course_id}")
        if issues:
            msg = f"Course {course.course_id or '<no id>'} INVALID: {issues[0]}"
            self.statusBar().showMessage(msg)
            self.log_panel.append_log(f"[ERROR] {msg}")
        else:
            self.log_panel.append_log(f"[RxCourse] {course.course_id} valid")

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
        team = self.selected_team()
        self.course_map.show_fleet(self.fleet, team)
        self.vehicle_monitor.refresh(self.fleet, team)
        self.teams_panel.refresh(self.fleet)

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
