"""Replay of a finished run: the course map as it looked during the run.

Opened from the Run start tab's **Finished runs** list. Draws the run's
course, UAV geofence, Task 1 / Task 2 overlays and every vehicle's track on
the same map as the live MAP tab; the timeline scrubs or plays through the
run from RunStart to End run.
"""

import time

from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QSlider, QVBoxLayout

from robocommand_ui.proto_helper import rx_reports_pb2
from robocommand_ui.run_log import format_duration
from robocommand_ui.run_replay import RunReplay, RunSummary
from robocommand_ui.widgets.course_map import MapCanvas
from robocommand_ui.widgets.form import button, caption

TICK_MS = 100
STEPS_PER_S = 10            # slider resolution: 0.1 s
SPEEDS = (1, 2, 5, 10, 20, 50)
DEFAULT_SPEED = 5


def clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _heartbeat(v) -> rx_reports_pb2.Heartbeat:
    """What MapCanvas draws a vehicle from."""
    hb = rx_reports_pb2.Heartbeat(vehicle_type=v.vehicle_type, heading_deg=v.heading, state=v.state)
    hb.position.latitude, hb.position.longitude = v.lat, v.lng
    return hb


class RunReplayDialog(QDialog):
    def __init__(self, summary: RunSummary, replay: RunReplay, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Run replay — {replay.team_id} run {replay.run_id}")
        self.resize(1100, 780)
        self.setObjectName("Root")              # themed background, like the main window
        self._summary = summary
        self._replay = replay
        self._t = 0.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        heading = QLabel(f"{replay.team_id} · run {replay.run_id}")
        heading.setObjectName("FormHeading")
        layout.addWidget(heading)
        started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(replay.started_at))
        layout.addWidget(caption(
            f"Started {started}  ·  {format_duration(replay.duration)}  ·  "
            f"course {replay.course_id or '—'}  ·  vehicles "
            f"{', '.join(replay.vehicle_ids) or 'none reported'}  ·  {summary.reason}"))

        self.canvas = MapCanvas(self)
        self.canvas.set_course_points(replay.course, replay.course_id)
        self.canvas.set_geofence(replay.geofence)
        layout.addWidget(self.canvas, 1)

        layout.addLayout(self._build_controls())
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._seek(replay.duration)         # open on the whole run drawn

    def _build_controls(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        self.play_btn = button("Play", "Primary", "Play the run from the timeline position")
        self.play_btn.setMinimumWidth(84)
        self.play_btn.clicked.connect(self._toggle_play)
        row.addWidget(self.play_btn)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, max(1, int(self._replay.duration * STEPS_PER_S)))
        self.slider.valueChanged.connect(lambda v: self._seek(v / STEPS_PER_S, from_slider=True))
        row.addWidget(self.slider, 1)

        self.time_label = QLabel("")
        self.time_label.setObjectName("Mono")
        self.time_label.setMinimumWidth(110)
        row.addWidget(self.time_label)

        self.speed = QComboBox()
        for s in SPEEDS:
            self.speed.addItem(f"{s}×", s)
        self.speed.setCurrentIndex(SPEEDS.index(DEFAULT_SPEED))
        self.speed.setToolTip("Playback speed")
        row.addWidget(self.speed)

        log_btn = button("Open log", "Ghost", str(self._summary.log_path))
        log_btn.setEnabled(self._summary.log_path.exists())
        log_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._summary.log_path))))
        row.addWidget(log_btn)
        return row

    # ---------- playback ----------
    def _toggle_play(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self.play_btn.setText("Play")
            return
        if self._t >= self._replay.duration:
            self._seek(0.0)                 # replay from RunStart
        self._timer.start(TICK_MS)
        self.play_btn.setText("Pause")

    def _advance(self) -> None:
        t = self._t + TICK_MS / 1000 * self.speed.currentData()
        if t >= self._replay.duration:
            t = self._replay.duration
            self._timer.stop()
            self.play_btn.setText("Play")
        self._seek(t)

    def _seek(self, t: float, from_slider: bool = False) -> None:
        self._t = max(0.0, min(t, self._replay.duration))
        if not from_slider:
            self.slider.blockSignals(True)
            self.slider.setValue(int(self._t * STEPS_PER_S))
            self.slider.blockSignals(False)
        self.time_label.setText(f"{clock(self._t)} / {clock(self._replay.duration)}")
        self._draw()

    def _draw(self) -> None:
        frame = self._replay.frame(self._t)
        c = self.canvas
        c.set_vehicles({f"{self._replay.team_id}/{vid}": (_heartbeat(v), v.trail, v.stale)
                        for vid, v in frame.vehicles.items()})
        c.clear_task_data()
        if frame.safe_passage:
            c.set_safe_passage(*frame.safe_passage)
        if frame.pipeline:
            c.set_pipeline(*frame.pipeline)
        c.update()

    def closeEvent(self, event) -> None:
        self._timer.stop()
        super().closeEvent(event)
