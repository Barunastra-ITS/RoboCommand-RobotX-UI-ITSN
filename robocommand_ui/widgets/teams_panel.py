"""Per-team run status as seen by the RoboCommand host.

One row per team on the broker: run state (IDLE / DECLARED / ACTIVE / DECL
MISMATCH), live vs declared vehicles, task tiers and run_id. The declaration
seq and latest request/command seqs are in each row's tooltip.
"""

import time
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QAbstractItemView, QHeaderView, QLabel, QTableWidget, QTableWidgetItem

from robocommand_ui import theme
from robocommand_ui.fleet_state import STALE_SECONDS, FleetState
from robocommand_ui.proto_helper import task_tier_name
from robocommand_ui.widgets.panel import Panel

def format_age(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"


RUN_COLORS = {
    "IDLE": theme.IDLE,
    "DECLARED": theme.WARN,
    "ACTIVE": theme.OK,
    "DECL MISMATCH": theme.FAULT,
}
COLUMNS = ["Team", "Run", "Live", "Tiers", "Run ID"]
TIER_SHORT = {"NONE": "–", "CORE": "C", "ADVANCED": "A", "DISRUPTIVE": "D", "UNKNOWN": "?"}


class TeamsPanel(Panel):
    def __init__(self, parent=None):
        super().__init__("Teams", parent)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        for col in (0, 1, 2):               # team, run state and link keep their full text
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setShowGrid(False)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setToolTip("Tiers T1–T4: C core · A advanced · D disruptive · – not attempted")
        self.body.addWidget(self.table)
        self._empty = QLabel("No team traffic yet.")
        self._empty.setObjectName("Empty")
        self._empty.setAlignment(Qt.AlignCenter)
        self.body.addWidget(self._empty)
        self._fit_height(0)

    def _fit_height(self, rows: int) -> None:
        self.table.setVisible(rows > 0)
        self._empty.setVisible(rows == 0)
        header_h = self.table.horizontalHeader().sizeHint().height()
        self.table.setFixedHeight(header_h + rows * 30 + 4)

    def refresh(self, fleet: FleetState, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        team_ids = fleet.team_ids()
        self.table.setRowCount(len(team_ids))
        for row, tid in enumerate(team_ids):
            team = fleet.teams[tid]
            tracks = fleet.vehicles_of(tid)
            live = sum(1 for v in tracks
                       if v.age(now) is not None and v.age(now) <= STALE_SECONDS)
            declared = len(team.declared_vehicles)
            tiers = (" ".join(TIER_SHORT.get(task_tier_name(t), "?") for t in team.tiers)
                     if team.declaration_seq else "—")
            link, link_age = fleet.team_link(tid, now)
            live_text = f"{live}/{declared}" if declared else f"{live}/-"
            if link == "LOST":
                live_text = f"LOST {format_age(link_age)}"
            elif link == "NO HEARTBEAT" and link_age > STALE_SECONDS:
                live_text = f"NO HB {format_age(link_age)}"
            else:
                link = "UP" if link == "UP" else "WAIT"
            values = [
                tid,
                team.run_state,
                live_text,
                tiers,
                "—" if team.run_id is None else str(team.run_id),
            ]
            decl = "—" if team.declaration_seq is None else team.declaration_seq
            tip = (f"Declaration seq {decl}\n"
                   f"Vehicles declared: {', '.join(team.declared_vehicles) or '—'}\n"
                   f"Last request seq {team.last_request_seq} · last command seq {team.last_command_seq}")
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setFont(theme.ui_font(10, 700) if col in (0, 1) else theme.mono_font(9.5))
                if col == 1:
                    item.setForeground(theme.qcolor(RUN_COLORS.get(text, theme.TEXT)))
                elif col == 2 and link in ("LOST", "NO HEARTBEAT"):
                    item.setForeground(theme.qcolor(theme.FAULT))
                elif col == 2 and declared and live < declared:
                    item.setForeground(theme.qcolor(theme.WARN))
                item.setToolTip(tip)
                self.table.setItem(row, col, item)
            self.table.setRowHeight(row, 30)
        self._fit_height(len(team_ids))
        self.set_meta(f"{len(team_ids)}" if team_ids else "")

    def row_text(self, team_id: str) -> Optional[list]:
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).text() == team_id:
                return [self.table.item(row, c).text() for c in range(self.table.columnCount())]
        return None
