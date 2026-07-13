from __future__ import annotations

from pathlib import Path

import jira_agent.orchestrator as orchestrator_module
from jira_agent.clients.github_client import MockGitHubClient
from jira_agent.clients.jira_client import MockJiraClient
from jira_agent.config import Settings
from jira_agent.execution.docker_runner import ExecResult
from jira_agent.logging_store.run_log import RunLogStore
from jira_agent.models import AttemptResult, ProjectConfig, Ticket, TriageResult


class _FakeContainer:
    def __enter__(self) -> "_FakeContainer":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def exec(self, command: str, workdir: str | None = None) -> ExecResult:
        return ExecResult(exit_code=0, output="")


def _project() -> ProjectConfig:
    return ProjectConfig(jira_project_key="ENG", github_repo="org/repo", default_branch="main")


def _ticket() -> Ticket:
    return Ticket(id="ENG-1", project_key="ENG", issue_type="Bug", summary="s", description="d")


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(_env_file=None, run_log_local_dir=str(tmp_path), max_fix_attempts=2, **overrides)


def _make_triage_fake(result: TriageResult):
    async def _fake(ticket: Ticket, settings: Settings) -> TriageResult:
        return result

    return _fake


async def test_non_bug_ticket_is_comment_only(tmp_path: Path, monkeypatch) -> None:
    triage_result = TriageResult(
        is_bug=False, issue_type_matched=False, repro_clear=False, reasoning="Reads like a feature request."
    )
    monkeypatch.setattr(orchestrator_module, "run_triage", _make_triage_fake(triage_result))

    async def _unexpected_fix_attempt(*args: object, **kwargs: object) -> None:
        raise AssertionError("fix loop should not run for non-bug tickets")

    monkeypatch.setattr(orchestrator_module, "run_fix_attempt", _unexpected_fix_attempt)

    settings = _settings(tmp_path)
    jira_client = MockJiraClient()
    github_client = MockGitHubClient()
    run_log_store = RunLogStore(settings)

    await orchestrator_module.process_ticket(
        _ticket(), _project(), settings, jira_client, github_client, run_log_store, tmp_path
    )

    assert jira_client.comments["ENG-1"] == ["Reads like a feature request."]
    assert "ENG-1" not in jira_client.statuses


async def test_bug_with_clear_repro_and_passing_fix_opens_pr(tmp_path: Path, monkeypatch) -> None:
    triage_result = TriageResult(is_bug=True, issue_type_matched=True, repro_clear=True, reasoning="Clear repro.")
    monkeypatch.setattr(orchestrator_module, "run_triage", _make_triage_fake(triage_result))
    monkeypatch.setattr(orchestrator_module, "DockerTicketContainer", lambda mirror_path, branch, image_tag: _FakeContainer())

    calls = []

    async def _fake_run_fix_attempt(
        container, settings, ticket, triage, attempt_number, max_attempts, prior_notes
    ) -> AttemptResult:
        calls.append(attempt_number)
        return AttemptResult(attempt_number=attempt_number, passed=True, notes="fixed it")

    monkeypatch.setattr(orchestrator_module, "run_fix_attempt", _fake_run_fix_attempt)

    settings = _settings(tmp_path)
    jira_client = MockJiraClient()
    github_client = MockGitHubClient()
    run_log_store = RunLogStore(settings)

    await orchestrator_module.process_ticket(
        _ticket(), _project(), settings, jira_client, github_client, run_log_store, tmp_path
    )

    assert calls == [1]
    assert jira_client.statuses["ENG-1"] == "In Review"
    assert len(github_client.prs) == 1
    assert "Fix proposed" in jira_client.comments["ENG-1"][0]


async def test_bug_with_all_attempts_failing_escalates(tmp_path: Path, monkeypatch) -> None:
    triage_result = TriageResult(is_bug=True, issue_type_matched=True, repro_clear=True, reasoning="Clear repro.")
    monkeypatch.setattr(orchestrator_module, "run_triage", _make_triage_fake(triage_result))
    monkeypatch.setattr(orchestrator_module, "DockerTicketContainer", lambda mirror_path, branch, image_tag: _FakeContainer())

    calls = []

    async def _fake_run_fix_attempt(
        container, settings, ticket, triage, attempt_number, max_attempts, prior_notes
    ) -> AttemptResult:
        calls.append(attempt_number)
        return AttemptResult(attempt_number=attempt_number, passed=False, notes=f"attempt {attempt_number} failed")

    monkeypatch.setattr(orchestrator_module, "run_fix_attempt", _fake_run_fix_attempt)

    settings = _settings(tmp_path)  # max_fix_attempts=2
    jira_client = MockJiraClient()
    github_client = MockGitHubClient()
    run_log_store = RunLogStore(settings)

    await orchestrator_module.process_ticket(
        _ticket(), _project(), settings, jira_client, github_client, run_log_store, tmp_path
    )

    assert calls == [1, 2]
    assert "ENG-1" not in jira_client.statuses
    assert github_client.prs == []
    assert "Automated fix attempt failed after 2 tries" in jira_client.comments["ENG-1"][0]


async def test_run_once_skips_ticket_unchanged_since_last_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator_module, "ensure_mirror", lambda repo_url, repo, mirror_dir: tmp_path
    )
    triage_result = TriageResult(
        is_bug=False, issue_type_matched=False, repro_clear=False, reasoning="not a bug"
    )
    monkeypatch.setattr(orchestrator_module, "run_triage", _make_triage_fake(triage_result))

    settings = _settings(tmp_path)
    jira_client = MockJiraClient(tickets=[_ticket()])
    github_client = MockGitHubClient()
    run_log_store = RunLogStore(settings)

    await orchestrator_module.run_once(
        settings, jira_client, github_client, run_log_store, projects=[_project()]
    )
    assert jira_client.comments["ENG-1"] == ["not a bug"]

    # Ticket hasn't changed since the run above -> must not be reprocessed.
    jira_client.comments["ENG-1"].clear()
    await orchestrator_module.run_once(
        settings, jira_client, github_client, run_log_store, projects=[_project()]
    )
    assert jira_client.comments["ENG-1"] == []
