"""Per-run log files, closed when the host ends a run.

The handbook (§3.4) has no run-end message: RoboCommand decides when a run
is over. The console records every log line from a team's RunStart until the
host presses **End run** (or the team declares a new run), then writes them,
with a summary, to ``~/.local/share/robocommand_ui/runs/`` (override with
``$ROBOCOMMAND_RUN_LOG_DIR``). Qt-free.
"""

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence


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


class RunRecorder:
    def __init__(self, directory: Optional[Path] = None):
        self.directory = Path(directory) if directory else default_dir()
        self._runs: Dict[str, _Run] = {}

    def is_active(self, team_id: str) -> bool:
        return team_id in self._runs

    def active_teams(self) -> List[str]:
        return sorted(self._runs)

    def begin(self, team_id: str, run_id: int, declaration_seq: Optional[int],
              now: Optional[float] = None) -> None:
        self._runs[team_id] = _Run(team_id, run_id, declaration_seq,
                                   time.time() if now is None else now)

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
        return path
