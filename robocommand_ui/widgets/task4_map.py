"""Task 4 map: the course map with a centre crosshair and command previews.

Everything the Map tab draws (course, UAV transit area, the team's vehicles
and trails, its geofence and reported Task 1 / Task 2 objects), plus:

- a crosshair at the map centre. Panning moves it, and ``center_changed``
  tells the Task 4 tab, whose position fields follow it;
- a preview of each Task 4 command before it is sent: the assistance point,
  the keep-out zone at its true radius (dashed red), and the moving object
  with its keep-out radius (dashed yellow) and a heading arrow. When the two
  rings fall on the same line (same place and radius, e.g. both 5 m), the
  ring alternates red and yellow dashes, so neither hides the other.
"""

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QBrush, QFontMetrics, QPen

from robocommand_ui import theme
from robocommand_ui.widgets.course_map import MapCanvas

LatLng = Tuple[float, float]
ARROW_SECONDS = 10.0        # the heading arrow shows this long of travel
MIN_ARROW_M = 4.0
CROSSHAIR_PX = 9
CENTER_EPS_DEG = 1e-10      # centre moves smaller than this are not news
DASH = 5                    # ring dash and gap, in pen widths
GAP = 3
SAME_RING_PX = 2.0          # rings this close in centre and radius are drawn as one line


@dataclass(frozen=True)
class Preview:
    """One Task 4 command as it would be sent."""
    point: LatLng
    label: str
    color: str
    radius_m: float = 0.0               # keep-out circle; 0 for none
    heading_deg: Optional[float] = None  # moving object
    speed_mps: float = 0.0
    active: bool = True                 # the team's declared tier: it can be sent


class IncidentMapCanvas(MapCanvas):
    center_changed = pyqtSignal(float, float)   # map centre lat, lng after a pan / zoom / fit

    def __init__(self, parent=None):
        super().__init__(parent)
        self._previews: List[Preview] = []
        self._last_center: Optional[LatLng] = None

    def set_previews(self, previews) -> None:
        self._previews = list(previews)
        self.update()

    def previews(self) -> List[Preview]:
        return list(self._previews)

    # ---------- centre ----------
    def _painted(self):
        center = self.center_latlng()
        if center is None:
            return
        last = self._last_center
        if last is None or max(abs(center[0] - last[0]), abs(center[1] - last[1])) > CENTER_EPS_DEG:
            self._last_center = center
            # after this paint: listeners may change the previews, which repaints
            QTimer.singleShot(0, lambda: self.center_changed.emit(*center))

    # ---------- drawing ----------
    def _draw_overlay(self, p):
        previews = sorted(self._previews, key=lambda v: v.active)       # active on top
        drawn = [self._draw_preview(p, preview, self._ring_colors(preview, previews))
                 for preview in previews]
        self._draw_crosshair(p)
        taken = [QRectF(tip.x() - 6, tip.y() - 6, 12, 12) for _, tip in drawn if tip is not None]
        for preview, (left, _) in zip(previews, drawn):     # labels over every shape
            if preview.active:
                taken.append(self._draw_tag(p, self.to_px(*preview.point), preview.label,
                                            preview.color, left, taken))

    def _ring_colors(self, v: Preview, previews) -> List[str]:
        """The ring's own colour, then those of other rings drawn on the same line
        (same centre and radius on screen): those alternate, a b a b."""
        colors = [v.color]
        if v.radius_m <= 0:
            return colors
        x, y = self.to_m(*v.point)
        for other in previews:
            if other is v or other.radius_m <= 0 or other.color in colors:
                continue
            ox, oy = self.to_m(*other.point)
            apart_px = math.hypot(ox - x, oy - y) * self._scale
            radius_px = abs(other.radius_m - v.radius_m) * self._scale
            if apart_px <= SAME_RING_PX and radius_px <= SAME_RING_PX:
                colors.append(other.color)
        return colors

    def _draw_preview(self, p, v: Preview, ring_colors) -> Tuple[bool, Optional[QPointF]]:
        """Draw one preview; returns (its label goes left, its arrow tip or None)."""
        q = self.to_px(*v.point)
        left, tip = False, None
        alpha = 255 if v.active else 110
        color = theme.qcolor(v.color, alpha)
        if v.radius_m > 0:
            r = v.radius_m * self._scale
            width = 1.8 if v.active else 1.2
            p.setBrush(QBrush(theme.qcolor(v.color, 46 if v.active else 18)))
            p.setPen(Qt.NoPen)
            p.drawEllipse(q, r, r)
            p.setBrush(Qt.NoBrush)
            # Same dash and gap as a single ring; overlapping rings take turns by colour
            n = len(ring_colors)
            for i, c in enumerate(ring_colors):
                pen = QPen(theme.qcolor(c, alpha), width, Qt.CustomDashLine)
                pen.setDashPattern([DASH, GAP + (DASH + GAP) * (n - 1)])
                pen.setDashOffset(-i * (DASH + GAP))
                p.setPen(pen)
                p.drawEllipse(q, r, r)
        if v.heading_deg is not None:
            tip = self._draw_heading(p, v, v.heading_deg, color)
            left = tip.x() > q.x()
        p.setPen(QPen(theme.qcolor(theme.BG), 2))
        p.setBrush(QBrush(color))
        p.drawEllipse(q, 5.5, 5.5)
        return left, tip

    def _draw_heading(self, p, v: Preview, heading_deg: float, color) -> QPointF:
        """Heading arrow from the object; returns its tip."""
        x, y = self.to_m(*v.point)
        length = max(v.speed_mps * ARROW_SECONDS, MIN_ARROW_M)
        h = math.radians(heading_deg)
        a = self._m_to_px(x, y)
        b = self._m_to_px(x + length * math.sin(h), y + length * math.cos(h))
        p.setPen(QPen(color, 2.2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(a, b)
        angle = math.atan2(b.y() - a.y(), b.x() - a.x())
        for side in (-1, 1):
            tip = angle + math.pi + side * 0.45
            p.drawLine(b, QPointF(b.x() + 9 * math.cos(tip), b.y() + 9 * math.sin(tip)))
        return b

    def _draw_tag(self, p, q: QPointF, text: str, color: str, left: bool = False,
                  taken=()) -> QRectF:
        """Label below the point (vehicle labels sit above), moved down past ``taken``."""
        font = theme.ui_font(8, 700)
        fm = QFontMetrics(font)
        width = fm.horizontalAdvance(text) + 14
        x = q.x() - 10 - width if left else q.x() + 10
        r = QRectF(x, q.y() + 8, width, 18)
        while any(r.intersects(t) for t in taken):
            r.translate(0, 22)
        p.setPen(QPen(theme.qcolor(color), 1))
        p.setBrush(QBrush(theme.qcolor(theme.SURFACE, 230)))
        p.drawRoundedRect(r, 5, 5)
        p.setFont(font)
        p.setPen(theme.qcolor(theme.TEXT_STRONG))
        p.drawText(r, Qt.AlignCenter, text)
        return r

    def _draw_crosshair(self, p):
        c = QPointF(self.width() / 2, self.height() / 2)
        for width, color in ((4.0, theme.qcolor(theme.MAP_DIM, 170)),
                             (1.6, theme.qcolor(theme.MAP_BOUNDARY))):
            p.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap))
            p.setBrush(Qt.NoBrush)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                p.drawLine(QPointF(c.x() + dx * 4, c.y() + dy * 4),
                           QPointF(c.x() + dx * (4 + CROSSHAIR_PX), c.y() + dy * (4 + CROSSHAIR_PX)))
