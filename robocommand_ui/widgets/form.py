"""Small form controls shared by the Course, Run start and Task 4 tabs."""

from typing import Optional, Sequence, Tuple

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from robocommand_ui import theme
from robocommand_ui.commands import VEHICLE_TYPES, point_in_polygon

LatLng = Tuple[float, float]
COORD_DECIMALS = 7          # ~1 cm, the precision RoboCommand publishes


def coord_spin(limit: float) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(-limit, limit)
    spin.setDecimals(COORD_DECIMALS)
    spin.setSingleStep(0.00001)
    spin.setFont(theme.mono_font(9.5))
    spin.setMinimumWidth(130)
    return spin


def number_spin(lo: float, hi: float, value: float, decimals: int = 1,
                suffix: str = "") -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(lo, hi)
    spin.setDecimals(decimals)
    spin.setValue(value)
    spin.setSuffix(suffix)
    spin.setFont(theme.mono_font(9.5))
    return spin


def int_spin(lo: int, hi: int, value: int) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(lo, hi)
    spin.setValue(value)
    spin.setFont(theme.mono_font(9.5))
    return spin


def type_combo(default: str = "USV") -> QComboBox:
    combo = QComboBox()
    combo.addItems(list(VEHICLE_TYPES))
    combo.setCurrentText(default)
    combo.setCursor(Qt.PointingHandCursor)
    return combo


def button(text: str, object_name: str = "", tooltip: str = "") -> QPushButton:
    btn = QPushButton(text)
    if object_name:
        btn.setObjectName(object_name)
    btn.setCursor(Qt.PointingHandCursor)
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


def caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Faint")
    label.setWordWrap(True)
    return label


def heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("FormHeading")
    return label


class LatLngField(QWidget):
    """Latitude / longitude pair with a "course centre" shortcut.

    Follows the course centre until the operator edits it, and warns when the
    point is outside the course boundary.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ring: Sequence[LatLng] = ()
        self._center: Optional[LatLng] = None
        self._touched = False

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.lat = coord_spin(90.0)
        self.lng = coord_spin(180.0)
        self.lat.setToolTip("Latitude, decimal degrees")
        self.lng.setToolTip("Longitude, decimal degrees")
        row.addWidget(self.lat, 1)
        row.addWidget(self.lng, 1)
        self.center_btn = button("Centre", "Ghost", "Fill in the course centre")
        self.center_btn.clicked.connect(self._use_center)
        row.addWidget(self.center_btn)
        col.addLayout(row)
        self.hint = caption("")
        col.addWidget(self.hint)

        for spin in (self.lat, self.lng):
            spin.valueChanged.connect(self._on_edit)
        self._check()

    def value(self) -> LatLng:
        return (self.lat.value(), self.lng.value())

    def set_value(self, point: LatLng) -> None:
        for spin, v in ((self.lat, point[0]), (self.lng, point[1])):
            spin.blockSignals(True)
            spin.setValue(v)
            spin.blockSignals(False)
        self._check()

    def set_course(self, ring: Sequence[LatLng], center: Optional[LatLng]) -> None:
        self._ring = list(ring)
        self._center = center
        if center is not None and not self._touched:
            self.set_value(center)
        self._check()

    def is_inside_course(self) -> Optional[bool]:
        if len(self._ring) < 3:
            return None
        return point_in_polygon(self.value(), self._ring)

    def _use_center(self) -> None:
        if self._center is not None:
            self.set_value(self._center)

    def _on_edit(self) -> None:
        self._touched = True
        self._check()

    def _check(self) -> None:
        inside = self.is_inside_course()
        if inside is None:
            self.hint.setText("")
            self.hint.setStyleSheet(f"color: {theme.TEXT_FAINT};")
        elif inside:
            self.hint.setText("Inside the course")
            self.hint.setStyleSheet(f"color: {theme.OK};")
        else:
            self.hint.setText("Outside the course")
            self.hint.setStyleSheet(f"color: {theme.WARN};")
