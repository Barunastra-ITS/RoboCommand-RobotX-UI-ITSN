"""Map rotation shared by the Map tab and Course tab maps.

``bearing`` is the compass direction (degrees clockwise from north) that
points up on screen; 0 is north-up. Offsets are screen pixels from the
widget centre (x right, y down). Shift+drag turns the map; the compass
button in the top-right corner shows north and turns it back to north-up.
"""

import math
from typing import Tuple

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QBrush, QPainter, QPen, QPolygonF

from robocommand_ui import theme

COMPASS_R = 16              # button radius, px
COMPASS_MARGIN = 12         # from the top-right corner


def rotate(x: float, y: float, bearing: float) -> Tuple[float, float]:
    """North-up screen offset -> offset on the map turned to ``bearing``."""
    b = math.radians(bearing)
    c, s = math.cos(b), math.sin(b)
    return x * c + y * s, -x * s + y * c


def unrotate(x: float, y: float, bearing: float) -> Tuple[float, float]:
    """Offset on the turned map -> north-up screen offset."""
    b = math.radians(bearing)
    c, s = math.cos(b), math.sin(b)
    return x * c - y * s, x * s + y * c


def normalize(bearing: float) -> float:
    return bearing % 360.0


def drag_bearing(bearing: float, center: QPointF, before: QPointF, after: QPointF) -> float:
    """New bearing after dragging from ``before`` to ``after`` around ``center``:
    the map turns with the pointer."""
    a0 = math.atan2(before.y() - center.y(), before.x() - center.x())
    a1 = math.atan2(after.y() - center.y(), after.x() - center.x())
    return normalize(bearing - math.degrees(a1 - a0))


def compass_center(width: float) -> QPointF:
    return QPointF(width - COMPASS_MARGIN - COMPASS_R, COMPASS_MARGIN + COMPASS_R)


def on_compass(pos: QPointF, width: float) -> bool:
    c = compass_center(width)
    return math.hypot(pos.x() - c.x(), pos.y() - c.y()) <= COMPASS_R + 2


def draw_compass(p: QPainter, width: float, bearing: float, hover: bool = False) -> None:
    """Round button with an N and a needle pointing north (red half)."""
    c = compass_center(width)
    p.save()
    p.setPen(QPen(theme.qcolor(theme.ACCENT if hover else theme.BORDER), 1))
    p.setBrush(QBrush(theme.qcolor(theme.SURFACE, 235)))
    p.drawEllipse(c, COMPASS_R, COMPASS_R)
    p.translate(c)
    p.rotate(-bearing)                      # needle follows north on the turned map
    p.setPen(theme.qcolor(theme.FAULT))
    p.setFont(theme.ui_font(7.5, 800))
    p.drawText(QRectF(-8, -15, 16, 11), Qt.AlignCenter, "N")
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(theme.qcolor(theme.FAULT)))
    p.drawPolygon(QPolygonF([QPointF(0, -5), QPointF(-4, 3), QPointF(4, 3)]))
    p.setBrush(QBrush(theme.qcolor(theme.TEXT_FAINT)))
    p.drawPolygon(QPolygonF([QPointF(0, 11), QPointF(-4, 3), QPointF(4, 3)]))
    p.restore()
    if round(bearing) % 360:
        p.setPen(theme.qcolor(theme.TEXT_MUTED))
        p.setFont(theme.mono_font(7.5, 600))
        p.drawText(QRectF(c.x() - 30, c.y() + COMPASS_R + 2, 60, 12), Qt.AlignCenter,
                   f"{bearing:.0f}°")
