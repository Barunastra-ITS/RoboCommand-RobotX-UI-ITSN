"""Satellite map for drawing the course boundary by pinning corners.

Click empty map to add a corner (on an edge it is inserted there), drag a
pin to move it, right-click a pin to delete it. Wheel zooms about the
cursor, drag on empty map pans. Every change emits ``corners_changed`` with
the open ring (the Course tab closes it on publish).
"""

import math
from typing import List, Optional, Tuple

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QPainter, QPainterPath, QPen, QPolygonF
from PyQt5.QtWidgets import QWidget

from robocommand_ui import theme
from robocommand_ui.widgets.tiles import (
    ATTRIBUTION, MAX_ZOOM, TILE_SIZE, metres_per_pixel, shared_loader, unit_to_latlng, unit_xy,
)

LatLng = Tuple[float, float]
DEFAULT_ZOOM = 17.0
MIN_ZOOM = 3.0
PIN_HIT_PX = 10
EDGE_HIT_PX = 7
CLICK_SLOP_PX = 4
SCALE_STEPS_M = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000)


class BoundaryMap(QWidget):
    corners_changed = pyqtSignal(list)          # [(lat, lng), ...] open ring

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 360)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self._tiles = shared_loader()
        self._tiles.updated.connect(self.update)
        self._center = unit_xy(0.0, 0.0)        # unit coords at widget centre
        self._zoom = DEFAULT_ZOOM
        self._corners: List[LatLng] = []
        self._press: Optional[QPointF] = None
        self._dragging_pin: Optional[int] = None
        self._panning = False
        self._hover_pin: Optional[int] = None
        self._has_center = False

    # ---------- view ----------
    def set_center(self, lat: float, lng: float, zoom: Optional[float] = None) -> None:
        self._center = unit_xy(lat, lng)
        self._has_center = True
        if zoom is not None:
            self._zoom = zoom
        self.update()

    def center(self) -> LatLng:
        return unit_to_latlng(*self._center)

    def zoom(self) -> float:
        return self._zoom

    def fit_corners(self) -> None:
        if not self._corners:
            return
        us = [unit_xy(*c) for c in self._corners]
        xs, ys = [u[0] for u in us], [u[1] for u in us]
        self._center = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-9)
        fit_px = 0.75 * min(self.width(), self.height())
        self._zoom = max(MIN_ZOOM, min(math.log2(fit_px / (span * TILE_SIZE)), MAX_ZOOM + 1))
        self._has_center = True
        self.update()

    def _world(self) -> float:
        return TILE_SIZE * 2 ** self._zoom

    def to_px(self, lat: float, lng: float) -> QPointF:
        ux, uy = unit_xy(lat, lng)
        world = self._world()
        return QPointF(self.width() / 2 + (ux - self._center[0]) * world,
                       self.height() / 2 + (uy - self._center[1]) * world)

    def to_latlng(self, p: QPointF) -> LatLng:
        world = self._world()
        return unit_to_latlng(self._center[0] + (p.x() - self.width() / 2) / world,
                              self._center[1] + (p.y() - self.height() / 2) / world)

    # ---------- corners ----------
    def set_corners(self, corners) -> None:
        self._corners = [tuple(c) for c in corners]
        self.update()

    def corners(self) -> List[LatLng]:
        return list(self._corners)

    def _emit(self) -> None:
        self.corners_changed.emit(list(self._corners))

    def _pin_at(self, p: QPointF) -> Optional[int]:
        for i, c in enumerate(self._corners):
            q = self.to_px(*c)
            if math.hypot(q.x() - p.x(), q.y() - p.y()) <= PIN_HIT_PX:
                return i
        return None

    def _edge_at(self, p: QPointF) -> Optional[int]:
        """Index to insert at when ``p`` is on an edge of the closed ring."""
        n = len(self._corners)
        if n < 2:
            return None
        for i in range(n):
            a, b = self.to_px(*self._corners[i]), self.to_px(*self._corners[(i + 1) % n])
            if _segment_distance(p, a, b) <= EDGE_HIT_PX:
                return i + 1
        return None

    # ---------- mouse ----------
    def mousePressEvent(self, e):
        p = QPointF(e.pos())
        pin = self._pin_at(p)
        if e.button() == Qt.RightButton and pin is not None:
            del self._corners[pin]
            self._hover_pin = None
            self._emit()
            self.update()
            return
        if e.button() != Qt.LeftButton:
            return
        self._press = p
        self._dragging_pin = pin
        self._panning = False

    def mouseMoveEvent(self, e):
        p = QPointF(e.pos())
        if self._press is None:
            hover = self._pin_at(p)
            if hover != self._hover_pin:
                self._hover_pin = hover
                self.setCursor(Qt.SizeAllCursor if hover is not None else Qt.CrossCursor)
                self.update()
            return
        if self._dragging_pin is not None:
            self._corners[self._dragging_pin] = self.to_latlng(p)
            self.update()
            return
        moved = p - self._press
        if self._panning or math.hypot(moved.x(), moved.y()) > CLICK_SLOP_PX:
            self._panning = True
            self.setCursor(Qt.ClosedHandCursor)
            world = self._world()
            self._center = (self._center[0] - moved.x() / world, self._center[1] - moved.y() / world)
            self._press = p
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self._press is None:
            return
        p = QPointF(e.pos())
        if self._dragging_pin is not None:
            self._emit()
        elif not self._panning:
            at = self._edge_at(p)
            point = self.to_latlng(p)
            if at is None:
                self._corners.append(point)
            else:
                self._corners.insert(at, point)
            self._emit()
        self._press = None
        self._dragging_pin = None
        self._panning = False
        self.setCursor(Qt.CrossCursor)
        self.update()

    def wheelEvent(self, e):
        p = QPointF(e.pos())
        before = self.to_latlng(p)
        self._zoom = max(MIN_ZOOM, min(self._zoom + e.angleDelta().y() / 480.0, MAX_ZOOM + 1))
        bx, by = unit_xy(*before)
        world = self._world()
        self._center = (bx - (p.x() - self.width() / 2) / world,
                        by - (p.y() - self.height() / 2) / world)
        self.update()

    # ---------- painting ----------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), theme.RADIUS, theme.RADIUS)
        p.setClipPath(clip)
        p.fillRect(self.rect(), theme.qcolor(theme.MAP_WATER))
        if not self._has_center:
            _draw_note(p, QRectF(self.rect()), "Enter a centre point and press Go to",
                       "the map opens there; then click to pin each corner")
            return
        drew_tiles = self._draw_tiles(p)
        if not drew_tiles:
            self._draw_grid(p)
        self._draw_ring(p)
        self._draw_center_mark(p)
        self._draw_scale(p)
        self._draw_hint(p, drew_tiles)

    def _draw_tiles(self, p: QPainter) -> bool:
        z = int(max(0, min(MAX_ZOOM, round(self._zoom))))
        n = 1 << z
        size = TILE_SIZE * 2 ** (self._zoom - z)
        world = self._world()
        left = self._center[0] - self.width() / 2 / world
        top = self._center[1] - self.height() / 2 / world
        x0, y0 = math.floor(left * n), max(0, math.floor(top * n))
        x1 = math.floor((left + self.width() / world) * n)
        y1 = min(n - 1, math.floor((top + self.height() / world) * n))
        drew = False
        for tx in range(x0, x1 + 1):
            for ty in range(y0, y1 + 1):
                pix = self._tiles.tile(z, tx, ty)
                if pix is None:
                    continue
                px = (tx / n - left) * world
                py = (ty / n - top) * world
                p.drawPixmap(QRectF(px, py, size + 0.5, size + 0.5), pix, QRectF(pix.rect()))
                drew = True
        if drew:
            p.fillRect(self.rect(), theme.qcolor(theme.BG, 40))     # keep overlays readable
        return drew

    def _draw_grid(self, p: QPainter) -> None:
        mpp = metres_per_pixel(self.center()[0], self._zoom)
        px_step = _scale_step(mpp) / mpp
        p.setPen(QPen(theme.qcolor(theme.MAP_GRID), 1))
        x = self.width() / 2 % px_step
        while x < self.width():
            p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
            x += px_step
        y = self.height() / 2 % px_step
        while y < self.height():
            p.drawLine(QPointF(0, y), QPointF(self.width(), y))
            y += px_step

    def _draw_ring(self, p: QPainter) -> None:
        if not self._corners:
            return
        pts = [self.to_px(*c) for c in self._corners]
        if len(pts) >= 3:
            p.setBrush(QBrush(theme.qcolor(theme.MAP_PIN, 40)))
            p.setPen(QPen(theme.qcolor(theme.MAP_PIN, 230), 2))
            p.drawPolygon(QPolygonF(pts))
        elif len(pts) == 2:
            p.setPen(QPen(theme.qcolor(theme.MAP_PIN, 230), 2))
            p.drawLine(pts[0], pts[1])
        p.setFont(theme.mono_font(8, 700))
        for i, q in enumerate(pts):
            r = 11 if i == self._hover_pin else 9
            p.setPen(QPen(theme.qcolor(theme.BG), 2))
            p.setBrush(QBrush(theme.qcolor(theme.MAP_PIN)))
            p.drawEllipse(q, r, r)
            p.setPen(theme.qcolor(theme.BG))
            p.drawText(QRectF(q.x() - r, q.y() - r, 2 * r, 2 * r), Qt.AlignCenter, str(i + 1))

    def _draw_center_mark(self, p: QPainter) -> None:
        c = QPointF(self.width() / 2, self.height() / 2)
        p.setPen(QPen(theme.qcolor(theme.TEXT_STRONG, 160), 1))
        p.drawLine(c + QPointF(-8, 0), c + QPointF(8, 0))
        p.drawLine(c + QPointF(0, -8), c + QPointF(0, 8))

    def _draw_scale(self, p: QPainter) -> None:
        mpp = metres_per_pixel(self.center()[0], self._zoom)
        step = _scale_step(mpp)
        length = step / mpp
        x, y = 16.0, self.height() - 18.0
        p.setPen(QPen(theme.qcolor(theme.TEXT_STRONG), 2))
        p.drawLine(QPointF(x, y), QPointF(x + length, y))
        p.setFont(theme.mono_font(8, 600))
        p.drawText(QPointF(x, y - 6), f"{step:g} m")
        p.setPen(theme.qcolor(theme.TEXT_MUTED))
        p.setFont(theme.ui_font(7.5))
        p.drawText(QRectF(0, self.height() - 18, self.width() - 10, 16),
                   Qt.AlignRight | Qt.AlignVCenter, ATTRIBUTION)

    def _draw_hint(self, p: QPainter, drew_tiles: bool) -> None:
        text = ("Click: add corner · on an edge: insert · drag pin: move · "
                "right-click pin: delete · wheel: zoom")
        if not drew_tiles:
            text = "No imagery (offline, not cached yet) · " + text
        p.setFont(theme.ui_font(8, 600))
        width = min(self.width() - 20.0, p.fontMetrics().horizontalAdvance(text) + 20.0)
        r = QRectF(10, 10, width, 22)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(theme.qcolor(theme.SURFACE, 215)))
        p.drawRoundedRect(r, 6, 6)
        p.setPen(theme.qcolor(theme.TEXT))
        p.drawText(r.adjusted(10, 0, -10, 0), Qt.AlignVCenter | Qt.AlignLeft, text)


def _scale_step(metres_per_px: float) -> float:
    for step in SCALE_STEPS_M:
        if step / metres_per_px >= 70:
            return step
    return SCALE_STEPS_M[-1]


def _segment_distance(p: QPointF, a: QPointF, b: QPointF) -> float:
    dx, dy = b.x() - a.x(), b.y() - a.y()
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return math.hypot(p.x() - a.x(), p.y() - a.y())
    t = max(0.0, min(1.0, ((p.x() - a.x()) * dx + (p.y() - a.y()) * dy) / length2))
    return math.hypot(p.x() - (a.x() + t * dx), p.y() - (a.y() + t * dy))


def _draw_note(p: QPainter, r: QRectF, title: str, detail: str) -> None:
    p.setPen(theme.qcolor(theme.TEXT_MUTED))
    p.setFont(theme.ui_font(11, 700))
    p.drawText(r.adjusted(0, -12, 0, -12), Qt.AlignCenter, title)
    p.setPen(theme.qcolor(theme.TEXT_FAINT))
    p.setFont(theme.ui_font(9))
    p.drawText(r.adjusted(0, 14, 0, 14), Qt.AlignCenter, detail)
