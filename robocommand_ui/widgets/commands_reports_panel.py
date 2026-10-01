"""Panels for displaying incoming RxCommands and sending task reports."""

from PyQt5.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton,
    QComboBox, QLineEdit, QGridLayout, QFrame, QSpinBox, QDoubleSpinBox,
    QTabWidget, QWidget, QTableWidget, QTableWidgetItem, QHeaderView,
)
from PyQt5.QtCore import pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QColor, QTextCharFormat

from robocommand_ui.proto_helper import (
    robot_state_name, vehicle_type_name, rx_task_name, color_name,
    pipeline_segment_name, STATE_STR_MAP, TYPE_STR_MAP, TASK_STR_MAP,
    COLOR_STR_MAP, SEGMENT_STR_MAP, BEACON_STR_MAP, FLIGHT_STR_MAP,
    common_pb2, rx_common_pb2,
)

STYLE = """
    QGroupBox {
        font-weight: bold;
        color: #cdd6f4;
        border: 1px solid #45475a;
        border-radius: 6px;
        margin-top: 8px;
        padding: 12px 8px 8px 8px;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 4px;
    }
    QLabel { color: #cdd6f4; }
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
        background-color: #313244;
        color: #cdd6f4;
        border: 1px solid #45475a;
        border-radius: 4px;
        padding: 3px 6px;
    }
    QPushButton {
        background-color: #89b4fa;
        color: #11111b;
        font-weight: bold;
        border-radius: 4px;
        padding: 5px 12px;
    }
    QPushButton:hover {
        background-color: #74c7ec;
    }
    QPushButton:disabled {
        background-color: #45475a;
        color: #6c7086;
    }
    QTextEdit {
        background-color: #11111b;
        color: #cdd6f4;
        border: 1px solid #45475a;
        border-radius: 4px;
        font-family: monospace;
        font-size: 11px;
    }
    QTabWidget::pane {
        border: 1px solid #45475a;
        background-color: #1e1e2e;
    }
    QTabBar::tab {
        background-color: #313244;
        color: #cdd6f4;
        padding: 6px 12px;
        border: 1px solid #45475a;
        border-bottom: none;
        border-top-left-radius: 4px;
        border-top-right-radius: 4px;
    }
    QTabBar::tab:selected {
        background-color: #1e1e2e;
        font-weight: bold;
    }
"""


class CommandsPanel(QGroupBox):
    """Displays received RxCommands from RoboCommand."""

    def __init__(self, parent=None):
        super().__init__("Received Commands (RxCommand)", parent)
        self.setStyleSheet(STYLE)
        layout = QVBoxLayout(self)

        self.run_status_label = QLabel("Run: Not started")
        self.run_status_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #f9e2af;")
        layout.addWidget(self.run_status_label)

        self.command_log = QTextEdit()
        self.command_log.setReadOnly(True)
        self.command_log.setMaximumHeight(200)
        layout.addWidget(self.command_log)

        self._run_id = None
        self._declaration_seq = None

    def add_command(self, command, body_name: str):
        import datetime
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        text = f"[{ts}] seq={command.seq} | {body_name}"

        if body_name == "run_start":
            rs = command.run_start
            text += f" | run_id={rs.run_id} declaration_seq={rs.declaration_seq}"
            self._run_id = rs.run_id
            self._declaration_seq = rs.declaration_seq
            self.run_status_label.setText(
                f"Run: ACTIVE (run_id={rs.run_id}, decl_seq={rs.declaration_seq})"
            )
            self.run_status_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #a6e3a1;")
        elif body_name == "assistance_request":
            ar = command.assistance_request
            text += (f" | type={vehicle_type_name(ar.vehicle_type)} "
                     f"pos=({ar.position.latitude:.6f},{ar.position.longitude:.6f})")
        elif body_name == "keep_out_zone":
            koz = command.keep_out_zone
            text += (f" | type={vehicle_type_name(koz.vehicle_type)} "
                     f"center=({koz.center.latitude:.6f},{koz.center.longitude:.6f}) "
                     f"radius={koz.radius_m:.1f}m")
        elif body_name == "all_clear":
            ac = command.all_clear
            text += f" | type={vehicle_type_name(ac.vehicle_type)}"
        elif body_name == "moving_object_alert":
            moa = command.moving_object_alert
            text += (f" | pos=({moa.position.latitude:.6f},{moa.position.longitude:.6f}) "
                     f"hdg={moa.heading_deg:.1f} spd={moa.speed_mps:.1f}")
        elif body_name == "readiness_confirm":
            rc = command.readiness_confirm
            text += f" | report_seq={rc.report_seq} vehicle={rc.vehicle_id}"

        self.command_log.append(text)

    @property
    def run_id(self):
        return self._run_id


class HeartbeatSender(QWidget):
    send_heartbeat = pyqtSignal(str, int, float, float, float, float, int, int, float, float, float, float, int)
    send_heartbeat_multi = pyqtSignal(list, int, float, float, float, float, int, float, float, float, float, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setSpacing(4)

        layout.addWidget(QLabel("Vehicle:"), 0, 0)
        self.vehicle_input = QComboBox()
        self.vehicle_input.setEditable(True)
        self.vehicle_input.addItems(["USV1", "UUV1", "UAV1"])
        layout.addWidget(self.vehicle_input, 0, 1)

        layout.addWidget(QLabel("State:"), 0, 2)
        self.state_combo = QComboBox()
        self.state_combo.addItems(["STATE_AUTO", "STATE_MANUAL", "STATE_KILLED"])
        layout.addWidget(self.state_combo, 0, 3)

        layout.addWidget(QLabel("Type:"), 1, 0)
        self.type_combo = QComboBox()
        self.type_combo.addItems(["TYPE_USV", "TYPE_UUV", "TYPE_UAV"])
        layout.addWidget(self.type_combo, 1, 1)

        layout.addWidget(QLabel("Task:"), 1, 2)
        self.task_combo = QComboBox()
        self.task_combo.addItems(list(TASK_STR_MAP.keys()))
        layout.addWidget(self.task_combo, 1, 3)

        layout.addWidget(QLabel("Lat:"), 2, 0)
        self.lat_input = QDoubleSpinBox()
        self.lat_input.setRange(-90, 90)
        self.lat_input.setDecimals(7)
        self.lat_input.setValue(1.2806142)
        layout.addWidget(self.lat_input, 2, 1)

        layout.addWidget(QLabel("Lng:"), 2, 2)
        self.lng_input = QDoubleSpinBox()
        self.lng_input.setRange(-180, 180)
        self.lng_input.setDecimals(7)
        self.lng_input.setValue(103.8557120)
        layout.addWidget(self.lng_input, 2, 3)

        layout.addWidget(QLabel("Speed:"), 3, 0)
        self.speed_input = QDoubleSpinBox()
        self.speed_input.setRange(0, 50)
        self.speed_input.setValue(0.0)
        layout.addWidget(self.speed_input, 3, 1)

        layout.addWidget(QLabel("Heading:"), 3, 2)
        self.heading_input = QDoubleSpinBox()
        self.heading_input.setRange(0, 360)
        self.heading_input.setValue(0.0)
        layout.addWidget(self.heading_input, 3, 3)

        # Per-task / attitude extras
        layout.addWidget(QLabel("Roll:"), 4, 0)
        self.roll_input = QDoubleSpinBox()
        self.roll_input.setRange(-180, 180)
        layout.addWidget(self.roll_input, 4, 1)

        layout.addWidget(QLabel("Pitch:"), 4, 2)
        self.pitch_input = QDoubleSpinBox()
        self.pitch_input.setRange(-180, 180)
        layout.addWidget(self.pitch_input, 4, 3)

        layout.addWidget(QLabel("Altitude:"), 5, 0)
        self.alt_input = QDoubleSpinBox()
        self.alt_input.setRange(-1000, 10000)
        layout.addWidget(self.alt_input, 5, 1)

        layout.addWidget(QLabel("Depth:"), 5, 2)
        self.depth_input = QDoubleSpinBox()
        self.depth_input.setRange(-1000, 1000)
        layout.addWidget(self.depth_input, 5, 3)

        layout.addWidget(QLabel("Flight Phase:"), 6, 0)
        self.flight_combo = QComboBox()
        self.flight_combo.addItems(list(FLIGHT_STR_MAP.keys()))
        layout.addWidget(self.flight_combo, 6, 1)

        # Manual send
        self.send_btn = QPushButton("Send Heartbeat")
        self.send_btn.clicked.connect(self._on_send)
        layout.addWidget(self.send_btn, 7, 0, 1, 4)

        # Auto heartbeat at 2Hz per handbook 3.4.11
        auto_layout = QHBoxLayout()
        self.auto_btn = QPushButton("Start Auto Heartbeat (2 Hz)")
        self.auto_btn.setCheckable(True)
        self.auto_btn.setStyleSheet("""
            QPushButton {
                background-color: #f9e2af;
                color: #11111b;
                font-weight: bold;
                border-radius: 4px;
                padding: 5px 12px;
            }
        """)
        self.auto_btn.toggled.connect(self._on_auto_toggled)
        auto_layout.addWidget(self.auto_btn)

        self.auto_vehicles = QLineEdit("USV1, UUV1, UAV1")
        self.auto_vehicles.setPlaceholderText("Vehicles to beacon for")
        auto_layout.addWidget(self.auto_vehicles, 1)
        layout.addLayout(auto_layout, 8, 0, 1, 4)

        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(500)
        self._auto_timer.timeout.connect(self._emit_auto_heartbeats)

    def _on_auto_toggled(self, checked: bool):
        if checked:
            self._auto_timer.start()
        else:
            self._auto_timer.stop()

    def _on_send(self):
        self._emit_heartbeat()

    def _emit_heartbeat(self):
        vid = self.vehicle_input.currentText().strip()
        state = STATE_STR_MAP.get(self.state_combo.currentText(), common_pb2.STATE_AUTO)
        vtype = TYPE_STR_MAP.get(self.type_combo.currentText(), rx_common_pb2.TYPE_USV)
        task = TASK_STR_MAP.get(self.task_combo.currentText(), rx_common_pb2.TASK_NONE)
        flight = FLIGHT_STR_MAP.get(self.flight_combo.currentText(),
                                    rx_common_pb2.FLIGHT_PHASE_UNKNOWN)
        self.send_heartbeat.emit(
            vid, state, self.lat_input.value(), self.lng_input.value(),
            self.speed_input.value(), self.heading_input.value(), vtype, task,
            self.roll_input.value(), self.pitch_input.value(),
            self.alt_input.value(), self.depth_input.value(), flight,
        )

    def _emit_auto_heartbeats(self):
        text = self.auto_vehicles.text().strip()
        vids = [v.strip() for v in text.split(",") if v.strip()]
        if not vids:
            return
        state = STATE_STR_MAP.get(self.state_combo.currentText(), common_pb2.STATE_AUTO)
        task = TASK_STR_MAP.get(self.task_combo.currentText(), rx_common_pb2.TASK_NONE)
        flight = FLIGHT_STR_MAP.get(self.flight_combo.currentText(),
                                    rx_common_pb2.FLIGHT_PHASE_UNKNOWN)
        self.send_heartbeat_multi.emit(
            vids, state, self.lat_input.value(), self.lng_input.value(),
            self.speed_input.value(), self.heading_input.value(), task,
            self.roll_input.value(), self.pitch_input.value(),
            self.alt_input.value(), self.depth_input.value(), flight,
        )

    def set_auto_vehicles(self, vehicle_ids):
        self.auto_vehicles.setText(", ".join(vehicle_ids))


class TaskReportSender(QWidget):
    send_incident_ack = pyqtSignal(str, int)
    send_readiness = pyqtSignal(str, int)
    send_docking = pyqtSignal(str, int)
    send_firefighting = pyqtSignal(str, int)
    send_pipeline_survey = pyqtSignal(str, float, float, list)
    send_resource_delivery = pyqtSignal(str, int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Incident Ack
        ack_frame = QFrame()
        ack_frame.setFrameShape(QFrame.StyledPanel)
        ack_layout = QHBoxLayout(ack_frame)
        ack_layout.addWidget(QLabel("IncidentAck:"))
        ack_layout.addWidget(QLabel("Vehicle:"))
        self.ack_vehicle = QComboBox()
        self.ack_vehicle.setEditable(True)
        self.ack_vehicle.addItems(["USV1", "UUV1", "UAV1"])
        ack_layout.addWidget(self.ack_vehicle)
        ack_layout.addWidget(QLabel("Cmd Seq:"))
        self.ack_seq = QSpinBox()
        self.ack_seq.setRange(0, 999999)
        ack_layout.addWidget(self.ack_seq)
        ack_btn = QPushButton("Send")
        ack_btn.clicked.connect(lambda: self.send_incident_ack.emit(
            self.ack_vehicle.currentText(), self.ack_seq.value()))
        ack_layout.addWidget(ack_btn)
        layout.addWidget(ack_frame)

        # Readiness Report
        rdy_frame = QFrame()
        rdy_frame.setFrameShape(QFrame.StyledPanel)
        rdy_layout = QHBoxLayout(rdy_frame)
        rdy_layout.addWidget(QLabel("ReadinessReport:"))
        rdy_layout.addWidget(QLabel("Vehicle:"))
        self.rdy_vehicle = QComboBox()
        self.rdy_vehicle.setEditable(True)
        self.rdy_vehicle.addItems(["USV1", "UUV1", "UAV1"])
        rdy_layout.addWidget(self.rdy_vehicle)
        rdy_layout.addWidget(QLabel("Cmd Seq:"))
        self.rdy_seq = QSpinBox()
        self.rdy_seq.setRange(0, 999999)
        rdy_layout.addWidget(self.rdy_seq)
        rdy_btn = QPushButton("Send")
        rdy_btn.clicked.connect(lambda: self.send_readiness.emit(
            self.rdy_vehicle.currentText(), self.rdy_seq.value()))
        rdy_layout.addWidget(rdy_btn)
        layout.addWidget(rdy_frame)

        # Docking Report
        dock_frame = QFrame()
        dock_frame.setFrameShape(QFrame.StyledPanel)
        dock_layout = QHBoxLayout(dock_frame)
        dock_layout.addWidget(QLabel("DockingReport:"))
        dock_layout.addWidget(QLabel("Vehicle:"))
        self.dock_vehicle = QComboBox()
        self.dock_vehicle.setEditable(True)
        self.dock_vehicle.addItems(["USV1"])
        dock_layout.addWidget(self.dock_vehicle)
        dock_layout.addWidget(QLabel("Bay ID:"))
        self.dock_bay = QSpinBox()
        self.dock_bay.setRange(1, 3)
        dock_layout.addWidget(self.dock_bay)
        dock_btn = QPushButton("Send")
        dock_btn.clicked.connect(lambda: self.send_docking.emit(
            self.dock_vehicle.currentText(), self.dock_bay.value()))
        dock_layout.addWidget(dock_btn)
        layout.addWidget(dock_frame)

        # Firefighting Report
        ff_frame = QFrame()
        ff_frame.setFrameShape(QFrame.StyledPanel)
        ff_layout = QHBoxLayout(ff_frame)
        ff_layout.addWidget(QLabel("FirefightingReport:"))
        ff_layout.addWidget(QLabel("Vehicle:"))
        self.ff_vehicle = QComboBox()
        self.ff_vehicle.setEditable(True)
        self.ff_vehicle.addItems(["USV1"])
        ff_layout.addWidget(self.ff_vehicle)
        ff_layout.addWidget(QLabel("Window:"))
        self.ff_window = QSpinBox()
        self.ff_window.setRange(1, 10)
        ff_layout.addWidget(self.ff_window)
        ff_btn = QPushButton("Send")
        ff_btn.clicked.connect(lambda: self.send_firefighting.emit(
            self.ff_vehicle.currentText(), self.ff_window.value()))
        ff_layout.addWidget(ff_btn)
        layout.addWidget(ff_frame)

        # Resource Delivery
        rd_frame = QFrame()
        rd_frame.setFrameShape(QFrame.StyledPanel)
        rd_layout = QHBoxLayout(rd_frame)
        rd_layout.addWidget(QLabel("ResourceDelivery:"))
        rd_layout.addWidget(QLabel("Vehicle:"))
        self.rd_vehicle = QComboBox()
        self.rd_vehicle.setEditable(True)
        self.rd_vehicle.addItems(["UAV1"])
        rd_layout.addWidget(self.rd_vehicle)
        rd_layout.addWidget(QLabel("Task:"))
        self.rd_task = QComboBox()
        self.rd_task.addItems(["TASK_INFRA_SURVEY_REPAIR", "TASK_COORDINATED_LOGISTICS"])
        rd_layout.addWidget(self.rd_task)
        rd_layout.addWidget(QLabel("Res:"))
        self.rd_res_color = QComboBox()
        self.rd_res_color.addItems(list(COLOR_STR_MAP.keys()))
        rd_layout.addWidget(self.rd_res_color)
        rd_layout.addWidget(QLabel("Circle:"))
        self.rd_circle_color = QComboBox()
        self.rd_circle_color.addItems(list(COLOR_STR_MAP.keys()))
        rd_layout.addWidget(self.rd_circle_color)
        rd_btn = QPushButton("Send")
        rd_btn.clicked.connect(self._on_send_rd)
        rd_layout.addWidget(rd_btn)
        layout.addWidget(rd_frame)

        layout.addStretch()

    def _on_send_rd(self):
        self.send_resource_delivery.emit(
            self.rd_vehicle.currentText(),
            TASK_STR_MAP.get(self.rd_task.currentText(), rx_common_pb2.TASK_UNKNOWN),
            COLOR_STR_MAP.get(self.rd_res_color.currentText(), rx_common_pb2.COLOR_UNKNOWN),
            COLOR_STR_MAP.get(self.rd_circle_color.currentText(), rx_common_pb2.COLOR_UNKNOWN),
        )


class SafePassageSender(QWidget):
    """Task 1: SafePassageReport — entry/exit positions plus detected buoys."""

    send_safe_passage = pyqtSignal(str, float, float, float, float, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # Vehicle + entry/exit
        grid = QGridLayout()
        grid.setSpacing(4)

        grid.addWidget(QLabel("Vehicle:"), 0, 0)
        self.vehicle_combo = QComboBox()
        self.vehicle_combo.setEditable(True)
        self.vehicle_combo.addItems(["USV1", "UUV1", "UAV1"])
        grid.addWidget(self.vehicle_combo, 0, 1)

        grid.addWidget(QLabel("Entry (FLASHING_BLUE):"), 0, 2)
        self.entry_lat = QDoubleSpinBox()
        self.entry_lat.setRange(-90, 90)
        self.entry_lat.setDecimals(7)
        self.entry_lat.setValue(1.2806142)
        grid.addWidget(self.entry_lat, 0, 3)
        self.entry_lng = QDoubleSpinBox()
        self.entry_lng.setRange(-180, 180)
        self.entry_lng.setDecimals(7)
        self.entry_lng.setValue(103.8557120)
        grid.addWidget(self.entry_lng, 0, 4)

        grid.addWidget(QLabel("Exit (STEADY_BLUE):"), 1, 2)
        self.exit_lat = QDoubleSpinBox()
        self.exit_lat.setRange(-90, 90)
        self.exit_lat.setDecimals(7)
        self.exit_lat.setValue(1.2807000)
        grid.addWidget(self.exit_lat, 1, 3)
        self.exit_lng = QDoubleSpinBox()
        self.exit_lng.setRange(-180, 180)
        self.exit_lng.setDecimals(7)
        self.exit_lng.setValue(103.8558000)
        grid.addWidget(self.exit_lng, 1, 4)

        layout.addLayout(grid)

        # Buoy table
        layout.addWidget(QLabel("Detected buoys (one row per detection):"))
        self.buoy_table = QTableWidget(0, 3)
        self.buoy_table.setHorizontalHeaderLabels(["Latitude", "Longitude", "Beacon State"])
        self.buoy_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.buoy_table.setMaximumHeight(140)
        self.buoy_table.setStyleSheet("""
            QTableWidget {
                background-color: #11111b;
                color: #cdd6f4;
                gridline-color: #45475a;
            }
            QHeaderView::section {
                background-color: #313244;
                color: #cdd6f4;
                font-weight: bold;
                border: 1px solid #45475a;
            }
        """)
        layout.addWidget(self.buoy_table)

        for name in BEACON_STR_MAP.keys():
            self._add_buoy_row()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        add_row_btn = QPushButton("Add Row")
        add_row_btn.clicked.connect(self._add_buoy_row)
        btn_layout.addWidget(add_row_btn)
        send_btn = QPushButton("Send SafePassageReport")
        send_btn.clicked.connect(self._on_send)
        btn_layout.addWidget(send_btn)
        layout.addLayout(btn_layout)

        layout.addStretch()

    def _add_buoy_row(self):
        row = self.buoy_table.rowCount()
        self.buoy_table.insertRow(row)

        lat_item = QTableWidgetItem("1.2806142")
        lng_item = QTableWidgetItem("103.8557120")
        self.buoy_table.setItem(row, 0, lat_item)
        self.buoy_table.setItem(row, 1, lng_item)

        state_combo = QComboBox()
        state_combo.addItems(list(BEACON_STR_MAP.keys()))
        state_combo.setCurrentText("BEACON_STATE_FLASHING_BLUE")
        self.buoy_table.setCellWidget(row, 2, state_combo)

    def _on_send(self):
        buoys = []
        for row in range(self.buoy_table.rowCount()):
            try:
                lat_item = self.buoy_table.item(row, 0)
                lng_item = self.buoy_table.item(row, 1)
                if not lat_item or not lng_item:
                    continue
                state_widget = self.buoy_table.cellWidget(row, 2)
                state_name = state_widget.currentText() if state_widget else "BEACON_STATE_UNKNOWN"
                buoys.append({
                    "lat": float(lat_item.text()),
                    "lng": float(lng_item.text()),
                    "state": BEACON_STR_MAP.get(state_name, rx_common_pb2.BEACON_STATE_UNKNOWN),
                })
            except ValueError:
                continue

        self.send_safe_passage.emit(
            self.vehicle_combo.currentText().strip(),
            self.entry_lat.value(),
            self.entry_lng.value(),
            self.exit_lat.value(),
            self.exit_lng.value(),
            buoys,
        )


class PipelineSurveySender(QWidget):
    """Task 2: PipelineSurveyReport — active buoy position and ordered segment states."""

    send_pipeline_survey = pyqtSignal(str, float, float, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setSpacing(4)

        layout.addWidget(QLabel("Vehicle:"), 0, 0)
        self.vehicle_combo = QComboBox()
        self.vehicle_combo.setEditable(True)
        self.vehicle_combo.addItems(["UUV1"])
        layout.addWidget(self.vehicle_combo, 0, 1)

        layout.addWidget(QLabel("Active buoy (GREEN):"), 1, 0)
        self.lat_input = QDoubleSpinBox()
        self.lat_input.setRange(-90, 90)
        self.lat_input.setDecimals(7)
        self.lat_input.setValue(1.2806142)
        layout.addWidget(self.lat_input, 1, 1)
        self.lng_input = QDoubleSpinBox()
        self.lng_input.setRange(-180, 180)
        self.lng_input.setDecimals(7)
        self.lng_input.setValue(103.8557120)
        layout.addWidget(self.lng_input, 1, 2)

        layout.addWidget(QLabel("Segments (in order from active buoy end):"), 2, 0, 1, 3)
        seg_row = QHBoxLayout()
        self.seg_combos = []
        default_segments = ["INTACT", "INTACT", "INTACT", "INTACT"]
        for i in range(4):
            combo = QComboBox()
            combo.addItems(["INTACT", "DAMAGED", "UNKNOWN"])
            if i < len(default_segments):
                combo.setCurrentText(default_segments[i])
            self.seg_combos.append(combo)
            seg_row.addWidget(QLabel(f"S{i + 1}:"))
            seg_row.addWidget(combo)
        add_seg_btn = QPushButton("+")
        add_seg_btn.clicked.connect(self._add_segment)
        seg_row.addWidget(add_seg_btn)
        layout.addLayout(seg_row, 3, 0, 1, 3)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        send_btn = QPushButton("Send PipelineSurveyReport")
        send_btn.clicked.connect(self._on_send)
        btn_layout.addWidget(send_btn)
        layout.addLayout(btn_layout, 4, 0, 1, 3)
        layout.setRowStretch(5, 1)

    def _add_segment(self):
        combo = QComboBox()
        combo.addItems(["INTACT", "DAMAGED", "UNKNOWN"])
        combo.setCurrentText("INTACT")
        self.seg_combos.append(combo)

    def _on_send(self):
        segments = [
            SEGMENT_STR_MAP.get(f"PIPELINE_SEGMENT_{c.currentText()}",
                                rx_common_pb2.PIPELINE_SEGMENT_UNKNOWN)
            for c in self.seg_combos
        ]
        self.send_pipeline_survey.emit(
            self.vehicle_combo.currentText().strip(),
            self.lat_input.value(),
            self.lng_input.value(),
            segments,
        )


class ReportsPanel(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Send Reports (OCS -> RoboCommand)", parent)
        self.setStyleSheet(STYLE)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        self.heartbeat_tab = HeartbeatSender()
        tabs.addTab(self.heartbeat_tab, "Heartbeat")

        self.safe_passage_tab = SafePassageSender()
        tabs.addTab(self.safe_passage_tab, "Task 1 Safe Passage")

        self.pipeline_tab = PipelineSurveySender()
        tabs.addTab(self.pipeline_tab, "Task 2 Pipeline Survey")

        self.task_reports_tab = TaskReportSender()
        tabs.addTab(self.task_reports_tab, "Task 3/4 Reports")

        layout.addWidget(tabs)
