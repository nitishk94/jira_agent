from __future__ import annotations

from pathlib import Path

from jira_agent.config import Settings
from jira_agent.logging_store.run_log import RunLog, RunLogStore
from jira_agent.models import AttemptResult, Ticket, TriageResult


def _ticket() -> Ticket:
    return Ticket(
        id="TICKET-123",
        project_key="ENG",
        issue_type="Bug",
        summary="Null pointer on checkout when cart is empty",
        description="d",
        url="https://example.atlassian.net/browse/TICKET-123",
    )


def test_render_header_and_section_match_template_shape() -> None:
    log = RunLog(ticket=_ticket())
    log.record_triage(
        TriageResult(is_bug=True, issue_type_matched=True, repro_clear=True, reasoning="Repro steps were clear.")
    )
    log.record_reproduction("Wrote test_checkout_empty_cart.py — confirmed failing against current main.")
    log.record_code_navigation("Located checkout/service.py, checkout/validators.py as the relevant region.")
    log.record_attempt(AttemptResult(attempt_number=1, passed=False, notes="Fix addressed wrong validator"))
    log.record_attempt(AttemptResult(attempt_number=2, passed=True, notes="Added empty-cart guard, suite passes"))
    log.finish(
        outcome_line="PR opened → `fix/TICKET-123` → [PR link](https://github.com/x/pull/1)",
        jira_status_line="→ In Review",
    )

    header = log.render_header()
    assert header.startswith("# TICKET-123 — Null pointer on checkout")
    assert "**Type:** Bug" in header

    section = log.render_section(run_number=1)
    assert "## Run 1 —" in section
    assert "**Classification:** Bug, Jira Issue Type matched, repro steps present." in section
    assert "| 1 | Fail | Fix addressed wrong validator |" in section
    assert "| 2 | Pass | Added empty-cart guard, suite passes |" in section
    assert "**Outcome:** PR opened" in section
    assert "**Jira status:** → In Review" in section


def test_store_appends_new_run_section_on_reprocessing(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, run_log_local_dir=str(tmp_path))
    store = RunLogStore(settings)
    ticket = _ticket()

    log1 = RunLog(ticket=ticket)
    log1.record_triage(TriageResult(is_bug=True, issue_type_matched=True, repro_clear=True, reasoning="r1"))
    log1.finish(outcome_line="Escalated after 3 failed attempts.", jira_status_line="unchanged")
    path1 = store.write(log1)

    log2 = RunLog(ticket=ticket)
    log2.record_triage(TriageResult(is_bug=True, issue_type_matched=True, repro_clear=True, reasoning="r2"))
    log2.finish(outcome_line="PR opened", jira_status_line="→ In Review")
    path2 = store.write(log2)

    assert path1 == path2  # same file, appended
    content = (tmp_path / "TICKET-123.md").read_text(encoding="utf-8")
    assert content.count("## Run ") == 2
    assert "## Run 1" in content and "## Run 2" in content
    assert content.startswith("# TICKET-123")
