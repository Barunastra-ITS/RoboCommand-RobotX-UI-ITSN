"""Tracks sequence numbers per handbook §3.4.8:
- RxRequest.seq: monotonically increasing team-request sequence.
- RxCommand.seq: maintained by RoboCommand for the addressed team.
- RxReport.seq: scoped per vehicle; each represented vehicle has its own increasing sequence counter.
"""

from typing import Dict


class SequenceTracker:
    def __init__(self):
        self._request_seq: int = 0
        self._last_rx_command_seq: int = 0
        self._vehicle_report_seqs: Dict[str, int] = {}

    def get_next_request_seq(self) -> int:
        self._request_seq += 1
        return self._request_seq

    def get_next_report_seq(self, vehicle_id: str) -> int:
        vid = vehicle_id.strip() or "UNKNOWN"
        self._vehicle_report_seqs[vid] = self._vehicle_report_seqs.get(vid, 0) + 1
        return self._vehicle_report_seqs[vid]

    def record_rx_command_seq(self, seq: int) -> None:
        if seq > self._last_rx_command_seq:
            self._last_rx_command_seq = seq

    def get_last_rx_command_seq(self) -> int:
        return self._last_rx_command_seq

    def get_report_seq(self, vehicle_id: str) -> int:
        return self._vehicle_report_seqs.get(vehicle_id.strip(), 0)

    def get_request_seq(self) -> int:
        return self._request_seq

    def reset(self) -> None:
        self._request_seq = 0
        self._last_rx_command_seq = 0
        self._vehicle_report_seqs.clear()

    def get_all_vehicle_seqs(self) -> Dict[str, int]:
        return dict(self._vehicle_report_seqs)
