"""Saved RxCourse parameters, so the Course tab needs no typing each session.

Built-in presets ship with the app; the operator's own are stored as JSON in
``~/.config/robocommand_ui/course_presets.json`` (override the path with
``$ROBOCOMMAND_PRESETS``)::

    {"presets": [{"name": "Lake bench", "course_id": "ALPHA",
                  "pinger_freq_hz": 25000,
                  "corners": [[-7.261, 112.791], [-7.261, 112.795], ...]}]}

A saved preset with a built-in's name replaces that built-in. Qt-free.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

LatLng = Tuple[float, float]


@dataclass(frozen=True)
class CoursePreset:
    name: str
    course_id: str
    pinger_freq_hz: int
    corners: Tuple[LatLng, ...]
    builtin: bool = False

    def to_json(self) -> dict:
        return {"name": self.name, "course_id": self.course_id,
                "pinger_freq_hz": self.pinger_freq_hz,
                "corners": [list(c) for c in self.corners]}

    @staticmethod
    def from_json(data: dict) -> "CoursePreset":
        corners = tuple((float(lat), float(lng)) for lat, lng in data["corners"])
        return CoursePreset(str(data["name"]), str(data["course_id"]),
                            int(data["pinger_freq_hz"]), corners)


BUILTIN_PRESETS = (
    CoursePreset("Danau 8", "ALPHA", 25000,
                 ((-7.286118, 112.7956025), (-7.2860113, 112.7963514), (-7.2875014, 112.7965795),
                  (-7.2876252, 112.795822), (-7.286118, 112.7956025)), builtin=True),
    CoursePreset("Promontory SG", "ALPHA", 25000,
                 ((1.280329, 103.8556869), (1.2804716, 103.8554529), (1.2808993, 103.8557337),
                  (1.2807567, 103.8559743), (1.280329, 103.8556869)), builtin=True),
)


def default_path() -> Path:
    override = os.environ.get("ROBOCOMMAND_PRESETS")
    if override:
        return Path(override)
    return Path.home() / ".config" / "robocommand_ui" / "course_presets.json"


def load_user_presets(path: Path) -> List[CoursePreset]:
    """Presets saved by the operator. Raises ValueError on a corrupt file."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return [CoursePreset.from_json(p) for p in data.get("presets", [])]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ValueError(f"cannot read course presets from {path}: {e}") from e


def merged(user: List[CoursePreset]) -> Dict[str, CoursePreset]:
    """Built-ins first, then the operator's presets (which win on a name clash)."""
    presets = {p.name: p for p in BUILTIN_PRESETS}
    presets.update({p.name: p for p in user})
    return presets


def _write(path: Path, user: List[CoursePreset]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"presets": [p.to_json() for p in user]}, indent=2))
    tmp.replace(path)


def save_preset(path: Path, preset: CoursePreset) -> List[CoursePreset]:
    """Add or replace a user preset by name; returns the new user list."""
    user = [p for p in load_user_presets(path) if p.name != preset.name]
    user.append(CoursePreset(preset.name, preset.course_id, preset.pinger_freq_hz,
                             tuple(preset.corners)))
    _write(path, user)
    return user


def delete_preset(path: Path, name: str) -> List[CoursePreset]:
    user = [p for p in load_user_presets(path) if p.name != name]
    _write(path, user)
    return user
