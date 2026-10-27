"""UAV geofence check of a RunDeclaration, as RoboCommand does it. Qt-free.

Ported from the upstream test server (robocommand ``rc_test/test_server.py``,
2026-10-23): a declaration with a UAV is refused unless its ``uav_geofence``
is a closed ring of at least 4 points, every point along its edges lies
within the RxCourse corners or its ``uav_transit_area`` (to within
GEOFENCE_TOLERANCE_M), and ``uav_geofence_max_altitude_hae_m`` is above 0 and
at most MAX_UAV_ALTITUDE_HAE_M. RoboCommand sends nothing back for a refused
declaration: the run just never starts.
"""

import math
from typing import List, Optional, Sequence, Tuple

LatLng = Tuple[float, float]
XY = Tuple[float, float]

MAX_UAV_ALTITUDE_HAE_M = 50.0     # meters above the WGS84 ellipsoid
GEOFENCE_TOLERANCE_M = 1.0        # rounding between surveys
EDGE_STEP_M = 0.5                 # how finely the geofence edges are checked
MIN_GEOFENCE_POINTS = 4
EARTH_RADIUS_M = 6371000.0


def is_uav(vehicle_id: str, vehicle_type_name: str = "") -> bool:
    """RoboCommand treats a vehicle ID starting with UAV as a UAV."""
    return vehicle_id.upper().startswith("UAV") or vehicle_type_name == "UAV"


def _xy(p: LatLng, origin: LatLng) -> XY:
    """(lat, lng) as local east/north meters around origin."""
    return (
        math.radians(p[1] - origin[1]) * EARTH_RADIUS_M * math.cos(math.radians(origin[0])),
        math.radians(p[0] - origin[0]) * EARTH_RADIUS_M,
    )


def _inside(p: XY, ring: Sequence[XY]) -> bool:
    x, y = p
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _outside_by(p: XY, ring: Sequence[XY]) -> float:
    """0 inside the ring, else meters to its nearest edge."""
    if _inside(p, ring):
        return 0.0
    best = math.inf
    for (ax, ay), (bx, by) in zip(ring, ring[1:]):
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / length2))
        best = min(best, math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy)))
    return best


def _points(ring: Sequence[LatLng]) -> List[LatLng]:
    return [(float(p[0]), float(p[1])) for p in ring]


def _closed(ring: Sequence[LatLng]) -> List[LatLng]:
    points = _points(ring)
    if points and points[0] != points[-1]:
        points.append(points[0])
    return points


def geofence_problems(fence: Sequence[LatLng], ceiling_hae_m: float,
                      corners: Sequence[LatLng], transit: Sequence[LatLng] = (),
                      max_altitude_hae_m: float = MAX_UAV_ALTITUDE_HAE_M) -> List[str]:
    """Why RoboCommand would refuse this UAV geofence (empty: it's fine).

    ``corners`` and ``transit`` are the RxCourse rings; without corners (no
    course yet) only the ring shape and ceiling can be checked.
    """
    points = _points(fence)
    problems = []
    if len(points) < MIN_GEOFENCE_POINTS:
        problems.append(f"uav_geofence has {len(points)} point(s), needs at least "
                        f"{MIN_GEOFENCE_POINTS}")
    elif points[0] != points[-1]:
        problems.append("uav_geofence isn't closed: its first and last points must be the same")
    elif len(corners) >= 3:
        worst, where = _worst_excursion(points, corners, transit)
        if worst > GEOFENCE_TOLERANCE_M:
            problems.append(f"uav_geofence leaves the course and transit area by "
                            f"{worst:.1f} m at {where}")
    if not 0 < ceiling_hae_m <= max_altitude_hae_m:
        problems.append(f"uav_geofence_max_altitude_hae_m is {ceiling_hae_m:g}: it must be "
                        f"above 0 and at most {max_altitude_hae_m:g}")
    return problems


def _worst_excursion(fence: Sequence[LatLng], corners: Sequence[LatLng],
                     transit: Sequence[LatLng]) -> Tuple[float, Optional[str]]:
    """Largest distance (m) of any point along the fence edges outside every area."""
    origin = corners[0]
    areas = [[_xy(p, origin) for p in _closed(ring)]
             for ring in (corners, transit) if len(ring) >= 3]
    pts = [_xy(p, origin) for p in fence]
    worst, where = 0.0, None
    for i, (a, b) in enumerate(zip(pts, pts[1:])):
        steps = max(1, math.ceil(math.dist(a, b) / EDGE_STEP_M))
        for k in range(steps + 1):
            q = (a[0] + (b[0] - a[0]) * k / steps, a[1] + (b[1] - a[1]) * k / steps)
            out = min(_outside_by(q, area) for area in areas)
            if out > worst:
                worst = out
                where = (f"point {i + 1}" if k == 0 else f"point {i + 2}" if k == steps
                         else f"edge {i + 1}-{i + 2}")
    return worst, where
