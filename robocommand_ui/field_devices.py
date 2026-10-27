"""HTTP clients for the RobotX 2026 course devices (``robotx-light-esp-2026``).

- **Light beacon** (Task 1, ``Beacon Light RBX``): ESP8266 with one LED matrix.
  ``GET /set?s=<mode>`` sets it; the state is only shown on its ``/`` page.
- **Docking bays** (Task 3, ``RBX_1``): ESP32 with two bays, each an LED
  matrix and a water flow sensor. ``GET /api/data`` returns JSON; ``/start``,
  ``/manual``, ``/force_success``, ``/setcolor``, ``/settarget`` and
  ``/setcalib`` drive it.

Both are plain HTTP on port 80 with no auth, on static ``192.168.0.x``
addresses of the devices' WiFi. The host joins that WiFi while MQTT stays on
the wired course LAN; the subnets do not overlap. Calls block, so the tabs
run them off the GUI thread (``widgets/device_runner.py``).
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

DEFAULT_BEACONS = ("192.168.0.252", "192.168.0.253")
DEFAULT_DOCK = "192.168.0.251"
TIMEOUT_S = 2.0

# (firmware mode, button text, what it marks on the course)
BEACON_MODES = (
    ("flash_blue", "Flashing blue", "entry"),
    ("solid_blue", "Solid blue", "exit"),
    ("flash_red", "Flashing red", "starboard obstacle"),
    ("flash_green", "Flashing green", "port obstacle"),
    ("off", "Off", "black obstacle"),
)
DOCK_TIERS = {"core": "Core", "adv": "Advanced", "disrupt": "Disruptive"}
DOCK_COLORS = ("red", "green", "blue")
BAYS = (1, 2)
ALL_BAYS = 0                # /manual?bay=0 stops both

_HOST = re.compile(r"^[A-Za-z0-9.\-]+(:\d{1,5})?$")
_BEACON_STATUS = re.compile(r"color:#ffeb3b;'>([^<]+)</h3>")
_DOCK_TARGET = re.compile(r"id='tVol' value='([0-9.]+)'")
# No proxy: the devices are on the local WiFi, never behind http_proxy
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class DeviceError(Exception):
    """The device did not answer, or refused the request."""


@dataclass(frozen=True)
class BayStatus:
    litres: float
    flow_lpm: float
    state: str


@dataclass(frozen=True)
class DockStatus:
    bays: Tuple[BayStatus, BayStatus]
    calibration: float


def valid_host(host: str) -> bool:
    return bool(_HOST.match(host or ""))


def _get(host: str, path: str, params: Optional[Dict[str, object]] = None,
         timeout: float = TIMEOUT_S) -> str:
    if not valid_host(host):
        raise DeviceError(f"invalid address '{host}'")
    url = f"http://{host}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with _OPENER.open(url, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise DeviceError(f"{host}{path} refused (HTTP {e.code})") from e
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise DeviceError(f"{host} unreachable ({reason})") from e


def _bay(bay: int) -> int:
    if bay not in BAYS:
        raise DeviceError(f"bay must be 1 or 2, not {bay}")
    return bay


# ---------- light beacon (Task 1) ----------
def beacon_status(host: str) -> str:
    """The beacon's state text, e.g. "FLASHING BLUE (ENTRY)"."""
    match = _BEACON_STATUS.search(_get(host, "/"))
    if match is None:
        raise DeviceError(f"{host} is not a light beacon (no status on its page)")
    return match.group(1).strip()


def set_beacon(host: str, mode: str) -> None:
    if mode not in {m for m, _, _ in BEACON_MODES}:
        raise DeviceError(f"unknown beacon mode '{mode}'")
    _get(host, "/set", {"s": mode})


# ---------- docking bays (Task 3) ----------
def dock_status(host: str) -> DockStatus:
    text = _get(host, "/api/data")
    try:
        d = json.loads(text)
        bays = (BayStatus(float(d["v1"]), float(d["f1"]), str(d["st1"])),
                BayStatus(float(d["v2"]), float(d["f2"]), str(d["st2"])))
        return DockStatus(bays, float(d["calib"]))
    except (ValueError, KeyError, TypeError) as e:
        raise DeviceError(f"{host} sent unreadable data ({e})") from e


def dock_target(host: str) -> float:
    """Target litres; only on the ``/`` page, and reset to 10 L on ESP reboot."""
    match = _DOCK_TARGET.search(_get(host, "/"))
    if match is None:
        raise DeviceError(f"{host} is not the docking bay controller")
    return float(match.group(1))


def dock_start(host: str, bay: int, tier: str, color1: str = "red", color2: str = "red") -> None:
    """Start a bay: LED red until its target litres, then the tier's pattern."""
    if tier not in DOCK_TIERS:
        raise DeviceError(f"unknown tier '{tier}'")
    if color1 not in DOCK_COLORS or color2 not in DOCK_COLORS:
        raise DeviceError("colours must be red, green or blue")
    _get(host, "/start", {"bay": _bay(bay), "tier": tier, "c1": color1, "c2": color2})


def dock_stop(host: str, bay: int = ALL_BAYS) -> None:
    """Back to manual: LED off and litres reset (``ALL_BAYS`` for both)."""
    if bay != ALL_BAYS:
        _bay(bay)
    _get(host, "/manual", {"bay": bay})


def dock_force_success(host: str, bay: int) -> None:
    try:
        _get(host, "/force_success", {"bay": _bay(bay)})
    except DeviceError as e:
        if "HTTP 400" in str(e):
            raise DeviceError(f"bay {bay} is not firefighting, nothing to force") from e
        raise


def dock_set_color(host: str, bay: int, rgb: Tuple[int, int, int]) -> None:
    r, g, b = (max(0, min(255, int(c))) for c in rgb)
    try:
        _get(host, "/setcolor", {"bay": _bay(bay), "r": r, "g": g, "b": b})
    except DeviceError as e:
        if "HTTP 400" in str(e):
            raise DeviceError(f"bay {bay} must be stopped (manual) to set a colour") from e
        raise


def dock_set_target(host: str, litres: float) -> None:
    if not 0 < litres <= 1000:
        raise DeviceError("target must be between 0 and 1000 L")
    _get(host, "/settarget", {"val": f"{litres:.2f}"})


def dock_set_calibration(host: str, constant: float) -> None:
    """Flow sensor pulses per (L/min); the ESP keeps it across reboots."""
    if not 0 < constant <= 1000:
        raise DeviceError("calibration must be between 0 and 1000")
    _get(host, "/setcalib", {"val": f"{constant:.2f}"})
