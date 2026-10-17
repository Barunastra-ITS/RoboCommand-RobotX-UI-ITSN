"""Per-run log files, closed when the host ends a run.

The handbook (§3.4) has no run-end message: RoboCommand decides when a run
is over. The console records every log line from a team's RunStart until the
host presses **End run** (or the team declares a new run), then writes them,
with a summary, to ``~/.local/share/robocommand_ui/runs/`` (override with
``$ROBOCOMMAND_RUN_LOG_DIR``).

Next to each ``.log`` a ``.json`` replay is written: the course, the declared
UAV geofence, every heartbeat position and the Task 1 / Task 2 overlays, with
times relative to RunStart (read back by ``run_replay``). Qt-free.
"""

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

LatLng = Tuple[float, float]
REPLAY_VERSION = 1
COORD_DECIMALS = 7          # ~1 cm


def default_dir() -> Path:
    override = os.environ.get("ROBOCOMMAND_RUN_LOG_DIR")
    if override:
        return Path(override)
    return Path.home() / ".local" / "share" / "robocommand_ui" / "runs"


def format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m{seconds % 60:02d}s"


def _stamp(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


@dataclass
class _Run:
    team_id: str
    run_id: int
    declaration_seq: Optional[int]
    started_at: float
    lines: List[str] = field(default_factory=list)
    course: List[LatLng] = field(default_factory=list)
    course_id: str = ""
    geofence: List[LatLng] = field(default_factory=list)
    samples: List[list] = field(default_factory=list)   # [t, vehicle, type, lat, lng, heading, state]
    tasks: List[list] = field(default_factory=list)     # [t, kind, data]

    def rel(self, now: Optional[float]) -> float:
        return round((time.time() if now is None else now) - self.started_at, 3)


def _points(points) -> List[List[float]]:
    return [[round(a, COORD_DECIMALS), round(b, COORD_DECIMALS)] for a, b in points]


class RunRecorder:
    def __init__(self, directory: Optional[Path] = None):
        self.directory = Path(directory) if directory else default_dir()
        self._runs: Dict[str, _Run] = {}

    def is_active(self, team_id: str) -> bool:
        return team_id in self._runs

    def active_teams(self) -> List[str]:
        return sorted(self._runs)

    def begin(self, team_id: str, run_id: int, declaration_seq: Optional[int],
              now: Optional[float] = None, course: Optional[Tuple[list, str]] = None,
              geofence: Sequence[LatLng] = ()) -> None:
        run = _Run(team_id, run_id, declaration_seq, time.time() if now is None else now,
                   geofence=_points(geofence))
        if course is not None:
            run.course, run.course_id = _points(course[0]), course[1]
        self._runs[team_id] = run

    def set_course(self, ring: Sequence[LatLng], course_id: str) -> None:
        """The course changed mid-run: replays show the latest one."""
        for run in self._runs.values():
            run.course, run.course_id = _points(ring), course_id

    def track(self, team_id: str, vehicle_id: str, hb, now: Optional[float] = None) -> None:
        """An accepted heartbeat of a team in a run (ignored without a position)."""
        run = self._runs.get(team_id)
        if run is None or not hb.HasField("position"):
            return
        run.samples.append([run.rel(now), vehicle_id, int(hb.vehicle_type),
                            round(hb.position.latitude, COORD_DECIMALS),
                            round(hb.position.longitude, COORD_DECIMALS),
                            round(hb.heading_deg, 1), int(hb.state)])

    def task(self, team_id: str, kind: str, data, now: Optional[float] = None) -> None:
        """Latest Task 1 ("safe_passage") / Task 2 ("pipeline") overlay, as FleetState keeps it."""
        run = self._runs.get(team_id)
        if run is not None and data is not None:
            run.tasks.append([run.rel(now), kind, data])

    def note(self, line: str) -> None:
        """A log line; kept by every run in progress (one team per course)."""
        for run in self._runs.values():
            run.lines.append(line)

    def finish(self, team_id: str, reason: str, summary: Sequence[str],
               now: Optional[float] = None) -> Optional[Path]:
        """Write the team's run log and close it. None when no run was recorded."""
        run = self._runs.pop(team_id, None)
        if run is None:
            return None
        ended = time.time() if now is None else now
        header = [
            f"RoboCommand run log — team {run.team_id}, run_id {run.run_id}",
            f"declaration seq {run.declaration_seq if run.declaration_seq is not None else '—'}",
            f"started  {_stamp(run.started_at)}",
            f"ended    {_stamp(ended)}  ({reason})",
            f"duration {format_duration(ended - run.started_at)}",
            "",
        ]
        body = ["== Summary =="] + list(summary) + ["", "== Log =="] + run.lines
        self.directory.mkdir(parents=True, exist_ok=True)
        name = (f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(run.started_at))}"
                f"_{run.team_id}_run{run.run_id}.log")
        path = self.directory / name
        path.write_text("\n".join(header + body) + "\n")
        self._write_replay(run, ended, reason, path)
        return path

    @staticmethod
    def _write_replay(run: _Run, ended: float, reason: str, log_path: Path) -> None:
        replay = {
            "version": REPLAY_VERSION,
            "team_id": run.team_id,
            "run_id": run.run_id,
            "declaration_seq": run.declaration_seq,
            "started_at": run.started_at,
            "ended_at": ended,
            "reason": reason,
            "log_file": log_path.name,
            "course_id": run.course_id,
            "course": run.course,
            "geofence": run.geofence,
            "samples": run.samples,
            "tasks": run.tasks,
        }
        log_path.with_suffix(".json").write_text(json.dumps(replay, separators=(",", ":")))
