"""Finished runs and their replays, read back from ``run_log`` files.

``list_runs`` finds every ``.json`` replay in the run log directory (newest
first); ``load_run`` reads one, and ``RunReplay.frame(t)`` gives what the map
showed ``t`` seconds after RunStart: each vehicle's position, heading and
trail so far, and the latest Task 1 / Task 2 overlays. Qt-free.
"""

import bisect
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from robocommand_ui.fleet_state import STALE_SECONDS
from robocommand_ui.run_log import default_dir

LatLng = Tuple[float, float]


@dataclass(frozen=True)
class RunSummary:
    team_id: str
    run_id: int
    started_at: float
    ended_at: float
    reason: str
    replay_path: Path
    log_path: Path

    @property
    def duration(self) -> float:
        return self.ended_at - self.started_at


@dataclass(frozen=True)
class VehicleFrame:
    vehicle_type: int
    lat: float
    lng: float
    heading: float
    state: int
    trail: List[LatLng]
    stale: bool


@dataclass(frozen=True)
class Frame:
    vehicles: Dict[str, VehicleFrame]
    safe_passage: Optional[tuple]
    pipeline: Optional[tuple]


@dataclass
class _Track:
    times: List[float] = field(default_factory=list)
    rows: List[list] = field(default_factory=list)


def _latlng(p) -> LatLng:
    return (float(p[0]), float(p[1]))


def _task_data(kind: str, data):
    """JSON lists back to the tuples FleetState uses."""
    if kind == "safe_passage":
        entry, exit_pos, buoys = data
        return (_latlng(entry), _latlng(exit_pos), [(b[0], b[1], int(b[2])) for b in buoys])
    if kind == "pipeline":
        active, segments = data
        return (_latlng(active), [int(s) for s in segments])
    return None


class RunReplay:
    def __init__(self, raw: dict):
        self.team_id: str = raw["team_id"]
        self.run_id: int = int(raw["run_id"])
        self.started_at: float = float(raw["started_at"])
        self.duration: float = float(raw["ended_at"]) - self.started_at
        self.course_id: str = raw.get("course_id", "")
        self.course: List[LatLng] = [_latlng(p) for p in raw.get("course", [])]
        self.geofence: List[LatLng] = [_latlng(p) for p in raw.get("geofence", [])]
        self._tracks: Dict[str, _Track] = {}
        for row in raw.get("samples", []):
            track = self._tracks.setdefault(row[1], _Track())
            track.times.append(float(row[0]))
            track.rows.append(row)
        self._tasks: Dict[str, Tuple[List[float], list]] = {}
        for t, kind, data in raw.get("tasks", []):
            times, values = self._tasks.setdefault(kind, ([], []))
            times.append(float(t))
            values.append(_task_data(kind, data))

    @property
    def vehicle_ids(self) -> List[str]:
        return sorted(self._tracks)

    def frame(self, t: float) -> Frame:
        vehicles = {}
        for vid, track in self._tracks.items():
            n = bisect.bisect_right(track.times, t)
            if n == 0:
                continue
            _, _, vtype, lat, lng, heading, state = track.rows[n - 1]
            vehicles[vid] = VehicleFrame(
                vtype, lat, lng, heading, state,
                [(r[3], r[4]) for r in track.rows[:n]],
                t - track.times[n - 1] > STALE_SECONDS)
        return Frame(vehicles, self._latest("safe_passage", t), self._latest("pipeline", t))

    def _latest(self, kind: str, t: float):
        times, values = self._tasks.get(kind, ([], []))
        n = bisect.bisect_right(times, t)
        return values[n - 1] if n else None


def load_run(path: Path) -> RunReplay:
    return RunReplay(json.loads(Path(path).read_text()))


def list_runs(directory: Optional[Path] = None) -> List[RunSummary]:
    """Finished runs with a replay, newest first; unreadable files are skipped."""
    directory = Path(directory) if directory else default_dir()
    if not directory.is_dir():
        return []
    runs = []
    for path in directory.glob("*.json"):
        try:
            raw = json.loads(path.read_text())
            runs.append(RunSummary(
                raw["team_id"], int(raw["run_id"]), float(raw["started_at"]),
                float(raw["ended_at"]), raw.get("reason", ""), path,
                path.with_name(raw.get("log_file", path.with_suffix(".log").name))))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(runs, key=lambda r: r.started_at, reverse=True)
