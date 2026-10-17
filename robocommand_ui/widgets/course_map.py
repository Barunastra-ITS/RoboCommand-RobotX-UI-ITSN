"""Top-down course map: what teams report, drawn in local metres.

Only reported data is drawn: the RxCourse boundary, each team's declared UAV
geofence, every vehicle's position, heading and fading trail (labelled
TEAM/VEHICLE, dimmed when its heartbeats go stale), and the latest Task 1
buoys / Task 2 pipeline reports. Positions are projected to metres around
the course so the grid and scale bar are true distances.

Satellite imagery (same source as the OCS map, cached on disk) is drawn
underneath when available; **Satellite** toggles it.

Mouse: wheel zooms about the cursor, drag pans, Shift+drag turns the map,
the compass (top right) turns it back to north-up, double-click re-fits.
"""

import math
import time
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
from PyQt5.QtWidgets import QPushButton, QWidget

from robocommand_ui import theme
from robocommand_ui.fleet_state import STALE_SECONDS
from robocommand_ui.proto_helper import rx_common_pb2, vehicle_type_name
from robocommand_ui.widgets.compass import (
    draw_compass, drag_bearing, on_compass, rotate, unrotate,
)
from robocommand_ui.widgets.panel import Panel
from robocommand_ui.widgets.tiles import (
    ATTRIBUTION, MAX_ZOOM, TILE_SIZE, shared_loader, unit_to_latlng, unit_xy,
)

LatLng = Tuple[float, float]
M_PER_DEG_LAT = 111_320.0
GRID_STEPS_M = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000)
MIN_GRID_PX = 64
WORLD_HEIGHT_FILL = 1.35          # world view: Mercator square taller than the map, poles cropped
EARTH_M_PER_PX_Z0 = 156_543.033928
FIT_MARGIN = 0.12

# Real-world buoy beacon colours (data, not UI status)
BEACONS = {
    rx_common_pb2.BEACON_STATE_FLASHING_RED: ("#EF4444", True),
    rx_common_pb2.BEACON_STATE_FLASHING_GREEN: ("#22C55E", True),
    rx_common_pb2.BEACON_STATE_FLASHING_BLUE: ("#3B82F6", True),
    rx_common_pb2.BEACON_STATE_STEADY_BLUE: ("#3B82F6", False),
    rx_common_pb2.BEACON_STATE_OFF: ("#64748B", False),
}
SEGMENTS = {
    rx_common_pb2.PIPELINE_SEGMENT_INTACT: theme.OK,
    rx_common_pb2.PIPELINE_SEGMENT_DAMAGED: theme.FAULT,
}


class CourseMapWidget(Panel):
    clear_requested = pyqtSignal()          # operator wants trails / task overlays gone

    def __init__(self, parent=None):
        super().__init__("Course map", parent, body_margins=(0, 0, 0, 0))
        self._canvas = MapCanvas(self)
        self.body.addWidget(self._canvas, 1)

        self.sat_btn = QPushButton("Satellite")
        self.sat_btn.setObjectName("Ghost")
        self.sat_btn.setCheckable(True)
        self.sat_btn.setChecked(True)
        self.sat_btn.setCursor(Qt.PointingHandCursor)
        self.sat_btn.setToolTip("Satellite imagery under the course (cached for offline use)")
        self.sat_btn.toggled.connect(self._canvas.set_show_tiles)
        self.actions.addWidget(self.sat_btn)

        self.trails_btn = QPushButton("Trails")
        self.trails_btn.setObjectName("Ghost")
        self.trails_btn.setCheckable(True)
        self.trails_btn.setChecked(True)
        self.trails_btn.setCursor(Qt.PointingHandCursor)
        self.trails_btn.setToolTip("Show each vehicle's reported track")
        self.trails_btn.toggled.connect(self._canvas.set_show_trails)
        self.actions.addWidget(self.trails_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("Ghost")
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setToolTip("Clear trails and Task 1 / Task 2 overlays of the team shown\n"
                             "(every RunStart does this automatically)")
        clear_btn.clicked.connect(self.clear_requested)
        self.actions.addWidget(clear_btn)

        fit_btn = QPushButton("Fit")
        fit_btn.setObjectName("Ghost")
        fit_btn.setCursor(Qt.PointingHandCursor)
        fit_btn.setToolTip("Fit the course (or double-click the map)")
        fit_btn.clicked.connect(self._canvas.reset_view)
        self.actions.addWidget(fit_btn)

    def set_course(self, course):
        self._canvas.set_course_points(
            [(c.latitude, c.longitude) for c in course.corners], course.course_id)
        self._update_meta()

    def show_fleet(self, fleet, team_filter=None, now: Optional[float] = None):
        """Draw every reporting vehicle (or one team's) from a FleetState."""
        now = time.time() if now is None else now
        c = self._canvas
        vehicles = {}
        for v in fleet.vehicles_of(team_filter):
            if v.last_hb is not None and v.last_hb.HasField("position"):
                stale = (now - v.last_hb_time) > STALE_SECONDS
                vehicles[f"{v.team_id}/{v.vehicle_id}"] = (v.last_hb, list(v.trail), stale)
        c.set_vehicles(vehicles)

        teams = [fleet.teams[t] for t in fleet.team_ids() if team_filter in (None, t)]
        c.clear_task_data()
        c.set_geofence([])
        # Geofence and task overlays belong to one team; only one runs per course
        if len(teams) == 1:
            team = teams[0]
            c.set_geofence(team.geofence)
            if team.safe_passage:
                c.set_safe_passage(*team.safe_passage)
            if team.pipeline:
                c.set_pipeline(*team.pipeline)
        self._update_meta()
        c.update()

    def clear(self):
        self._canvas.set_vehicles({})
        self._canvas.clear_task_data()
        self._canvas.set_geofence([])
        self._update_meta()
        self._canvas.update()

    def _update_meta(self):
        c = self._canvas
        parts = []
        if c._course_id:
            parts.append(c._course_id)
        n = len(c._vehicles)
        parts.append(f"{n} vehicle{'s' if n != 1 else ''}")
        self.set_meta("  ·  ".join(parts))


class MapCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 320)
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)
        self._course_points: List[LatLng] = []
        self._geofence_points: List[LatLng] = []
        self._vehicles: Dict[str, tuple] = {}     # label -> (heartbeat, trail, stale)
        self._course_id = ""
        self._sp_entry: Optional[LatLng] = None
        self._sp_exit: Optional[LatLng] = None
        self._sp_buoys: List[Tuple[float, float, int]] = []
        self._pl_active: Optional[LatLng] = None
        self._pl_segments: List[int] = []
        self._show_trails = True
        self._show_tiles = True
        self._tiles = shared_loader()
        self._tiles.updated.connect(self.update)
        # view: local metres -> pixels
        self._origin: Optional[LatLng] = None
        self._scale = 1.0                     # px per metre
        self._center_m = (0.0, 0.0)           # metres at widget centre
        self._user_view = False
        self._drag_from: Optional[QPointF] = None
        self._bearing = 0.0                   # compass direction shown up (Shift+drag)
        self._rotating = False
        self._compass_hover = False

    # ---------------- data ----------------
    def set_course_points(self, points, course_id=""):
        self._course_points = list(points)
        self._course_id = course_id
        self._origin = None
        self._user_view = False
        self.update()

    def set_geofence(self, points):
        self._geofence_points = list(points)

    def set_vehicles(self, vehicles):
        self._vehicles = dict(vehicles)

    def set_safe_passage(self, entry, exit_pos, buoys):
        self._sp_entry, self._sp_exit, self._sp_buoys = entry, exit_pos, list(buoys)

    def set_pipeline(self, active, segments):
        self._pl_active, self._pl_segments = active, list(segments)

    def clear_task_data(self):
        self._sp_entry = self._sp_exit = self._pl_active = None
        self._sp_buoys, self._pl_segments = [], []

    def set_show_tiles(self, on: bool):
        self._show_tiles = on
        self.update()

    def set_show_trails(self, on: bool):
        self._show_trails = on
        self.update()

    def reset_view(self):
        self._user_view = False
        self.update()

    def bearing(self) -> float:
        return self._bearing

    def set_bearing(self, bearing: float) -> None:
        self._bearing = bearing % 360.0
        self.update()

    # ---------------- projection ----------------
    def _ensure_origin(self) -> bool:
        if self._origin is None:
            pts = self._course_points or [
                (hb.position.latitude, hb.position.longitude) for hb, _, _ in self._vehicles.values()]
            if not pts:
                return False
            self._origin = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        return True

    def to_m(self, lat: float, lng: float) -> Tuple[float, float]:
        lat0, lng0 = self._origin
        return ((lng - lng0) * M_PER_DEG_LAT * math.cos(math.radians(lat0)),
                (lat - lat0) * M_PER_DEG_LAT)

    def to_px(self, lat: float, lng: float) -> QPointF:
        x, y = self.to_m(lat, lng)
        return self._m_to_px(x, y)

    def _m_to_px(self, x: float, y: float) -> QPointF:
        """Metres -> pixels on the map as shown (turned to the bearing)."""
        q = self._m_to_px0(x, y)
        w2, h2 = self.width() / 2, self.height() / 2
        rx, ry = rotate(q.x() - w2, q.y() - h2, self._bearing)
        return QPointF(w2 + rx, h2 + ry)

    def _px_to_m(self, p: QPointF) -> Tuple[float, float]:
        w2, h2 = self.width() / 2, self.height() / 2
        ux, uy = unrotate(p.x() - w2, p.y() - h2, self._bearing)
        return self._px0_to_m(QPointF(w2 + ux, h2 + uy))

    def _m_to_px0(self, x: float, y: float) -> QPointF:
        """Metres -> pixels on the north-up map (before turning)."""
        cx, cy = self._center_m
        return QPointF(self.width() / 2 + (x - cx) * self._scale,
                       self.height() / 2 - (y - cy) * self._scale)

    def _px0_to_m(self, p: QPointF) -> Tuple[float, float]:
        cx, cy = self._center_m
        return (cx + (p.x() - self.width() / 2) / self._scale,
                cy - (p.y() - self.height() / 2) / self._scale)

    def _north_up_view(self) -> QRectF:
        """North-up pixel area that covers the turned widget (its circumscribed square)."""
        r = math.hypot(self.width(), self.height()) / 2
        return QRectF(self.width() / 2 - r, self.height() / 2 - r, 2 * r, 2 * r)

    def _turned(self, p: QPainter) -> None:
        """Make ``p`` draw north-up coordinates onto the turned map."""
        p.translate(self.width() / 2, self.height() / 2)
        p.rotate(-self._bearing)
        p.translate(-self.width() / 2, -self.height() / 2)

    def _fit(self):
        pts = list(self._course_points) + list(self._geofence_points)
        if not pts:
            pts = [(hb.position.latitude, hb.position.longitude) for hb, _, _ in self._vehicles.values()]
        # extents in the turned frame (x right, y down on screen), in metres
        turned = [rotate(x, -y, self._bearing) for x, y in (self.to_m(a, b) for a, b in pts)]
        xs, ys = [t[0] for t in turned], [t[1] for t in turned]
        w = max(max(xs) - min(xs), 20.0)
        h = max(max(ys) - min(ys), 20.0)
        cx, cy = unrotate((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, self._bearing)
        self._center_m = (cx, -cy)
        self._scale = min(self.width() / (w * (1 + 2 * FIT_MARGIN)),
                          self.height() / (h * (1 + 2 * FIT_MARGIN)))

    # ---------------- interaction ----------------
    def wheelEvent(self, e):
        if self._origin is None:
            return
        before = self._px_to_m(e.pos())
        factor = 1.0015 ** e.angleDelta().y()
        self._scale = max(0.05, min(self._scale * factor, 400.0))
        after = self._px_to_m(e.pos())
        cx, cy = self._center_m
        self._center_m = (cx + before[0] - after[0], cy + before[1] - after[1])
        self._user_view = True
        self.update()

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self._origin is not None and on_compass(QPointF(e.pos()), self.width()):
            self.set_bearing(0.0)               # back to north-up
            return
        self._drag_from = QPointF(e.pos())
        self._rotating = bool(e.modifiers() & Qt.ShiftModifier)
        self.setCursor(Qt.SizeAllCursor if self._rotating else Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        pos = QPointF(e.pos())
        if self._drag_from is None:
            hover = self._origin is not None and on_compass(pos, self.width())
            if hover != self._compass_hover:
                self._compass_hover = hover
                self.setCursor(Qt.PointingHandCursor if hover else Qt.OpenHandCursor)
                self.update()
            return
        if self._rotating:
            center = QPointF(self.width() / 2, self.height() / 2)
            self._bearing = drag_bearing(self._bearing, center, self._drag_from, pos)
        else:
            d = pos - self._drag_from
            dx, dy = unrotate(d.x(), d.y(), self._bearing)
            cx, cy = self._center_m
            self._center_m = (cx - dx / self._scale, cy + dy / self._scale)
        self._drag_from = pos
        self._user_view = True
        self.update()

    def mouseReleaseEvent(self, e):
        self._drag_from = None
        self._rotating = False
        self.setCursor(Qt.OpenHandCursor)

    def mouseDoubleClickEvent(self, e):
        if not on_compass(QPointF(e.pos()), self.width()):
            self.reset_view()

    # ---------------- painting ----------------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), theme.RADIUS, theme.RADIUS)
        p.setClipPath(path)
        p.fillRect(self.rect(), theme.qcolor(theme.MAP_WATER))

        if not self._ensure_origin():
            if self._show_tiles:
                self._draw_world(p)         # global satellite view, as on the OCS
            self._draw_empty(p)
            return
        if not self._user_view:
            self._fit()

        drew_tiles = self._show_tiles and self._draw_tiles(p)
        if not drew_tiles:
            self._draw_grid(p)
        self._draw_boundary(p)
        self._draw_geofence(p)
        self._draw_tasks(p)
        if self._show_trails:
            self._draw_trails(p)
        self._draw_vehicles(p)
        self._draw_scale_and_north(p)
        self._draw_legend(p)

    def _px0_to_latlng(self, q: QPointF) -> LatLng:
        x, y = self._px0_to_m(q)
        lat0, lng0 = self._origin
        return (lat0 + y / M_PER_DEG_LAT,
                lng0 + x / (M_PER_DEG_LAT * math.cos(math.radians(lat0))))

    def _draw_tiles(self, p) -> bool:
        """Satellite tiles under the course; False when none are available."""
        lat0 = self._origin[0]
        mpp = 1.0 / self._scale
        z = int(max(0, min(MAX_ZOOM, round(math.log2(
            EARTH_M_PER_PX_Z0 * math.cos(math.radians(lat0)) / mpp)))))
        n = 1 << z
        view = self._north_up_view()
        ux0, uy0 = unit_xy(*self._px0_to_latlng(view.topLeft()))
        ux1, uy1 = unit_xy(*self._px0_to_latlng(view.bottomRight()))
        drew = False
        p.save()
        self._turned(p)
        for tx in range(math.floor(ux0 * n), math.floor(ux1 * n) + 1):
            for ty in range(max(0, math.floor(uy0 * n)), min(n - 1, math.floor(uy1 * n)) + 1):
                pix = self._tiles.tile(z, tx, ty)
                if pix is None:
                    continue
                nw = self._m_to_px0(*self.to_m(*unit_to_latlng(tx / n, ty / n)))
                se = self._m_to_px0(*self.to_m(*unit_to_latlng((tx + 1) / n, (ty + 1) / n)))
                p.drawPixmap(QRectF(nw, se).adjusted(0, 0, 0.5, 0.5), pix, QRectF(pix.rect()))
                drew = True
        p.restore()
        if drew:
            p.fillRect(self.rect(), theme.qcolor(theme.MAP_DIM, 70))     # keep overlays readable
            p.setPen(theme.qcolor(theme.TEXT_MUTED))
            p.setFont(theme.ui_font(7.5))
            p.drawText(QRectF(0, self.height() - 16, self.width(), 14), Qt.AlignCenter,
                       ATTRIBUTION)
        return drew

    def _draw_world(self, p) -> bool:
        """Whole-world imagery, repeated east-west, until there is a course or a boat."""
        w, h = self.width(), self.height()
        world = h * WORLD_HEIGHT_FILL
        z = int(max(1, min(MAX_ZOOM, round(math.log2(world / TILE_SIZE)))))
        n = 1 << z
        size = world / n
        left, top = w / 2 - world / 2, h / 2 - world / 2
        drew = False
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        for tx in range(math.floor(-left / size), math.floor((w - left) / size) + 1):
            for ty in range(max(0, math.floor(-top / size)), min(n - 1, math.floor((h - top) / size)) + 1):
                pix = self._tiles.tile(z, tx, ty)
                if pix is not None:
                    p.drawPixmap(QRectF(left + tx * size, top + ty * size, size + 0.5, size + 0.5),
                                 pix, QRectF(pix.rect()))
                    drew = True
        if drew:
            p.setPen(theme.qcolor(theme.TEXT_MUTED))
            p.setFont(theme.ui_font(7.5))
            p.drawText(QRectF(0, h - 16, w - 10, 14), Qt.AlignRight | Qt.AlignVCenter, ATTRIBUTION)
        return drew

    def _draw_empty(self, p):
        """Centred card over the world view (or the plain well when offline)."""
        r = QRectF(self.rect())
        card = QRectF(0, 0, min(320.0, r.width() - 40), 132)
        card.moveCenter(r.center())
        p.setPen(QPen(theme.qcolor(theme.BORDER), 1))
        p.setBrush(QBrush(theme.qcolor(theme.SURFACE, 215)))
        p.drawRoundedRect(card, theme.RADIUS_LG, theme.RADIUS_LG)
        # radar glyph
        c = QPointF(card.center().x(), card.top() + 52)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(theme.qcolor(theme.TEXT_MUTED), 1.4))
        for radius in (8, 16, 24):
            p.drawEllipse(c, radius, radius)
        p.drawLine(c, c + QPointF(17, -17))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(theme.qcolor(theme.TEXT_MUTED)))
        p.drawEllipse(c, 2.5, 2.5)
        p.setPen(theme.qcolor(theme.TEXT))
        p.setFont(theme.ui_font(12, 700))
        p.drawText(QRectF(card.left(), card.top() + 88, card.width(), 26), Qt.AlignCenter,
                   "NO COURSE")

    def _grid_step(self) -> float:
        for step in GRID_STEPS_M:
            if step * self._scale >= MIN_GRID_PX:
                return step
        return GRID_STEPS_M[-1]

    def _draw_grid(self, p):
        step = self._grid_step()
        view = self._north_up_view()
        x0, y1 = self._px0_to_m(view.topLeft())
        x1, y0 = self._px0_to_m(view.bottomRight())
        p.save()
        self._turned(p)
        p.setPen(QPen(theme.qcolor(theme.MAP_GRID), 1))
        gx = math.floor(x0 / step) * step
        while gx <= x1:
            q = self._m_to_px0(gx, 0)
            p.drawLine(QPointF(q.x(), view.top()), QPointF(q.x(), view.bottom()))
            gx += step
        gy = math.floor(y0 / step) * step
        while gy <= y1:
            q = self._m_to_px0(0, gy)
            p.drawLine(QPointF(view.left(), q.y()), QPointF(view.right(), q.y()))
            gy += step
        p.restore()

    def _draw_boundary(self, p):
        if len(self._course_points) < 3:
            return
        poly = QPolygonF([self.to_px(a, b) for a, b in self._course_points])
        p.setBrush(QBrush(theme.qcolor(theme.MAP_BOUNDARY, 14)))
        p.setPen(QPen(theme.qcolor(theme.MAP_DIM, 150), 3.6))     # halo: readable on any ground
        p.drawPolygon(poly)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(theme.qcolor(theme.MAP_BOUNDARY, 230), 1.6))
        p.drawPolygon(poly)
        p.setBrush(QBrush(theme.qcolor(theme.MAP_BOUNDARY)))
        p.setPen(Qt.NoPen)
        for a, b in self._course_points[:-1]:
            p.drawEllipse(self.to_px(a, b), 2.5, 2.5)

    def _draw_geofence(self, p):
        if len(self._geofence_points) < 3:
            return
        poly = QPolygonF([self.to_px(a, b) for a, b in self._geofence_points])
        p.setBrush(QBrush(theme.qcolor(theme.MAP_GEOFENCE, 18)))
        pen = QPen(theme.qcolor(theme.MAP_GEOFENCE, 210), 1.4, Qt.DashLine)
        pen.setDashPattern([6, 4])
        p.setPen(pen)
        p.drawPolygon(poly)

    def _draw_tasks(self, p):
        for lat, lng, state in self._sp_buoys:
            color, flashing = BEACONS.get(state, (theme.TEXT_FAINT, False))
            q = self.to_px(lat, lng)
            if flashing:
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(theme.qcolor(color, 60)))
                p.drawEllipse(q, 10, 10)
            p.setPen(QPen(theme.qcolor(theme.BG), 1.5))
            p.setBrush(QBrush(theme.qcolor(color)))
            p.drawEllipse(q, 5, 5)
        for point, label in ((self._sp_entry, "ENTRY"), (self._sp_exit, "EXIT")):
            if point:
                q = self.to_px(*point)
                p.setPen(QPen(theme.qcolor(theme.INFO), 1.6))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(q, 9, 9)
                p.setFont(theme.mono_font(7.5, 700))
                p.drawText(QPointF(q.x() + 12, q.y() - 8), label)
        if self._pl_active:
            q = self.to_px(*self._pl_active)
            p.setPen(QPen(theme.qcolor(theme.BG), 1.5))
            p.setBrush(QBrush(theme.qcolor(theme.OK)))
            p.drawEllipse(q, 6, 6)
            for i, seg in enumerate(self._pl_segments):
                p.setBrush(QBrush(theme.qcolor(SEGMENTS.get(seg, theme.TEXT_FAINT))))
                p.drawEllipse(QPointF(q.x() + 14 + i * 12, q.y()), 4, 4)

    def _draw_trails(self, p):
        for hb, trail, stale in self._vehicles.values():
            if len(trail) < 2:
                continue
            color = theme.type_color(vehicle_type_name(hb.vehicle_type))
            pts = [self.to_px(a, b) for a, b in trail]
            n = len(pts)
            for i in range(1, n):
                alpha = int(25 + 150 * (i / n))          # older = fainter
                if stale:
                    alpha //= 2
                p.setPen(QPen(theme.qcolor(color, alpha), 2, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(pts[i - 1], pts[i])

    def _draw_vehicles(self, p):
        fm = QFontMetrics(theme.mono_font(8, 600))
        for label, (hb, _, stale) in sorted(self._vehicles.items()):
            color = theme.type_color(vehicle_type_name(hb.vehicle_type))
            q = self.to_px(hb.position.latitude, hb.position.longitude)
            alpha = 110 if stale else 255
            # heading arrow
            h = math.radians(hb.heading_deg - self._bearing)       # as drawn on the turned map
            fwd = QPointF(math.sin(h), -math.cos(h))
            side = QPointF(-fwd.y(), fwd.x())
            arrow = QPolygonF([q + fwd * 11, q - fwd * 7 + side * 7, q - fwd * 3, q - fwd * 7 - side * 7])
            p.setPen(QPen(theme.qcolor(theme.BG, alpha), 2))
            p.setBrush(QBrush(theme.qcolor(color, alpha)))
            p.drawPolygon(arrow)
            if stale:
                pen = QPen(theme.qcolor(theme.WARN, 200), 1.2, Qt.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(q, 15, 15)
            # label chip
            text = label + ("  STALE" if stale else "")
            w = fm.horizontalAdvance(text) + 12
            r = QRectF(q.x() + 14, q.y() - 22, w, 18)
            p.setPen(QPen(theme.qcolor(color, 140 if not stale else 70), 1))
            p.setBrush(QBrush(theme.qcolor(theme.SURFACE, 225)))
            p.drawRoundedRect(r, 4, 4)
            p.setPen(theme.qcolor(theme.WARN if stale else theme.TEXT))
            p.setFont(theme.mono_font(8, 600))
            p.drawText(r, Qt.AlignCenter, text)

    def _draw_scale_and_north(self, p):
        step = self._grid_step()
        length = step * self._scale
        x, y = 16, self.height() - 18
        p.setPen(QPen(theme.qcolor(theme.TEXT_MUTED), 1.5))
        p.drawLine(QPointF(x, y), QPointF(x + length, y))
        p.drawLine(QPointF(x, y - 4), QPointF(x, y + 1))
        p.drawLine(QPointF(x + length, y - 4), QPointF(x + length, y + 1))
        p.setFont(theme.mono_font(8))
        p.drawText(QPointF(x, y - 7), f"{step:g} m")
        draw_compass(p, self.width(), self._bearing, self._compass_hover)

    def _draw_legend(self, p):
        types = sorted({vehicle_type_name(hb.vehicle_type) for hb, _, _ in self._vehicles.values()})
        items = [(theme.type_color(t), t) for t in types]
        if self._geofence_points:
            items.append((theme.MAP_GEOFENCE, "UAV geofence"))
        if not items:
            return
        p.setFont(theme.ui_font(8))
        fm = QFontMetrics(theme.ui_font(8))
        w = max(fm.horizontalAdvance(t) for _, t in items) + 34
        h = 10 + 16 * len(items)
        r = QRectF(self.width() - w - 12, self.height() - h - 12, w, h)
        p.setPen(QPen(theme.qcolor(theme.BORDER), 1))
        p.setBrush(QBrush(theme.qcolor(theme.SURFACE, 220)))
        p.drawRoundedRect(r, 6, 6)
        for i, (color, text) in enumerate(items):
            cy = r.top() + 13 + i * 16
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(theme.qcolor(color)))
            p.drawRoundedRect(QRectF(r.left() + 10, cy - 4, 10, 8), 2, 2)
            p.setPen(theme.qcolor(theme.TEXT_MUTED))
            p.drawText(QPointF(r.left() + 26, cy + 4), text)
