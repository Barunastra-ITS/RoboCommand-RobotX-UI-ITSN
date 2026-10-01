"""Course map visualization.

Renders the standard RobotX 2026 course schematic (pontoons + UAV L/R, Safe
Passage buoy field, pipeline, Coordinated Logistics platform, seawall) scaled
to fit the received RxCourse boundary, then overlays the live data the OCS
actually has: vehicle positions/headings, the UAV geofence, and the task
reports (Safe Passage buoys with beacon states, the pipeline survey).

Only the boundary polygon comes from the wire. The schematic elements are the
standardized course layout and are drawn as a labeled context layer; the live
points are drawn at their real lat/lng.
"""

import math

from PyQt5.QtWidgets import QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QWidget, QCheckBox
from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QPolygonF, QFont

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
    QLabel { color: #6c7086; font-style: italic; font-size: 11px; }
    QCheckBox { color: #cdd6f4; font-size: 11px; }
"""

# --- palette -------------------------------------------------------------
WATER = QColor(0xa9, 0xc6, 0xd9)          # reference light-blue water
WATER_GRID = QColor(0x93, 0xb3, 0xc9)
BOUNDARY = QColor(0x25, 0x3b, 0x52)
GEOFENCE = QColor(0xf9, 0xe2, 0x17)       # amber dashed UAV geofence
SCHEMATIC = QColor(0x8a, 0x7f, 0x6e)      # tan platform / pontoons
PONT = QColor(0x2f, 0x5f, 0x8a)
SEA = QColor(0x33, 0x3f, 0x4f)
BUOY_BODY = QColor(0xf4, 0xf6, 0xf8)
BUOY_EDGE = QColor(0x55, 0x60, 0x6b)
TEXT = QColor(0x25, 0x3b, 0x52)

VEHICLE_COLORS = {
    "USV": QColor(0x4c, 0xaf, 0x50),
    "UUV": QColor(0x21, 0x96, 0xf3),
    "UAV": QColor(0xff, 0xa0, 0x00),
}
UNKNOWN_COLOR = QColor(0x9e, 0x9e, 0x9e)

# beacon state -> (color, is_flashing)
from robocommand_ui.proto_helper import rx_common_pb2

_BEACON = {
    rx_common_pb2.BEACON_STATE_FLASHING_RED: (QColor(0xe5, 0x39, 0x35), True),
    rx_common_pb2.BEACON_STATE_FLASHING_GREEN: (QColor(0x4c, 0xaf, 0x50), True),
    rx_common_pb2.BEACON_STATE_FLASHING_BLUE: (QColor(0x1e, 0x88, 0xe5), True),
    rx_common_pb2.BEACON_STATE_STEADY_BLUE: (QColor(0x1e, 0x88, 0xe5), False),
    rx_common_pb2.BEACON_STATE_OFF: (QColor(0x9e, 0x9e, 0x9e), False),
}
_SEGMENT = {
    rx_common_pb2.PIPELINE_SEGMENT_INTACT: QColor(0x4c, 0xaf, 0x50),
    rx_common_pb2.PIPELINE_SEGMENT_DAMAGED: QColor(0xe5, 0x39, 0x35),
}
_SEGMENT_DEFAULT = QColor(0x9e, 0x9e, 0x9e)


def _type_key(hb) -> str:
    try:
        from robocommand_ui.proto_helper import vehicle_type_name
        return vehicle_type_name(hb.vehicle_type)
    except Exception:
        return "UNKNOWN"


class CourseMapWidget(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Course Map (top-down)", parent)
        self.setStyleSheet(STYLE)
        self.setMinimumHeight(420)

        layout = QVBoxLayout(self)

        self._canvas = MapCanvas(self)
        self._canvas.setMinimumHeight(360)

        # toolbar
        tb = QHBoxLayout()
        tb.addWidget(QLabel("Course map: live positions over the standard course schematic."))
        tb.addStretch()
        self.schematic_chk = QCheckBox("schematic")
        self.schematic_chk.setChecked(True)
        self.schematic_chk.toggled.connect(self._canvas.set_schematic)
        tb.addWidget(self.schematic_chk)
        layout.addLayout(tb)

        layout.addWidget(self._canvas)

        self._empty_label = QLabel("No course received yet.")
        self._empty_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._empty_label)

    def set_course(self, course):
        self._canvas.set_course_points(
            [(c.latitude, c.longitude) for c in course.corners],
            course.course_id)
        self._empty_label.hide()
        self.update()

    def set_geofence(self, points):
        self._canvas.set_geofence(points)
        self.update()

    def update_vehicle(self, vehicle_id, heartbeat, seq):
        self._canvas.set_vehicle(vehicle_id, heartbeat)
        self.update()

    def set_safe_passage(self, entry, exit_pos, buoys):
        """entry/exit: (lat, lng); buoys: list[(lat, lng, beacon_state_int)]."""
        self._canvas.set_safe_passage(entry, exit_pos, buoys)
        self.update()

    def set_pipeline(self, active, segments):
        """active: (lat, lng); segments: list[PIPELINE_SEGMENT_* int]."""
        self._canvas.set_pipeline(active, segments)
        self.update()

    def clear_vehicles(self):
        self._canvas.clear_vehicles()
        self.update()

    def clear_task_data(self):
        self._canvas.clear_task_data()
        self.update()


class MapCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(320)
        self.setStyleSheet("background-color: #0f1824; border-radius: 4px;")
        self._course_points = []
        self._geofence_points = []
        self._vehicles = {}
        self._course_id = ""
        self._show_schematic = True
        self._sp_entry = None      # (lat, lng)
        self._sp_exit = None
        self._sp_buoys = []        # list[(lat,lng,state)]
        self._pl_active = None     # (lat,lng)
        self._pl_segments = []

    # --- data setters ---
    def set_schematic(self, on: bool):
        self._show_schematic = on
        self.update()

    def set_course_points(self, points, course_id=""):
        self._course_points = points
        self._course_id = course_id

    def set_geofence(self, points):
        self._geofence_points = points

    def set_vehicle(self, vehicle_id, heartbeat):
        self._vehicles[vehicle_id] = heartbeat

    def clear_vehicles(self):
        self._vehicles.clear()

    def set_safe_passage(self, entry, exit_pos, buoys):
        self._sp_entry = entry
        self._sp_exit = exit_pos
        self._sp_buoys = buoys

    def set_pipeline(self, active, segments):
        self._pl_active = active
        self._pl_segments = segments

    def clear_task_data(self):
        self._sp_entry = None
        self._sp_exit = None
        self._sp_buoys = []
        self._pl_active = None
        self._pl_segments = []

    # --- geometry helpers ---
    def _all_points(self):
        pts = list(self._course_points) + list(self._geofence_points)
        for hb in self._vehicles.values():
            pts.append((hb.position.latitude, hb.position.longitude))
        if self._sp_entry:
            pts.append(self._sp_entry)
        if self._sp_exit:
            pts.append(self._sp_exit)
        for b in self._sp_buoys:
            pts.append((b[0], b[1]))
        if self._pl_active:
            pts.append(self._pl_active)
        return pts

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), WATER)

        points = self._all_points()
        if not points:
            p.setPen(QColor(0x6c, 0x70, 0x86))
            p.drawText(self.rect(), Qt.AlignCenter, "Awaiting RxCourse")
            return

        lats = [pt[0] for pt in points]
        lngs = [pt[1] for pt in points]
        min_lat, max_lat = min(lats), max(lats)
        min_lng, max_lng = min(lngs), max(lngs)
        span_lat = max(max_lat - min_lat, 1e-5)
        span_lng = max(max_lng - min_lng, 1e-5)
        min_lat -= span_lat * 0.12
        max_lat += span_lat * 0.12
        min_lng -= span_lng * 0.12
        max_lng += span_lng * 0.12

        w = self.width() - 24
        h = self.height() - 24
        if w <= 0 or h <= 0:
            return
        lat_scale = math.cos(math.radians((min_lat + max_lat) / 2.0))
        data_w = (max_lng - min_lng) * lat_scale
        data_h = max_lat - min_lat
        if data_w <= 0 or data_h <= 0:
            return
        scale = min(w / data_w, h / data_h)
        off_x = 12 + (w - data_w * scale) / 2.0
        off_y = 12 + (h - data_h * scale) / 2.0

        def scr(lat, lng):
            return QPointF(off_x + (lng - min_lng) * lat_scale * scale,
                           off_y + (max_lat - lat) * scale)

        # bbox of the course (screen) for schematic placement
        if self._course_points:
            cp = [scr(a, b) for a, b in self._course_points]
            bbox = (min(q.x() for q in cp), min(q.y() for q in cp),
                    max(q.x() for q in cp), max(q.y() for q in cp))
        else:
            bbox = (off_x, off_y, off_x + data_w * scale, off_y + data_h * scale)
        bx0, by0, bx1, by1 = bbox
        bw, bh = bx1 - bx0, by1 - by0

        # --- schematic context (standard course layout) ---
        if self._show_schematic:
            self._draw_schematic(p, bbox)

        # --- water grid ---
        p.setPen(QPen(WATER_GRID, 1))
        step = 40
        gx = int(off_x)
        while gx < self.width() - 12:
            p.drawLine(QPointF(gx, off_y), QPointF(gx, off_y + data_h * scale))
            gx += step
        gy = int(off_y)
        while gy < self.height() - 12:
            p.drawLine(QPointF(off_x, gy), QPointF(off_x + data_w * scale, gy))
            gy += step

        # --- boundary polygon ---
        if len(self._course_points) >= 3:
            poly = QPolygonF([scr(a, b) for a, b in self._course_points])
            p.setBrush(QBrush(QColor(0x66, 0x99, 0xcc, 60)))
            p.setPen(QPen(BOUNDARY, 2.5))
            p.drawPolygon(poly)
            p.setPen(QPen(BOUNDARY, 1))
            for i, (a, b) in enumerate(self._course_points[:-1]):
                q = scr(a, b)
                p.setBrush(QBrush(BOUNDARY))
                p.drawEllipse(q, 2, 2)

        # --- safe passage (Task 1) ---
        for b in self._sp_buoys:
            color, flashing = _BEACON.get(b[2], (QColor(0x9e, 0x9e, 0x9e), False))
            self._draw_buoy(p, scr(b[0], b[1]), color, flashing, 9)
        if self._sp_entry:
            self._draw_ring_marker(p, scr(*self._sp_entry), QColor(0x1e, 0x88, 0xe5), "ENTRY")
        if self._sp_exit:
            self._draw_ring_marker(p, scr(*self._sp_exit), QColor(0x1e, 0x88, 0xe5), "EXIT")

        # --- pipeline (Task 2) ---
        if self._pl_active:
            q = scr(*self._pl_active)
            color, _ = _BEACON[rx_common_pb2.BEACON_STATE_FLASHING_GREEN]
            self._draw_buoy(p, q, color, True, 9)
            # segments as a schematic chain from the active buoy
            for i, seg in enumerate(self._pl_segments):
                sq = QPointF(q.x(), q.y() + 16 + i * 15)
                c = _SEGMENT.get(seg, _SEGMENT_DEFAULT)
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(c))
                p.drawEllipse(sq, 5, 5)

        # --- UAV geofence ---
        if len(self._geofence_points) >= 3:
            poly = QPolygonF([scr(a, b) for a, b in self._geofence_points])
            p.setBrush(QBrush(QColor(0xff, 0xa0, 0x00, 40)))
            p.setPen(QPen(GEOFENCE, 2, Qt.DashLine))
            p.drawPolygon(poly)

        # --- vehicles (top layer) ---
        for vid, hb in self._vehicles.items():
            key = _type_key(hb)
            color = VEHICLE_COLORS.get(key, UNKNOWN_COLOR)
            q = scr(hb.position.latitude, hb.position.longitude)
            p.setPen(QPen(QColor(0x11, 0x11, 0x1b), 2))
            p.setBrush(QBrush(color))
            p.drawEllipse(q, 6, 6)
            hr = math.radians(hb.heading_deg)
            vx, vy = math.sin(hr) * 22, -math.cos(hr) * 22
            p.setPen(QPen(color, 2))
            p.drawLine(q, QPointF(q.x() + vx, q.y() + vy))
            p.setPen(QPen(TEXT))
            p.setFont(QFont(QFont().family(), 7, QFont.Bold))
            p.drawText(int(q.x() + 10), int(q.y() + 4), vid)

        # --- legend + course id ---
        self._draw_legend(p)
        if self._course_id:
            p.setPen(QPen(TEXT))
            p.setFont(QFont(QFont().family(), 8, QFont.Bold))
            p.drawText(8, 14, f"Course: {self._course_id}")
            p.setFont(QFont(QFont().family(), 6))
            p.setPen(QPen(QColor(0x44, 0x55, 0x66)))
            p.drawText(8, 26, "live positions over standard course schematic")

    # --- drawing helpers ---
    def _draw_buoy(self, p, c, color, flashing, size):
        # body: white trapezoid (wider at bottom)
        w = size
        h = size + 2
        top = QPointF(c.x() - w * 0.55, c.y() - h * 0.5)
        bot_l = QPointF(c.x() - w * 0.95, c.y() + h * 0.6)
        bot_r = QPointF(c.x() + w * 0.95, c.y() + h * 0.6)
        top_r = QPointF(c.x() + w * 0.55, c.y() - h * 0.5)
        body = QPolygonF([bot_l, bot_r, top_r, top])
        p.setPen(QPen(BUOY_EDGE, 1.2))
        p.setBrush(QBrush(BUOY_BODY))
        p.drawPolygon(body)
        # beacon
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(color))
        p.drawEllipse(QPointF(c.x(), c.y() - h * 0.6), size * 0.42, size * 0.42)
        if flashing:
            p.setPen(QPen(color, 1))
            for ang in range(0, 360, 45):
                a = math.radians(ang)
                r1, r2 = size * 0.6, size * 0.95
                p.drawLine(
                    QPointF(c.x() + math.cos(a) * r1, c.y() - h * 0.6 + math.sin(a) * r1),
                    QPointF(c.x() + math.cos(a) * r2, c.y() - h * 0.6 + math.sin(a) * r2))

    def _draw_ring_marker(self, p, c, color, label):
        p.setPen(QPen(color, 2))
        for r in (8, 12):
            p.drawEllipse(c, r, r)
        p.setPen(QPen(color))
        p.setFont(QFont(QFont().family(), 6, QFont.Bold))
        p.drawText(int(c.x() + 14), int(c.y() - 6), label)

    def _draw_schematic(self, p, bbox):
        bx0, by0, bx1, by1 = bbox
        bw, bh = bx1 - bx0, by1 - by0

        def fx(frac_x, frac_y):
            return QPointF(bx0 + bw * frac_x, by0 + bh * frac_y)

        # Pontoons strip along the top
        p.setPen(QPen(PONT, 2))
        p.setBrush(QBrush(PONT))
        p.drawRect(QRectF(fx(0.0, 0.0), QPointF(fx(1.0, 0.06).x(), fx(0.0, 0.06).y())))
        p.setPen(QPen(QColor(0xf4, 0xf6, 0xf8)))
        p.setFont(QFont(QFont().family(), 6, QFont.Bold))
        p.drawText(int(fx(0.5, 0.0).x() - 24), int(fx(0.5, 0.0).y() + 8), "PONTTONS")

        # UAV L/R pad top-left
        pad = 16
        p.setPen(QPen(SEA, 1.5))
        p.setBrush(QBrush(QColor(0xcf, 0xd8, 0xe0)))
        p.drawRect(QRectF(fx(0.04, 0.08), QPointF(fx(0.04, 0.08).x() + pad,
                                                  fx(0.04, 0.08).y() + pad)))
        p.setPen(QPen(TEXT))
        p.setFont(QFont(QFont().family(), 5, QFont.Bold))
        p.drawText(int(fx(0.04, 0.08).x()), int(fx(0.04, 0.08).y() + pad / 2), "L/R")

        # Seawall along the bottom
        p.setPen(QPen(SEA, 2, Qt.DashLine))
        p.drawLine(QPointF(bx0, by1), QPointF(bx1, by1))
        p.setPen(QPen(TEXT))
        p.setFont(QFont(QFont().family(), 6, QFont.Bold))
        p.drawText(int((bx0 + bx1) / 2 - 30), int(by1 - 4), "SEAWALL")

        # Coordinated Logistics platform (right side) with 3 bays
        plat = fx(0.80, 0.42)
        px0, py0 = plat.x(), plat.y()
        pw, ph = bw * 0.12, bh * 0.40
        p.setPen(QPen(SCHEMATIC, 2))
        p.setBrush(QBrush(QColor(0xd8, 0xc9, 0xa8)))
        p.drawRect(QRectF(px0, py0, pw, ph))
        p.setPen(QPen(QColor(0xf4, 0xf6, 0xf8), 1))
        p.setBrush(QBrush(QColor(0xf4, 0xf6, 0xf8)))
        for i in range(3):
            by = py0 + ph * (0.15 + i * 0.30)
            p.drawRect(QRectF(px0 + pw * 0.55, by, pw * 0.35, ph * 0.22))
        p.setPen(QPen(TEXT))
        p.setFont(QFont(QFont().family(), 5, QFont.Bold))
        p.drawText(int(px0), int(py0 - 4), "coordinated logistics")

        # Task labels (context only — live data drawn at real positions)
        p.setPen(QPen(QColor(0x25, 0x3b, 0x52)))
        p.setFont(QFont(QFont().family(), 6, QFont.Bold))
        p.drawText(int(fx(0.34, 0.12).x()), int(fx(0.34, 0.12).y()), "safe passage")
        p.drawText(int(fx(0.12, 0.66).x()), int(fx(0.12, 0.66).y()), "infrastructure")
        p.drawText(int(fx(0.12, 0.72).x()), int(fx(0.12, 0.72).y()), "survey & repair")

    def _draw_legend(self, p):
        x = self.width() - 150
        y = self.height() - 96
        p.setPen(QPen(QColor(0x11, 0x11, 0x1b, 180), 1))
        p.setBrush(QBrush(QColor(0x1e, 0x1e, 0x2e, 200)))
        p.drawRect(QRectF(x, y, 140, 88))
        p.setPen(QPen(QColor(0xcc, 0xd6, 0xf4)))
        p.setFont(QFont(QFont().family(), 6, QFont.Bold))
        p.drawText(int(x + 8), int(y + 12), "Beacon states")
        p.setFont(QFont(QFont().family(), 6))
        entries = [
            (QColor(0xe5, 0x39, 0x35), "flashing red — starboard"),
            (QColor(0x4c, 0xaf, 0x50), "flashing green — port"),
            (QColor(0x1e, 0x88, 0xe5), "blue — entry / exit"),
            (QColor(0x9e, 0x9e, 0x9e), "off — not on route"),
        ]
        for i, (col, txt) in enumerate(entries):
            yy = y + 24 + i * 14
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(col))
            p.drawEllipse(QPointF(x + 14, yy - 3), 4, 4)
            p.setPen(QPen(QColor(0xcc, 0xd6, 0xf4)))
            p.drawText(int(x + 24), int(yy), txt)
