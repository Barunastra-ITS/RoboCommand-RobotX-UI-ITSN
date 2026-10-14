"""Satellite basemap tiles (Web Mercator), shared by both maps.

Same imagery as the nala2-report OCS map (Esri World Imagery). Tiles are
fetched off the GUI thread and cached on disk in
``~/.cache/robocommand_ui/tiles``: the course networks have no Internet
(handbook §3.4.2), so open the Course tab once at home to pre-cache the
area and the map still shows it on the course. Without tiles the maps fall
back to their plain grid. ``ROBOCOMMAND_TILE_URL`` overrides the source and
``ROBOCOMMAND_MAP_TILES=0`` turns tiles off.
"""

import math
import os
import time
import urllib.request
from collections import OrderedDict
from typing import Dict, Optional, Tuple

from PyQt5.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap

TILE_SIZE = 256
MAX_ZOOM = 19
TILE_URL = os.environ.get(
    "ROBOCOMMAND_TILE_URL",
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}")
ATTRIBUTION = "Imagery © Esri, Maxar, Earthstar Geographics"
MEMORY_TILES = 512
RETRY_AFTER_FAIL_S = 60.0
FETCH_TIMEOUT_S = 8
MAX_LAT = 85.05112878

TileKey = Tuple[int, int, int]      # z, x, y


def unit_xy(lat: float, lng: float) -> Tuple[float, float]:
    """lat/lng -> Web Mercator unit square (x right, y down)."""
    lat = max(min(lat, MAX_LAT), -MAX_LAT)
    s = math.sin(math.radians(lat))
    return (lng + 180.0) / 360.0, 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)


def unit_to_latlng(x: float, y: float) -> Tuple[float, float]:
    return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y)))), x * 360.0 - 180.0


def metres_per_pixel(lat: float, zoom: float) -> float:
    return 156_543.033928 * math.cos(math.radians(lat)) / (2 ** zoom)


def cache_dir() -> str:
    base = os.environ.get("XDG_CACHE_HOME", os.path.join(os.path.expanduser("~"), ".cache"))
    return os.path.join(base, "robocommand_ui", "tiles")


class _Signals(QObject):
    ready = pyqtSignal(int, int, int, object)
    failed = pyqtSignal(int, int, int)


class _Fetch(QRunnable):
    def __init__(self, signals: _Signals, key: TileKey, path: str):
        super().__init__()
        self._signals, self._key, self._path = signals, key, path

    def run(self) -> None:
        z, x, y = self._key
        try:
            request = urllib.request.Request(TILE_URL.format(z=z, x=x, y=y),
                                             headers={"User-Agent": "robocommand-ui/1.0"})
            with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_S) as response:
                data = response.read()
            image = QImage()
            if not data or not image.loadFromData(data):
                raise ValueError("tile decode failed")
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            tmp = self._path + ".part"
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, self._path)
            self._emit(self._signals.ready, z, x, y, image)
        except Exception:       # offline / HTTP errors only cost the imagery
            self._emit(self._signals.failed, z, x, y)

    @staticmethod
    def _emit(signal, *args) -> None:
        try:
            signal.emit(*args)
        except RuntimeError:
            pass                # loader destroyed while the fetch was in flight


class TileLoader(QObject):
    """Memory + disk tile cache. ``tile()`` returns a pixmap or starts a fetch."""

    updated = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled = os.environ.get("ROBOCOMMAND_MAP_TILES", "1") != "0"
        self._dir = cache_dir()
        self._memory: "OrderedDict[TileKey, QPixmap]" = OrderedDict()
        self._failed: Dict[TileKey, float] = {}
        self._pending = set()
        self._signals = _Signals()
        self._signals.ready.connect(self._on_ready)
        self._signals.failed.connect(self._on_failed)
        self._pool = QThreadPool.globalInstance()

    def _path(self, key: TileKey) -> str:
        z, x, y = key
        return os.path.join(self._dir, str(z), str(x), f"{y}.jpg")

    def tile(self, z: int, x: int, y: int) -> Optional[QPixmap]:
        if not self.enabled or not 0 <= y < (1 << z):
            return None
        key = (z, x % (1 << z), y)
        pix = self._memory.get(key)
        if pix is not None:
            self._memory.move_to_end(key)
            return pix
        path = self._path(key)
        if os.path.exists(path):
            pix = QPixmap(path)
            if not pix.isNull():
                self._remember(key, pix)
                return pix
        if key in self._pending or time.time() - self._failed.get(key, -1e9) < RETRY_AFTER_FAIL_S:
            return None
        self._pending.add(key)
        self._pool.start(_Fetch(self._signals, key, path))
        return None

    def _remember(self, key: TileKey, pix: QPixmap) -> None:
        self._memory[key] = pix
        while len(self._memory) > MEMORY_TILES:
            self._memory.popitem(last=False)

    def _on_ready(self, z: int, x: int, y: int, image) -> None:
        self._pending.discard((z, x, y))
        self._remember((z, x, y), QPixmap.fromImage(image))
        self.updated.emit()

    def _on_failed(self, z: int, x: int, y: int) -> None:
        self._pending.discard((z, x, y))
        self._failed[(z, x, y)] = time.time()


_shared: Optional[TileLoader] = None


def shared_loader() -> TileLoader:
    global _shared
    if _shared is None:
        _shared = TileLoader()
    return _shared
