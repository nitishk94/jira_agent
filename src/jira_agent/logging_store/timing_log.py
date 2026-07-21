from __future__ import annotations

from datetime import datetime
from pathlib import Path


class TimingLog:
    """One central, append-only log of how long each ticket run takes —
    a `started` line immediately (so an in-progress run's elapsed time can
    be read off by hand) and a `finished`/`crashed` line with the duration
    once it's done. Uses the local system clock, not UTC, since this is for
    a human watching the console, not an audit trail (see run_log.py /
    mcp_call_log.py for those, which stay UTC).
    """

    def __init__(self, local_dir: str) -> None:
        self._path = Path(local_dir) / "timing.log"

    def record_start(self, ticket_id: str) -> datetime:
        start = datetime.now()
        self._append(f"{start:%Y-%m-%d %H:%M:%S} | {ticket_id} | started")
        return start

    def record_end(self, ticket_id: str, start: datetime, outcome: str) -> None:
        end = datetime.now()
        duration = end - start
        self._append(
            f"{end:%Y-%m-%d %H:%M:%S} | {ticket_id} | finished in {duration} | outcome={outcome}"
        )

    def _append(self, line: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
