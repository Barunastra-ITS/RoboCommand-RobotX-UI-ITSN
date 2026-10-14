"""Course tab: edit and publish the retained RxCourse, with saved presets.

Replaces ``rc course --course-id … --corner-lats … --corner-lngs …``. The
boundary ring is closed automatically on publish (first corner repeated at
the end), so an open ring can't make the course INVALID.

Corners can be typed in the table or pinned on the satellite map: enter a
centre point, press Go, then click the map to drop each corner. The table
and the pins stay in sync both ways.
"""

from pathlib import Path
from typing import List, Optional, Tuple

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from robocommand_ui import theme
from robocommand_ui.commands import build_course, close_ring
from robocommand_ui.course_presets import (
    CoursePreset, default_path, delete_preset, load_user_presets, merged, save_preset,
)
from robocommand_ui.course_validation import validate_course
from robocommand_ui.widgets.boundary_map import DEFAULT_ZOOM, BoundaryMap
from robocommand_ui.widgets.form import button, caption, coord_spin, int_spin
from robocommand_ui.widgets.panel import Panel, make_chip, set_chip

LatLng = Tuple[float, float]
MAX_PINGER_HZ = 200_000
EDITOR_WIDTH = 470


def ring_center(corners) -> Optional[LatLng]:
    """Mean of the distinct corners, or None without any."""
    pts = list(corners)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if not pts:
        return None
    return (sum(c[0] for c in pts) / len(pts), sum(c[1] for c in pts) / len(pts))


class CourseTab(QWidget):
    publish_requested = pyqtSignal(object)      # RxCourse
    clear_requested = pyqtSignal()
    log = pyqtSignal(str)

    def __init__(self, presets_path: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self._presets_path = presets_path or default_path()
        self._presets = {}
        self._broker_course = None

        row = QHBoxLayout(self)
        row.setContentsMargins(20, 16, 20, 16)
        row.setSpacing(16)
        left = QWidget()
        left.setFixedWidth(EDITOR_WIDTH)
        col = QVBoxLayout(left)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(16)
        col.addWidget(self._build_editor(), 1)
        col.addWidget(self._build_broker_panel(), 0)
        row.addWidget(left)
        row.addWidget(self._build_map_panel(), 1)

        self._reload_presets()
        first = next(iter(self._presets))
        self.preset_combo.setCurrentText(first)
        self._load_preset(first)

    # ---------- builders ----------
    def _build_editor(self) -> Panel:
        panel = Panel("RxCourse parameters")

        presets = QHBoxLayout()
        presets.setSpacing(6)
        self.preset_combo = QComboBox()
        self.preset_combo.setCursor(Qt.PointingHandCursor)
        self.preset_combo.setToolTip("Saved course parameters")
        self.preset_combo.activated.connect(lambda _: self._load_preset(self.preset_combo.currentText()))
        presets.addWidget(self.preset_combo, 1)
        save_btn = button("Save as preset…",
                          tooltip=f"Save the fields below under a name\n(in {self._presets_path})")
        save_btn.clicked.connect(self._save_preset)
        presets.addWidget(save_btn)
        self.delete_btn = button("Delete", "Ghost", "Delete the selected saved preset")
        self.delete_btn.clicked.connect(self._delete_preset)
        presets.addWidget(self.delete_btn)
        panel.body.addLayout(presets)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        self.course_id = QLineEdit()
        self.course_id.setFont(theme.mono_font(9.5))
        self.course_id.setPlaceholderText("e.g. ALPHA")
        form.addRow("Course ID", self.course_id)
        self.pinger = int_spin(1, MAX_PINGER_HZ, 25000)
        self.pinger.setSuffix(" Hz")
        form.addRow("Pinger frequency", self.pinger)
        panel.body.addLayout(form)

        self.corners = QTableWidget(0, 2)
        self.corners.setHorizontalHeaderLabels(["Latitude", "Longitude"])
        self.corners.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.corners.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.corners.setFont(theme.mono_font(9.5))
        self.corners.setMinimumHeight(200)
        panel.body.addWidget(self.corners, 1)

        edit_row = QHBoxLayout()
        add_btn = button("+ Corner", "Ghost", "Add a corner after the selected one")
        add_btn.clicked.connect(self._add_corner)
        remove_btn = button("− Corner", "Ghost", "Remove the selected corner")
        remove_btn.clicked.connect(self._remove_corner)
        edit_row.addWidget(add_btn)
        edit_row.addWidget(remove_btn)
        edit_row.addStretch()
        panel.body.addLayout(edit_row)
        panel.body.addWidget(caption(
            "Corners in order around the course. The first corner is repeated at the end "
            "automatically when you publish."))

        self.validity = make_chip("", theme.IDLE)
        panel.body.addWidget(self.validity, 0, Qt.AlignLeft)

        actions = QHBoxLayout()
        self.publish_btn = button("Publish course (retained)", "Primary",
                                  "Publish RxCourse on robocommand/robotx/course, retained")
        self.publish_btn.clicked.connect(self._publish)
        actions.addWidget(self.publish_btn)
        actions.addStretch()
        panel.body.addLayout(actions)

        self.course_id.textChanged.connect(self._validate)
        self.pinger.valueChanged.connect(self._validate)
        self.corners.itemChanged.connect(self._validate)
        return panel

    def _build_map_panel(self) -> Panel:
        panel = Panel("Boundary map", dot=theme.MAP_PIN)
        panel.set_meta("click to pin corners")
        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("Centre")
        label.setObjectName("FormHeading")
        row.addWidget(label)
        self.center_lat = coord_spin(90.0)
        self.center_lat.setToolTip("Centre latitude, decimal degrees")
        self.center_lng = coord_spin(180.0)
        self.center_lng.setToolTip("Centre longitude, decimal degrees")
        row.addWidget(self.center_lat, 1)
        row.addWidget(self.center_lng, 1)
        go_btn = button("Go", "Primary", "Move the map to this centre point")
        go_btn.clicked.connect(self._go_to_center)
        row.addWidget(go_btn)
        fit_btn = button("Fit corners", "Ghost", "Zoom the map to the pinned corners")
        fit_btn.clicked.connect(lambda: self.map.fit_corners())
        row.addWidget(fit_btn)
        clear_btn = button("Clear pins", "Ghost", "Remove every corner")
        clear_btn.clicked.connect(self._clear_corners)
        row.addWidget(clear_btn)
        panel.body.addLayout(row)
        for spin in (self.center_lat, self.center_lng):
            spin.lineEdit().returnPressed.connect(self._go_to_center)

        self.map = BoundaryMap()
        self.map.corners_changed.connect(self._on_map_corners)
        panel.body.addWidget(self.map, 1)
        return panel

    def _build_broker_panel(self) -> Panel:
        panel = Panel("On the broker now")
        panel.set_meta("robocommand/robotx/course · retained")
        self.broker_summary = caption("Nothing received yet. Connect to the broker first.")
        self.broker_summary.setFont(theme.mono_font(9.5))
        self.broker_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        panel.body.addWidget(self.broker_summary)
        row = QHBoxLayout()
        self.copy_btn = button("Edit this course", tooltip="Copy the retained course into the editor")
        self.copy_btn.clicked.connect(self._copy_broker_course)
        self.copy_btn.setEnabled(False)
        row.addWidget(self.copy_btn)
        clear_btn = button("Clear retained course", "Danger",
                           "Remove the retained RxCourse from the broker")
        clear_btn.clicked.connect(self._confirm_clear)
        row.addWidget(clear_btn)
        row.addStretch()
        panel.body.addLayout(row)
        panel.body.addStretch()
        return panel

    # ---------- presets ----------
    def _reload_presets(self) -> None:
        try:
            user = load_user_presets(self._presets_path)
        except ValueError as e:
            self.log.emit(f"[ERROR] {e}")
            user = []
        self._presets = merged(user)
        current = self.preset_combo.currentText()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItems(list(self._presets))
        if current in self._presets:
            self.preset_combo.setCurrentText(current)
        self.preset_combo.blockSignals(False)
        self._sync_delete()

    def _sync_delete(self) -> None:
        preset = self._presets.get(self.preset_combo.currentText())
        self.delete_btn.setEnabled(preset is not None and not preset.builtin)

    def _load_preset(self, name: str) -> None:
        preset = self._presets.get(name)
        self._sync_delete()
        if preset is not None:
            self.set_fields(preset.course_id, preset.pinger_freq_hz, preset.corners)
            self._center_on_corners()

    def _save_preset(self) -> None:
        corners, error = self.read_corners()
        if error:
            QMessageBox.warning(self, "Cannot save preset", error)
            return
        name, ok = QInputDialog.getText(self, "Save course preset", "Preset name:",
                                        text=self.course_id.text().strip())
        name = name.strip()
        if not ok or not name:
            return
        preset = CoursePreset(name, self.course_id.text().strip(), self.pinger.value(),
                              tuple(close_ring(corners)))
        try:
            save_preset(self._presets_path, preset)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Cannot save preset", str(e))
            return
        self._reload_presets()
        self.preset_combo.setCurrentText(name)
        self._sync_delete()
        self.log.emit(f"Saved course preset '{name}'")

    def _delete_preset(self) -> None:
        name = self.preset_combo.currentText()
        preset = self._presets.get(name)
        if preset is None or preset.builtin:
            return
        if QMessageBox.question(self, "Delete preset", f"Delete the preset '{name}'?") != QMessageBox.Yes:
            return
        try:
            delete_preset(self._presets_path, name)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Cannot delete preset", str(e))
            return
        self._reload_presets()
        self._load_preset(self.preset_combo.currentText())
        self.log.emit(f"Deleted course preset '{name}'")

    # ---------- fields ----------
    def set_fields(self, course_id: str, pinger_hz: int, corners) -> None:
        self.course_id.setText(course_id)
        self.pinger.setValue(pinger_hz)
        ring = list(corners)
        if len(ring) > 1 and ring[0] == ring[-1]:
            ring = ring[:-1]                # shown open; closed again on publish
        self.corners.blockSignals(True)
        self.corners.setRowCount(0)
        for lat, lng in ring:
            self._append_row(f"{lat:.7f}", f"{lng:.7f}")
        self.corners.blockSignals(False)
        self._validate()

    # ---------- map ----------
    def _go_to_center(self) -> None:
        zoom = self.map.zoom() if self.map.corners() else DEFAULT_ZOOM
        self.map.set_center(self.center_lat.value(), self.center_lng.value(), zoom)

    def _center_on_corners(self) -> None:
        corners, error = self.read_corners()
        center = ring_center(corners) if not error else None
        if center is None:
            return
        self.center_lat.setValue(center[0])
        self.center_lng.setValue(center[1])
        self.map.set_center(*center)
        self.map.fit_corners()

    def _on_map_corners(self, corners) -> None:
        """Pins moved on the map: rewrite the table from them."""
        self.corners.blockSignals(True)
        self.corners.setRowCount(0)
        for lat, lng in corners:
            self._append_row(f"{lat:.7f}", f"{lng:.7f}")
        self.corners.blockSignals(False)
        self._validate(sync_map=False)

    def _clear_corners(self) -> None:
        self.corners.setRowCount(0)
        self._validate()

    def _append_row(self, lat: str = "", lng: str = "", at: Optional[int] = None) -> None:
        row = self.corners.rowCount() if at is None else at
        self.corners.insertRow(row)
        self.corners.setItem(row, 0, QTableWidgetItem(lat))
        self.corners.setItem(row, 1, QTableWidgetItem(lng))

    def _add_corner(self) -> None:
        current = self.corners.currentRow()
        self.corners.blockSignals(True)
        self._append_row(at=None if current < 0 else current + 1)
        self.corners.blockSignals(False)
        self._validate()

    def _remove_corner(self) -> None:
        current = self.corners.currentRow()
        if current >= 0:
            self.corners.removeRow(current)
            self._validate()

    def read_corners(self) -> Tuple[List[LatLng], str]:
        """Corners from the table, or an error naming the first bad cell."""
        corners = []
        for row in range(self.corners.rowCount()):
            values = []
            for col, name in ((0, "latitude"), (1, "longitude")):
                item = self.corners.item(row, col)
                text = item.text().strip() if item else ""
                try:
                    values.append(float(text))
                except ValueError:
                    return [], f"corner {row + 1}: {name} '{text}' is not a number"
            corners.append((values[0], values[1]))
        return corners, ""

    def build(self):
        """The RxCourse to publish, plus its problems (empty when valid)."""
        corners, error = self.read_corners()
        if error:
            return None, [error]
        course = build_course(self.course_id.text().strip(), self.pinger.value(),
                              close_ring(corners))
        return course, validate_course(course)

    def _validate(self, sync_map: bool = True) -> None:
        if sync_map and hasattr(self, "map"):      # the map is built after the editor
            corners, error = self.read_corners()
            if not error:
                self.map.set_corners(corners)
        _, issues = self.build()
        if issues:
            set_chip(self.validity, f"INVALID · {issues[0]}", theme.FAULT)
        else:
            set_chip(self.validity, "VALID · ready to publish", theme.OK)
        self.publish_btn.setEnabled(not issues)

    def _publish(self) -> None:
        course, issues = self.build()
        if course is not None and not issues:
            self.publish_requested.emit(course)

    def _confirm_clear(self) -> None:
        if QMessageBox.question(
                self, "Clear retained course",
                "Remove the retained course from the broker?\n"
                "A GCS that connects afterwards will not get a course.") == QMessageBox.Yes:
            self.clear_requested.emit()

    # ---------- broker state ----------
    def show_broker_course(self, course) -> None:
        self._broker_course = course
        self.copy_btn.setEnabled(course is not None)
        if course is None:
            self.broker_summary.setText("No retained course on the broker.")
            return
        issues = validate_course(course)
        state = "VALID" if not issues else "INVALID: " + "; ".join(issues)
        self.broker_summary.setText(
            f"{course.course_id or '<empty>'} · {course.pinger_freq_hz} Hz · "
            f"{len(course.corners)} corners · {state}")
        self.broker_summary.setToolTip("\n".join(
            f"{i + 1:>2}  {c.latitude:.7f}, {c.longitude:.7f}"
            for i, c in enumerate(course.corners)))

    def _copy_broker_course(self) -> None:
        c = self._broker_course
        if c is not None:
            self.set_fields(c.course_id, c.pinger_freq_hz,
                            [(p.latitude, p.longitude) for p in c.corners])
            self._center_on_corners()
