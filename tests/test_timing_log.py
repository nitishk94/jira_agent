from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from jira_agent.logging_store.timing_log import TimingLog


def test_record_start_and_end_appends_readable_lines(tmp_path: Path) -> None:
    log = TimingLog(str(tmp_path))

    start = log.record_start("ENG-1")
    assert isinstance(start, datetime)

    # Use a synthetic start further in the past so duration is deterministic
    # and doesn't depend on real elapsed wall-clock time in the test.
    synthetic_start = start - timedelta(minutes=5)
    log.record_end("ENG-1", synthetic_start, "pr_opened")

    lines = (tmp_path / "timing.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert "ENG-1 | started" in lines[0]
    assert "ENG-1 | finished in 0:05:0" in lines[1]
    assert "outcome=pr_opened" in lines[1]
