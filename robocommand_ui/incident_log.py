"""Task 4 commands this host sent, matched with the team's answers.

Each command the host sends is one entry. IncidentAck and ReadinessReport
quote ``command_seq``, so they are matched to the entry with that seq.
A ReadinessReport carries its own RxReport.seq, which ReadinessConfirm must
quote back: the log keeps it so the Task 4 tab can fill it in. Qt-free.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

ACKED_KINDS = ("assistance_request", "keep_out_zone", "all_clear")


@dataclass
class Incident:
    team_id: str
    seq: int
    kind: str
    summary: str
    sent_at: float
    acked_by: List[str] = field(default_factory=list)
    readiness: Optional[Tuple[str, int]] = None     # (vehicle_id, RxReport.seq)
    confirmed: bool = False

    @property
    def status(self) -> str:
        if self.kind not in ACKED_KINDS:
            return "SENT"
        if not self.acked_by:
            return "WAITING ACK"
        if self.kind != "assistance_request":
            return f"ACKED {', '.join(self.acked_by)}"
        if self.confirmed:
            return "CONFIRMED"
        if self.readiness:
            vehicle, report_seq = self.readiness
            return f"READY {vehicle} R={report_seq}"
        return f"ACKED {', '.join(self.acked_by)} · EN ROUTE"


class IncidentLog:
    def __init__(self):
        self._entries: Dict[Tuple[str, int], Incident] = {}

    def entries(self, team_id: Optional[str] = None) -> List[Incident]:
        found = [e for e in self._entries.values() if team_id in (None, e.team_id)]
        return sorted(found, key=lambda e: e.sent_at, reverse=True)

    def record(self, team_id: str, seq: int, kind: str, summary: str,
               now: Optional[float] = None) -> Incident:
        entry = Incident(team_id, seq, kind, summary, time.time() if now is None else now)
        self._entries[(team_id, seq)] = entry
        return entry

    def on_report(self, team_id: str, vehicle_id: str, report) -> Optional[str]:
        """Match an IncidentAck / ReadinessReport; returns a log line, or None."""
        body = report.WhichOneof("body")
        if body not in ("incident_ack", "readiness"):
            return None
        command_seq = getattr(report, body).command_seq
        entry = self._entries.get((team_id, command_seq))
        label = "IncidentAck" if body == "incident_ack" else "ReadinessReport"
        if entry is None:
            return (f"[WARN] {team_id}/{vehicle_id} {label} for command seq={command_seq}, "
                    f"which this console did not send")
        if body == "incident_ack":
            if vehicle_id not in entry.acked_by:
                entry.acked_by.append(vehicle_id)
            return f"[Task4] {team_id}/{vehicle_id} acked seq={command_seq} {entry.kind}"
        entry.readiness = (vehicle_id, report.seq)
        return (f"[Task4] {team_id}/{vehicle_id} ready for seq={command_seq} "
                f"(report seq R={report.seq}); send Readiness confirm")

    def pending_readiness(self, team_id: str) -> Optional[Incident]:
        """Newest assistance request that reported ready but is not confirmed yet."""
        for entry in self.entries(team_id):
            if entry.readiness and not entry.confirmed:
                return entry
        return None

    def clear_team(self, team_id: str) -> None:
        """Forget a team's commands (its run ended; the next run starts clean)."""
        self._entries = {k: e for k, e in self._entries.items() if e.team_id != team_id}

    def mark_confirmed(self, team_id: str, vehicle_id: str, report_seq: int) -> None:
        for entry in self.entries(team_id):
            if entry.readiness == (vehicle_id, report_seq):
                entry.confirmed = True
