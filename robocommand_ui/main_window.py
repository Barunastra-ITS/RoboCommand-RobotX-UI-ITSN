"""Main window for RoboCommand RobotX 2026 OCS UI.

Two pages:
  - Monitoring  : big top-down course map (left) + read-only vehicle telemetry
                  (right), course config, commands, and sequence numbers.
  - Sending     : the tools for publishing RunDeclaration and every task report.

A connection bar sits on top and a message log strip stays visible at the bottom
on both pages, so connection changes, publications, and received commands are
always visible to the operator (handbook 3.4.13).
"""

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QScrollArea,
    QTabWidget, QLabel, QFrame,
)
from PyQt5.QtCore import Qt, QTimer

from robocommand_ui.mqtt_worker import MqttWorker
from robocommand_ui.widgets.connection_bar import ConnectionBar
from robocommand_ui.widgets.course_panel import CoursePanel
from robocommand_ui.widgets.course_map import CourseMapWidget
from robocommand_ui.widgets.vehicle_monitor import VehicleMonitorPanel
from robocommand_ui.widgets.run_declaration_panel import RunDeclarationPanel
from robocommand_ui.widgets.commands_reports_panel import CommandsPanel, ReportsPanel
from robocommand_ui.widgets.log_panel import LogPanel
from robocommand_ui.widgets.sequence_panel import SequencePanel
from robocommand_ui.proto_helper import rx_common_pb2, vehicle_type_name

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
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RoboCommand RobotX 2026 — OCS Control Station (ITSN)")
        self.setMinimumSize(1280, 800)
        self.resize(1520, 940)

        self._apply_dark_theme()

        self.mqtt = MqttWorker(self)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ---- connection bar (top) ----
        self.connection_bar = ConnectionBar()
        main_layout.addWidget(self.connection_bar)

        # ---- persistent status strip ----
        self.status_strip = QFrame()
        self.status_strip.setObjectName("statusStrip")
        self.status_strip.setStyleSheet(STRIP_STYLE)
        strip_layout = QHBoxLayout(self.status_strip)
        strip_layout.setContentsMargins(10, 4, 10, 4)
        self.run_state_label = QLabel("Run: IDLE")
        self.run_state_label.setStyleSheet("font-weight: bold; color: #6c7086;")
        strip_layout.addWidget(self.run_state_label)
        self.course_id_label = QLabel("Course: ---")
        self.course_id_label.setStyleSheet("color: #89b4fa;")
        strip_layout.addWidget(self.course_id_label)
        self.team_label = QLabel("Team: ---")
        strip_layout.addWidget(self.team_label)
        strip_layout.addStretch()
        strip_layout.addWidget(QLabel("RoboCommand  RobotX 2026  OCS"))
        main_layout.addWidget(self.status_strip)

        # ---- two pages ----
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_monitor_page(), "Monitoring")
        self.tabs.addTab(self._build_sending_page(), "Sending / Testing")
        main_layout.addWidget(self.tabs, 1)

        # ---- persistent log strip (bottom) ----
        self.log_panel = LogPanel()
        self.log_panel.log_view.setFixedHeight(150)
        main_layout.addWidget(self.log_panel)

        self.statusBar().showMessage("Ready. Configure the connection and press Connect.")
        self.statusBar().setStyleSheet("background-color: #11111b; color: #6c7086;")

        self._connect_signals()

        self._seq_timer = QTimer(self)
        self._seq_timer.timeout.connect(self._update_seq_display)
        self._seq_timer.start(500)

        self._run_state = "IDLE"
        self._declared_vehicles = []

    # ---------- page builders ----------
    def _build_monitor_page(self):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(6, 6, 6, 6)
        split = QSplitter(Qt.Horizontal)

        # Left: the big course map
        self.course_map = CourseMapWidget()
        split.addWidget(self.course_map)

        # Right: course config + vehicle telemetry + commands + sequence
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 6, 0)
        right_layout.setSpacing(6)
        self.course_panel = CoursePanel()
        right_layout.addWidget(self.course_panel)
        self.vehicle_monitor = VehicleMonitorPanel()
        right_layout.addWidget(self.vehicle_monitor, 1)
        self.commands_panel = CommandsPanel()
        right_layout.addWidget(self.commands_panel)
        self.sequence_panel = SequencePanel()
        right_layout.addWidget(self.sequence_panel)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setWidget(right)
        right_scroll.setStyleSheet("QScrollArea { border: none; background-color: #1e1e2e; }")
        split.addWidget(right_scroll)

        split.setSizes([860, 560])
        page_layout.addWidget(split)
        return page

    def _build_sending_page(self):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(6, 6, 6, 6)
        split = QSplitter(Qt.Horizontal)

        self.declaration_panel = RunDeclarationPanel()
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(self.declaration_panel)
        left_scroll.setStyleSheet("QScrollArea { border: none; background-color: #1e1e2e; }")
        split.addWidget(left_scroll)

        self.reports_panel = ReportsPanel()
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setWidget(self.reports_panel)
        right_scroll.setStyleSheet("QScrollArea { border: none; background-color: #1e1e2e; }")
        split.addWidget(right_scroll)

        split.setSizes([520, 880])
        page_layout.addWidget(split)
        return page

    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e2e;
            }
            QWidget {
                background-color: #1e1e2e;
                color: #cdd6f4;
            }
            QTabWidget::pane {
                border: 1px solid #313244;
                background-color: #1e1e2e;
                top: 1px;
            }
            QTabBar::tab {
                background-color: #181825;
                color: #a6adc8;
                padding: 7px 16px;
                border: 1px solid #313244;
                border-bottom: none;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background-color: #1e1e2e;
                color: #cdd6f4;
            }
            QScrollBar:vertical {
                background: #1e1e2e;
                width: 10px;
            }
            QScrollBar::handle:vertical {
                background: #45475a;
                border-radius: 5px;
            }
            QScrollBar:horizontal {
                background: #1e1e2e;
                height: 10px;
            }
            QScrollBar::handle:horizontal {
                background: #45475a;
                border-radius: 5px;
            }
            QScrollBar::add-line, QScrollBar::sub-line {
                height: 0px; width: 0px;
            }
        """)

    # ---------- signal wiring ----------
    def _connect_signals(self):
        self.connection_bar.connect_requested.connect(self._on_connect)
        self.connection_bar.disconnect_requested.connect(self._on_disconnect)

        self.mqtt.connected.connect(self._on_mqtt_connected)
        self.mqtt.disconnected.connect(self._on_mqtt_disconnected)
        self.mqtt.connection_error.connect(self._on_mqtt_error)
        self.mqtt.course_received.connect(self._on_course_received)
        self.mqtt.command_received.connect(self._on_command_received)
        self.mqtt.log_message.connect(self._on_log)
        self.mqtt.report_sent.connect(self._on_report_sent)
        self.mqtt.request_sent.connect(self._on_request_sent)

        self.declaration_panel.send_declaration.connect(self._on_send_declaration)

        hb = self.reports_panel.heartbeat_tab
        hb.send_heartbeat.connect(self._on_send_heartbeat)
        hb.send_heartbeat_multi.connect(self._on_send_heartbeats_multi)

        rp = self.reports_panel
        rp.safe_passage_tab.send_safe_passage.connect(self._on_send_safe_passage)
        rp.pipeline_tab.send_pipeline_survey.connect(self._on_send_pipeline_survey)

        tr = self.reports_panel.task_reports_tab
        tr.send_incident_ack.connect(self._on_send_incident_ack)
        tr.send_readiness.connect(self._on_send_readiness)
        tr.send_docking.connect(self._on_send_docking)
        tr.send_firefighting.connect(self._on_send_firefighting)
        tr.send_resource_delivery.connect(self._on_send_resource_delivery)

    # ---------- connection ----------
    def _on_connect(self, host: str, port: int, team_id: str):
        self.mqtt.configure(host, port, team_id)
        self.mqtt.seq.reset()
        self._run_state = "IDLE"
        self.sequence_panel.set_run_state("IDLE")
        self._set_run_state_label()
        self.team_label.setText(f"Team: {team_id}")
        self.vehicle_monitor.clear()
        self.course_map.clear_vehicles()
        self.course_map.clear_task_data()
        self.mqtt.start()

    def _on_disconnect(self):
        self.mqtt.stop()

    def _on_mqtt_connected(self):
        self.connection_bar.set_connected(True)
        self.declaration_panel.set_enabled(True)
        self.statusBar().showMessage(
            f"Connected to {self.mqtt._broker_host}:{self.mqtt._broker_port} as {self.mqtt.team_id}")

    def _on_mqtt_disconnected(self):
        self.connection_bar.set_connected(False)
        self.declaration_panel.set_enabled(False)
        self.statusBar().showMessage("Disconnected.")

    def _on_mqtt_error(self, err: str):
        self.connection_bar.set_error(err)
        self.statusBar().showMessage(f"Connection error: {err}")

    # ---------- received ----------
    def _on_course_received(self, course):
        from robocommand_ui.widgets.course_panel import validate_course
        issues = validate_course(course)
        self.course_panel.update_course(course)
        self.course_map.set_course(course)
        self.course_id_label.setText(f"Course: {course.course_id}")
        if issues:
            msg = f"Course {course.course_id or '<no id>'} INVALID: {issues[0]}"
            self.statusBar().showMessage(msg)
            self.log_panel.append_log(f"[ERROR] {msg}")
        else:
            self.statusBar().showMessage(f"Course received: {course.course_id} (valid)")
            self.log_panel.append_log(f"Course configuration validated: {course.course_id}")

    def _on_command_received(self, command, body_name: str):
        self.commands_panel.add_command(command, body_name)
        if body_name == "run_start":
            self._run_state = "ACTIVE"
            self.sequence_panel.set_run_state("ACTIVE", command.run_start.run_id)
            self._set_run_state_label()
        self._record_command_to_monitor(body_name, command)

    def _on_log(self, text: str):
        self.log_panel.append_log(text)

    def _on_report_sent(self, text: str):
        self.log_panel.append_log(f"[SENT] {text}")

    def _on_request_sent(self, text: str):
        self.log_panel.append_log(f"[SENT] {text}")
        if self._run_state == "IDLE":
            self._run_state = "DECLARED"
            self.sequence_panel.set_run_state("DECLARED")
            self._set_run_state_label()

    # ---------- sending ----------
    def _on_send_declaration(self, vehicles, t1, t2, t3, t4, geofence):
        self.mqtt.publish_run_declaration(vehicles, t1, t2, t3, t4, geofence)
        self._declared_vehicles = list(vehicles)
        self.course_map.set_geofence(geofence)
        self.reports_panel.heartbeat_tab.set_auto_vehicles(vehicles)
        for vid in vehicles:
            if vid.upper().startswith("USV"):
                self.reports_panel.heartbeat_tab.type_combo.setCurrentText("TYPE_USV")
            elif vid.upper().startswith("UUV"):
                self.reports_panel.heartbeat_tab.type_combo.setCurrentText("TYPE_UUV")
            elif vid.upper().startswith("UAV"):
                self.reports_panel.heartbeat_tab.type_combo.setCurrentText("TYPE_UAV")

    def _on_send_heartbeat(
        self, vehicle_id, state, lat, lng, speed, heading, vtype, task,
        roll=0.0, pitch=0.0, altitude=0.0, depth=0.0, flight_phase=0,
    ):
        self.mqtt.publish_heartbeat(
            vehicle_id=vehicle_id, state=state, lat=lat, lng=lng,
            speed=speed, heading=heading, vehicle_type=vtype,
            current_task=task, roll=roll, pitch=pitch,
            altitude=altitude, depth=depth, flight_phase=flight_phase,
        )
        from robocommand_ui.proto_helper import rx_reports_pb2, common_pb2
        hb = rx_reports_pb2.Heartbeat(
            state=state,
            position=common_pb2.LatLng(latitude=lat, longitude=lng),
            spd_mps=speed,
            heading_deg=heading,
            roll_deg=roll,
            pitch_deg=pitch,
            altitude_hae_m=altitude,
            depth_m=depth,
            vehicle_type=vtype,
            current_task=task,
            flight_phase=flight_phase,
        )
        seq = self.mqtt.seq.get_report_seq(vehicle_id)
        self.vehicle_monitor.record_heartbeat(vehicle_id, hb, seq)
        self.course_map.update_vehicle(vehicle_id, hb, seq)

    def _on_send_safe_passage(self, vehicle_id, entry_lat, entry_lng, exit_lat, exit_lng, buoys):
        self.mqtt.publish_safe_passage_report(
            vehicle_id, entry_lat, entry_lng, exit_lat, exit_lng, buoys
        )
        self.course_map.set_safe_passage(
            (entry_lat, entry_lng), (exit_lat, exit_lng),
            [(b["lat"], b["lng"], b["state"]) for b in buoys]
        )
        self.vehicle_monitor.record_report(vehicle_id, "safe_passage")

    def _on_send_pipeline_survey(self, vehicle_id, lat, lng, segments):
        self.mqtt.publish_pipeline_survey(vehicle_id, lat, lng, segments)
        self.course_map.set_pipeline((lat, lng), segments)
        self.vehicle_monitor.record_report(vehicle_id, "pipeline_survey")

    def _on_send_heartbeats_multi(
        self, vehicle_ids, state, lat, lng, speed, heading, task,
        roll, pitch, altitude, depth, flight_phase,
    ):
        for vid in vehicle_ids:
            upper = vid.upper()
            if upper.startswith("USV"):
                vtype = rx_common_pb2.TYPE_USV
            elif upper.startswith("UUV"):
                vtype = rx_common_pb2.TYPE_UUV
            elif upper.startswith("UAV"):
                vtype = rx_common_pb2.TYPE_UAV
            else:
                vtype = rx_common_pb2.TYPE_UNKNOWN
            self._on_send_heartbeat(
                vid, state, lat, lng, speed, heading, vtype, task,
                roll, pitch, altitude, depth, flight_phase,
            )

    def _on_send_incident_ack(self, vehicle_id, cmd_seq):
        self.mqtt.publish_incident_ack(vehicle_id, cmd_seq)
        self.vehicle_monitor.record_report(vehicle_id, "incident_ack")

    def _on_send_readiness(self, vehicle_id, cmd_seq):
        self.mqtt.publish_readiness_report(vehicle_id, cmd_seq)
        self.vehicle_monitor.record_report(vehicle_id, "readiness")

    def _on_send_docking(self, vehicle_id, bay_id):
        self.mqtt.publish_docking_report(vehicle_id, bay_id)
        self.vehicle_monitor.record_report(vehicle_id, "docking")

    def _on_send_firefighting(self, vehicle_id, window_id):
        self.mqtt.publish_firefighting_report(vehicle_id, window_id)
        self.vehicle_monitor.record_report(vehicle_id, "firefighting")

    def _on_send_resource_delivery(self, vehicle_id, task, res_color, circle_color):
        self.mqtt.publish_resource_delivery(vehicle_id, task, res_color, circle_color)
        self.vehicle_monitor.record_report(vehicle_id, "resource_delivery")

    # ---------- helpers ----------
    def _set_run_state_label(self):
        text = {
            "IDLE": ("Run: IDLE", "#6c7086"),
            "DECLARED": ("Run: DECLARED (awaiting RunStart)", "#f9e2af"),
            "ACTIVE": ("Run: ACTIVE", "#a6e3a1"),
        }.get(self._run_state, ("Run: IDLE", "#6c7086"))
        self.run_state_label.setText(text[0])
        self.run_state_label.setStyleSheet(f"font-weight: bold; color: {text[1]};")

    def _record_command_to_monitor(self, body_name, command):
        mon = self.vehicle_monitor
        if body_name == "run_start":
            targets = mon.all_vehicle_ids() or self._declared_vehicles
            text = (f"RunStart run_id={command.run_start.run_id} "
                    f"decl_seq={command.run_start.declaration_seq}")
        elif body_name == "assistance_request":
            t = command.assistance_request.vehicle_type
            targets = mon.vehicle_ids_of_type(t)
            text = f"AssistanceRequest seq={command.seq} ({vehicle_type_name(t)})"
        elif body_name == "keep_out_zone":
            t = command.keep_out_zone.vehicle_type
            targets = mon.vehicle_ids_of_type(t)
            text = f"KeepOutZone seq={command.seq} r={command.keep_out_zone.radius_m:.0f}m"
        elif body_name == "all_clear":
            t = command.all_clear.vehicle_type
            targets = mon.vehicle_ids_of_type(t)
            text = f"AllClear seq={command.seq} ({vehicle_type_name(t)})"
        elif body_name == "moving_object_alert":
            targets = set()
            for t in command.moving_object_alert.affected_vehicle_types:
                targets.update(mon.vehicle_ids_of_type(t))
            text = f"MovingObjectAlert seq={command.seq}"
        elif body_name == "readiness_confirm":
            targets = [command.readiness_confirm.vehicle_id]
            text = (f"ReadinessConfirm seq={command.seq} "
                    f"report_seq={command.readiness_confirm.report_seq}")
        else:
            return
        mon.record_command(targets, text)

    def _update_seq_display(self):
        self.sequence_panel.update_from_tracker(self.mqtt.seq)

    def closeEvent(self, event):
        self.mqtt.stop()
        self.mqtt.wait(2000)
        event.accept()
