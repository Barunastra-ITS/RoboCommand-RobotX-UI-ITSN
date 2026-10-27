"""Address field + ONLINE / OFFLINE chip for a course device (Task 1 and 3 tabs).

The address is remembered in QSettings under ``key``.
"""

from typing import Optional

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QWidget

from robocommand_ui import theme
from robocommand_ui.field_devices import valid_host
from robocommand_ui.widgets.form import caption
from robocommand_ui.widgets.panel import make_chip, set_chip


def readout_style(color: str, px: int = 20) -> str:
    """Large mono readout; a style sheet, since the app sheet overrides setFont."""
    return (f"font-family: '{theme.mono_family()}'; font-size: {px}px; font-weight: 600;"
            f" color: {theme.resolve(color)};")


class DeviceHost(QWidget):
    changed = pyqtSignal(str)

    def __init__(self, label: str, default: str, settings=None, key: str = "", parent=None):
        super().__init__(parent)
        self._settings, self._key = settings, key
        self._online: Optional[bool] = None         # None until the first answer
        saved = str(settings.value(key, default)) if settings is not None and key else default

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        name = QLabel(label)
        name.setObjectName("FormHeading")
        row.addWidget(name)
        self.edit = QLineEdit(saved)
        self.edit.setFont(theme.mono_font(9.5))
        self.edit.setMaximumWidth(170)
        self.edit.setToolTip("Device address on its WiFi (static, from the firmware)")
        self.edit.editingFinished.connect(self._on_edit)
        row.addWidget(self.edit)
        self.chip = make_chip("NOT CHECKED", theme.IDLE)
        row.addWidget(self.chip)
        self.detail = caption("")
        row.addWidget(self.detail, 1)

    def host(self) -> str:
        return self.edit.text().strip()

    @property
    def online(self) -> bool:
        return bool(self._online)

    def set_online(self, online: bool, detail: str = "") -> Optional[str]:
        """Show the link state; returns a log line when it changed."""
        changed = online != self._online
        self._online = online
        set_chip(self.chip, "ONLINE" if online else "OFFLINE", theme.OK if online else theme.FAULT)
        self.detail.setText("" if online else detail)
        if not changed:
            return None
        return f"{self.host()} online" if online else f"{self.host()} offline: {detail}"

    def _on_edit(self) -> None:
        host = self.host()
        if not valid_host(host):
            self.detail.setText(f"'{host}' is not an address")
            return
        if self._settings is not None and self._key:
            self._settings.setValue(self._key, host)
        self._online = None
        set_chip(self.chip, "CHECKING", theme.IDLE)
        self.changed.emit(host)
