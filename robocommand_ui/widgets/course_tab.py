"""Course tab: edit and publish the retained RxCourse, with saved presets.

Replaces ``rc course --course-id … --corner-lats … --corner-lngs …``. The
boundary ring is closed automatically on publish (first corner repeated at
the end), so an open ring can't make the course INVALID.

Three columns: **Presets** (pick one to load it; Add saves the fields as a
new preset, Update overwrites the selected one), the **RxCourse** editor
with the broker's retained course under it, and the **Boundary map**.
Corners can be typed in the table or pinned on the map; the table and the
pins stay in sync both ways, and the Centre fields follow the map as it is
panned (or type a centre and press Go). The Course ID follows the course
this host serves (from its address), so it is filled in already.

**Boundary / UAV transit** picks which ring the table and the map pins edit;
the other is drawn dashed on the map. The UAV transit area (optional) is
where a declared UAV geofence may lie beyond the boundary: takeoff, landing
and the way to and from the course. Without one, the geofence must fit the
boundary.
"""

import time
from pathlib import Path
from typing import List, Optional, Tuple

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QButtonGroup, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from robocommand_ui import theme
from robocommand_ui.commands import build_course, close_ring
from robocommand_ui.course_presets import (
    CoursePreset, default_path, delete_preset, load_user_presets, merged, save_preset,
)
from robocommand_ui.course_validation import validate_course
from robocommand_ui.courses import course_id_of
from robocommand_ui.widgets.boundary_map import DEFAULT_ZOOM, BoundaryMap
from robocommand_ui.widgets.form import button, caption, coord_spin, int_spin, unit_label
from robocommand_ui.widgets.panel import Panel, make_chip, set_chip

LatLng = Tuple[float, float]
MAX_PINGER_HZ = 200_000
PRESETS_WIDTH = 250
EDITOR_WIDTH = 440
SAME_CORNER = 5e-10         # degrees: what the table's 9 decimals can tell apart
BOUNDARY, TRANSIT = "boundary", "transit"
RING_NAMES = {BOUNDARY: "corner", TRANSIT: "transit point"}


def ring_center(corners) -> Optional[LatLng]:
    """Mean of the distinct corners, or None without any."""
    pts = open_ring(corners)
    if not pts:
        return None
    return (sum(c[0] for c in pts) / len(pts), sum(c[1] for c in pts) / len(pts))


def open_ring(corners) -> List[LatLng]:
    ring = [tuple(c) for c in corners]
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    return ring


def same_ring(a, b) -> bool:
    a, b = open_ring(a), open_ring(b)
    return len(a) == len(b) and all(
        abs(p[0] - q[0]) < SAME_CORNER and abs(p[1] - q[1]) < SAME_CORNER for p, q in zip(a, b))


def sent_at_text(course) -> str:
    """Local time of RxCourse.sent_at, or a note when the publisher left it unset."""
    if not course.HasField("sent_at") or course.sent_at.seconds == 0:
        return "(time unknown: no sent_at)"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(course.sent_at.seconds))


class CourseTab(QWidget):
    publish_requested = pyqtSignal(object)      # RxCourse
    clear_requested = pyqtSignal()
    log = pyqtSignal(str)

    def __init__(self, presets_path: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self._presets_path = presets_path or default_path()
        self._presets = {}
        self._active: Optional[str] = None      # preset loaded into the editor
        self._broker_course = None
        self._rc_course = None                  # courses.Course this host serves
        self._id_typed = False                  # operator typed their own Course ID
        self._editing = BOUNDARY                # ring the table and map pins edit

        row = QHBoxLayout(self)
        row.setContentsMargins(20, 16, 20, 16)
        row.setSpacing(16)
        presets = self._build_presets_panel()
        presets.setFixedWidth(PRESETS_WIDTH)
        row.addWidget(presets)
        editor = QWidget()
        editor.setFixedWidth(EDITOR_WIDTH)
        col = QVBoxLayout(editor)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(16)
        col.addWidget(self._build_editor(), 1)
        col.addWidget(self._build_broker_panel(), 0)
        row.addWidget(editor)
        row.addWidget(self._build_map_panel(), 1)

        self._reload_presets()
        if self.preset_list.count():
            self.preset_list.setCurrentRow(0)       # loads it
        self.set_rc_course(None)

    # ---------- builders ----------
    def _build_presets_panel(self) -> Panel:
        panel = Panel("Presets")
        self.preset_list = QListWidget()
        self.preset_list.setCursor(Qt.PointingHandCursor)
        self.preset_list.currentItemChanged.connect(self._on_preset_selected)
        panel.body.addWidget(self.preset_list, 1)

        self.preset_state = caption("")
        panel.body.addWidget(self.preset_state)

        self.add_preset_btn = button("+ Add preset", "Primary",
                                     f"Save the fields as a new preset (asks for a name)\n"
                                     f"in {self._presets_path}")
        self.add_preset_btn.clicked.connect(self._add_preset)
        panel.body.addWidget(self.add_preset_btn)
        self.update_preset_btn = button("Update preset", tooltip="Overwrite the selected "
                                        "preset with the fields (keeps its name)")
        self.update_preset_btn.clicked.connect(self._update_preset)
        panel.body.addWidget(self.update_preset_btn)
        self.delete_btn = button("Delete preset", "Danger", "Delete the selected saved preset")
        self.delete_btn.clicked.connect(self._delete_preset)
        panel.body.addWidget(self.delete_btn)
        return panel

    def _build_editor(self) -> Panel:
        panel = Panel("RxCourse parameters")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        id_col = QVBoxLayout()
        id_col.setSpacing(4)
        id_row = QHBoxLayout()
        id_row.setSpacing(6)
        self.course_id = QLineEdit()
        self.course_id.setFont(theme.mono_font(10))
        self.course_id.setPlaceholderText("e.g. ALPHA")
        id_row.addWidget(self.course_id, 1)
        self.rc_course_btn = button("This host", "Ghost", "Fill in the course this host serves")
        self.rc_course_btn.clicked.connect(self._use_rc_course)
        id_row.addWidget(self.rc_course_btn)
        id_col.addLayout(id_row)
        self.rc_course_note = caption("")
        id_col.addWidget(self.rc_course_note)
        form.addRow("Course ID", id_col)

        pinger_row = QHBoxLayout()
        pinger_row.setSpacing(8)
        self.pinger = int_spin(1, MAX_PINGER_HZ, 25000)
        self.pinger.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.pinger.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.pinger.setFont(theme.mono_font(10))
        self.pinger.setToolTip(f"Pinger frequency in hertz (1 – {MAX_PINGER_HZ})")
        pinger_row.addWidget(self.pinger, 1)
        pinger_row.addWidget(unit_label("Hz"), 0, Qt.AlignVCenter)
        form.addRow("Pinger frequency", pinger_row)
        panel.body.addLayout(form)

        ring_row = QHBoxLayout()
        ring_row.setSpacing(6)
        self.ring_buttons = QButtonGroup(self)
        self.ring_btns = {}
        for key, text, tip in (
                (BOUNDARY, "Boundary", "Edit the course boundary (RxCourse.corners)"),
                (TRANSIT, "UAV transit", "Edit the UAV transit area (RxCourse.uav_transit_area):"
                 "\nwhere a UAV geofence may lie beyond the boundary. Optional")):
            btn = button(text, "Ghost", tip)
            btn.setCheckable(True)
            self.ring_buttons.addButton(btn)
            self.ring_btns[key] = btn
            btn.clicked.connect(lambda _=False, k=key: self.set_editing(k))
            ring_row.addWidget(btn)
        self.ring_btns[BOUNDARY].setChecked(True)
        ring_row.addStretch()
        self.ring_note = caption("")
        ring_row.addWidget(self.ring_note)
        panel.body.addLayout(ring_row)

        self.corners = self._ring_table()
        self.transit = self._ring_table()
        self.transit.setVisible(False)
        panel.body.addWidget(self.corners, 1)
        panel.body.addWidget(self.transit, 1)

        edit_row = QHBoxLayout()
        self.add_point_btn = button("+ Corner", "Ghost", "Add a point after the selected one")
        self.add_point_btn.clicked.connect(self._add_corner)
        self.remove_point_btn = button("− Corner", "Ghost", "Remove the selected point")
        self.remove_point_btn.clicked.connect(self._remove_corner)
        edit_row.addWidget(self.add_point_btn)
        edit_row.addWidget(self.remove_point_btn)
        edit_row.addStretch()
        panel.body.addLayout(edit_row)

        self.validity = make_chip("", theme.IDLE)
        panel.body.addWidget(self.validity, 0, Qt.AlignLeft)

        self.publish_btn = button("Publish course (retained)", "Primary",
                                  "Publish RxCourse on robocommand/robotx/course, retained")
        self.publish_btn.clicked.connect(self._publish)
        panel.body.addWidget(self.publish_btn)
        self.last_published = caption("")
        panel.body.addWidget(self.last_published)

        self.course_id.textChanged.connect(self._on_fields_edited)
        self.course_id.textEdited.connect(lambda _: setattr(self, "_id_typed", True))
        self.pinger.valueChanged.connect(self._on_fields_edited)
        self.corners.itemChanged.connect(self._on_fields_edited)
        self.transit.itemChanged.connect(self._on_fields_edited)
        return panel

    @staticmethod
    def _ring_table() -> QTableWidget:
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Latitude", "Longitude"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setFont(theme.mono_font(10))
        table.setMinimumHeight(180)
        return table

    def _build_map_panel(self) -> Panel:
        panel = Panel("Boundary map", dot=theme.MAP_PIN)
        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("Centre")
        label.setObjectName("FormHeading")
        row.addWidget(label)
        self.center_lat = coord_spin(90.0)
        self.center_lat.setToolTip("Centre latitude, decimal degrees (follows the map)")
        self.center_lng = coord_spin(180.0)
        self.center_lng.setToolTip("Centre longitude, decimal degrees (follows the map)")
        row.addWidget(self.center_lat, 1)
        row.addWidget(self.center_lng, 1)
        go_btn = button("Go", "Primary", "Move the map to this centre point")
        go_btn.clicked.connect(self._go_to_center)
        row.addWidget(go_btn)
        fit_btn = button("Fit corners", "Ghost", "Zoom the map to the boundary and transit area")
        fit_btn.clicked.connect(lambda: self.map.fit_corners())
        row.addWidget(fit_btn)
        clear_btn = button("Clear pins", "Ghost", "Remove every point of the ring being edited")
        clear_btn.clicked.connect(self._clear_corners)
        row.addWidget(clear_btn)
        panel.body.addLayout(row)
        for spin in (self.center_lat, self.center_lng):
            spin.lineEdit().returnPressed.connect(self._go_to_center)

        self.map = BoundaryMap()
        self.map.corners_changed.connect(self._on_map_corners)
        self.map.view_changed.connect(self._on_map_moved)
        panel.body.addWidget(self.map, 1)
        return panel

    def _build_broker_panel(self) -> Panel:
        panel = Panel("On the broker now")
        self.broker_summary = caption("—")
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
        return panel

    # ---------- course of this host ----------
    def set_rc_course(self, course) -> None:
        """The course this RoboCommand host serves (courses.Course, or None).

        Fills the Course ID unless the operator typed their own.
        """
        follows = not self._id_typed or not self.course_id.text().strip()
        self._rc_course = course
        self.rc_course_btn.setEnabled(course is not None)
        if course is None:
            self.rc_course_note.setText("")
            return
        where = f" · {course.host}" if course.host else ""
        self.rc_course_note.setText(f"{course.name}{where}")
        if follows:
            self._use_rc_course()

    def rc_course_id(self) -> Optional[str]:
        return course_id_of(self._rc_course) if self._rc_course is not None else None

    def _use_rc_course(self) -> None:
        course_id = self.rc_course_id()
        if course_id:
            self._id_typed = False
            self.course_id.setText(course_id)

    # ---------- presets ----------
    def selected_preset(self) -> Optional[str]:
        item = self.preset_list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def select_preset(self, name: str) -> None:
        for i in range(self.preset_list.count()):
            if self.preset_list.item(i).data(Qt.UserRole) == name:
                self.preset_list.setCurrentRow(i)
                return

    def _reload_presets(self) -> None:
        try:
            user = load_user_presets(self._presets_path)
        except ValueError as e:
            self.log.emit(f"[ERROR] {e}")
            user = []
        self._presets = merged(user)
        current = self.selected_preset()
        self.preset_list.blockSignals(True)
        self.preset_list.clear()
        for name, preset in self._presets.items():
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, name)
            item.setToolTip(f"{preset.course_id} · {preset.pinger_freq_hz} Hz · "
                            f"{len(open_ring(preset.corners))} corners"
                            + (f" · UAV transit {len(open_ring(preset.transit))} points"
                               if preset.transit else "")
                            + (" · built-in" if preset.builtin else ""))
            self.preset_list.addItem(item)
            if name == current:
                self.preset_list.setCurrentItem(item)
        self.preset_list.blockSignals(False)
        self._sync_preset_buttons()

    def _on_preset_selected(self, item, _previous=None) -> None:
        if item is not None:
            self._load_preset(item.data(Qt.UserRole))

    def _load_preset(self, name: str) -> None:
        preset = self._presets.get(name)
        if preset is None:
            return
        self._active = name
        self.set_fields(self.rc_course_id() or preset.course_id, preset.pinger_freq_hz,
                        preset.corners, preset.transit)
        self._center_on_corners()
        self._sync_preset_buttons()

    def _preset_modified(self) -> bool:
        """Do the fields differ from the preset they were loaded from?"""
        preset = self._presets.get(self._active or "")
        if preset is None:
            return False
        corners, error = self.read_corners()
        transit, transit_error = self.read_transit()
        course_id = self.course_id.text().strip()
        return bool(error or transit_error) or not (
            course_id in (preset.course_id, self.rc_course_id())    # auto-filled ID isn't an edit
            and self.pinger.value() == preset.pinger_freq_hz
            and same_ring(corners, preset.corners)
            and same_ring(transit, preset.transit))

    def _sync_preset_buttons(self) -> None:
        preset = self._presets.get(self._active or "")
        modified = self._preset_modified()
        self.update_preset_btn.setEnabled(preset is not None and modified)
        self.delete_btn.setEnabled(preset is not None and not preset.builtin)
        self.preset_state.setText("Unsaved changes" if modified else "")
        self.preset_state.setVisible(modified)

    def _preset_from_fields(self, name: str) -> Optional[CoursePreset]:
        corners, error = self.read_corners()
        transit, transit_error = self.read_transit()
        if error or transit_error:
            QMessageBox.warning(self, "Cannot save preset", error or transit_error)
            return None
        return CoursePreset(name, self.course_id.text().strip(), self.pinger.value(),
                            tuple(close_ring(corners)), tuple(close_ring(transit)))

    def _write_preset(self, preset: CoursePreset, verb: str) -> None:
        try:
            save_preset(self._presets_path, preset)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Cannot save preset", str(e))
            return
        self._active = preset.name
        self._reload_presets()
        self.preset_list.blockSignals(True)        # fields are the preset already
        self.select_preset(preset.name)
        self.preset_list.blockSignals(False)
        self._sync_preset_buttons()
        self.log.emit(f"{verb} course preset '{preset.name}'")

    def _add_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "Add course preset", "Name of the new preset:")
        name = name.strip()
        if not ok or not name:
            return
        if name in self._presets and QMessageBox.question(
                self, "Replace preset?", f"A preset named '{name}' exists. Replace it?") \
                != QMessageBox.Yes:
            return
        preset = self._preset_from_fields(name)
        if preset is not None:
            self._write_preset(preset, "Saved")

    def _update_preset(self) -> None:
        name = self._active
        if name not in self._presets:
            return
        preset = self._preset_from_fields(name)
        if preset is not None:
            self._write_preset(preset, "Updated")

    def _delete_preset(self) -> None:
        name = self._active
        preset = self._presets.get(name or "")
        if preset is None or preset.builtin:
            return
        if QMessageBox.question(self, "Delete preset", f"Delete the preset '{name}'?") != QMessageBox.Yes:
            return
        try:
            delete_preset(self._presets_path, name)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Cannot delete preset", str(e))
            return
        self._active = None
        self._reload_presets()
        if name in self._presets:           # the built-in it had replaced is back
            self.select_preset(name)
            self._load_preset(name)
        self._sync_preset_buttons()
        self.log.emit(f"Deleted course preset '{name}'")

    # ---------- fields ----------
    def set_fields(self, course_id: str, pinger_hz: int, corners, transit=()) -> None:
        self.course_id.blockSignals(True)
        self.course_id.setText(course_id)
        self.course_id.blockSignals(False)
        self.pinger.blockSignals(True)
        self.pinger.setValue(pinger_hz)
        self.pinger.blockSignals(False)
        self._fill_table(self.corners, open_ring(corners))     # shown open; closed on publish
        self._fill_table(self.transit, open_ring(transit))
        self._on_fields_edited()

    def _fill_table(self, table: QTableWidget, ring) -> None:
        table.blockSignals(True)
        table.setRowCount(0)
        for lat, lng in ring:
            self._append_row(f"{lat:.9f}", f"{lng:.9f}", table=table)
        table.blockSignals(False)

    # ---------- ring being edited ----------
    def editing(self) -> str:
        return self._editing

    def set_editing(self, ring: str) -> None:
        """Edit the boundary or the UAV transit area in the table and on the map."""
        self._editing = ring
        self.ring_btns[ring].setChecked(True)
        self.corners.setVisible(ring == BOUNDARY)
        self.transit.setVisible(ring == TRANSIT)
        self.add_point_btn.setText("+ Corner" if ring == BOUNDARY else "+ Point")
        self.remove_point_btn.setText("− Corner" if ring == BOUNDARY else "− Point")
        self._validate()

    def _active_table(self) -> QTableWidget:
        return self.corners if self._editing == BOUNDARY else self.transit

    def _sync_ring_note(self) -> None:
        transit, error = self.read_transit()
        if error:
            self.ring_note.setText("UAV transit: fix the table")
        elif transit:
            self.ring_note.setText(f"UAV transit: {len(transit)} points")
        else:
            self.ring_note.setText("No UAV transit: geofence must fit the boundary")

    def _on_fields_edited(self, *_args) -> None:
        self._validate()
        self._sync_preset_buttons()

    # ---------- map ----------
    def _go_to_center(self) -> None:
        zoom = self.map.zoom() if self.map.corners() or self.map.backdrop() else DEFAULT_ZOOM
        self.map.set_center(self.center_lat.value(), self.center_lng.value(), zoom)

    def _on_map_moved(self, lat: float, lng: float) -> None:
        """The map was panned or zoomed: the Centre fields follow it."""
        for spin, value in ((self.center_lat, lat), (self.center_lng, lng)):
            if spin.hasFocus():
                continue                    # don't overwrite what the operator is typing
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)

    def _center_on_corners(self) -> None:
        corners, error = self.read_corners()
        if not error and not corners:
            corners, error = self.read_transit()
        center = ring_center(corners) if not error else None
        if center is None:
            return
        self.map.set_center(*center)
        self.map.fit_corners()              # the Centre fields follow via view_changed

    def _on_map_corners(self, points) -> None:
        """Pins moved on the map: rewrite the table of the ring being edited."""
        self._fill_table(self._active_table(), points)
        self._validate(sync_map=False)
        self._sync_preset_buttons()

    def _clear_corners(self) -> None:
        self._active_table().setRowCount(0)
        self._on_fields_edited()

    def _append_row(self, lat: str = "", lng: str = "", at: Optional[int] = None,
                    table: Optional[QTableWidget] = None) -> None:
        table = table or self._active_table()
        row = table.rowCount() if at is None else at
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(lat))
        table.setItem(row, 1, QTableWidgetItem(lng))

    def _add_corner(self) -> None:
        table = self._active_table()
        current = table.currentRow()
        table.blockSignals(True)
        self._append_row(at=None if current < 0 else current + 1, table=table)
        table.blockSignals(False)
        self._on_fields_edited()

    def _remove_corner(self) -> None:
        table = self._active_table()
        current = table.currentRow()
        if current >= 0:
            table.removeRow(current)
            self._on_fields_edited()

    def read_corners(self) -> Tuple[List[LatLng], str]:
        """Corners from the table, or an error naming the first bad cell."""
        return self._read_ring(self.corners, RING_NAMES[BOUNDARY])

    def read_transit(self) -> Tuple[List[LatLng], str]:
        """UAV transit area from its table (empty: none), or an error."""
        return self._read_ring(self.transit, RING_NAMES[TRANSIT])

    @staticmethod
    def _read_ring(table: QTableWidget, what: str) -> Tuple[List[LatLng], str]:
        points = []
        for row in range(table.rowCount()):
            values = []
            for col, name in ((0, "latitude"), (1, "longitude")):
                item = table.item(row, col)
                text = item.text().strip() if item else ""
                try:
                    values.append(float(text))
                except ValueError:
                    return [], f"{what} {row + 1}: {name} '{text}' is not a number"
            points.append((values[0], values[1]))
        return points, ""

    def build(self):
        """The RxCourse to publish, plus its problems (empty when valid)."""
        corners, error = self.read_corners()
        transit, transit_error = self.read_transit()
        if error or transit_error:
            return None, [error or transit_error]
        course = build_course(self.course_id.text().strip(), self.pinger.value(),
                              close_ring(corners), close_ring(transit))
        return course, validate_course(course)

    def _validate(self, sync_map: bool = True) -> None:
        if sync_map and hasattr(self, "map"):      # the map is built after the editor
            rings = {}
            for key, (points, error) in ((BOUNDARY, self.read_corners()),
                                         (TRANSIT, self.read_transit())):
                rings[key] = [] if error else points
            other = TRANSIT if self._editing == BOUNDARY else BOUNDARY
            self.map.set_corners(rings[self._editing])
            self.map.set_backdrop(close_ring(rings[other]))
        self._sync_ring_note()
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

    def mark_published(self, course) -> None:
        """This console's publish went out: show when, from the course's own sent_at."""
        self.last_published.setText(
            f"Last published {sent_at_text(course)} · {course.course_id or '<empty>'}")

    # ---------- broker state ----------
    def show_broker_course(self, course) -> None:
        self._broker_course = course
        self.copy_btn.setEnabled(course is not None)
        if course is None:
            self.broker_summary.setText("None")
            return
        issues = validate_course(course)
        state = "VALID" if not issues else "INVALID: " + "; ".join(issues)
        transit = (f"UAV transit {len(course.uav_transit_area)} points"
                   if course.uav_transit_area else "no UAV transit")
        self.broker_summary.setText(
            f"{course.course_id or '<empty>'} · {course.pinger_freq_hz} Hz · "
            f"{len(course.corners)} corners · {transit} · {state}\n"
            f"published {sent_at_text(course)}")
        self.broker_summary.setToolTip("\n".join(
            f"{i + 1:>2}  {c.latitude:.9f}, {c.longitude:.9f}"
            for i, c in enumerate(course.corners)))

    def _copy_broker_course(self) -> None:
        c = self._broker_course
        if c is not None:
            self._active = None             # not a preset any more
            self.preset_list.blockSignals(True)
            self.preset_list.clearSelection()
            self.preset_list.setCurrentItem(None)
            self.preset_list.blockSignals(False)
            self.set_fields(c.course_id, c.pinger_freq_hz,
                            [(p.latitude, p.longitude) for p in c.corners],
                            [(p.latitude, p.longitude) for p in c.uav_transit_area])
            self._center_on_corners()
