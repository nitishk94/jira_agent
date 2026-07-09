from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable

from jira_agent.agents.fix_loop import run_fix_attempt
from jira_agent.agents.triage import run_triage
from jira_agent.clients.github_client import GitHubClient
from jira_agent.clients.jira_client import JiraClient
from jira_agent.config import Settings
from jira_agent.execution.docker_runner import DockerTicketContainer
from jira_agent.execution.repo_mirror import ensure_mirror
from jira_agent.logging_store.run_log import RunLog, RunLogStore
from jira_agent.models import AttemptResult, FixLoopResult, FixOutcome, ProjectConfig, Ticket, TriageResult

RepoUrlResolver = Callable[[ProjectConfig], str]


def _jql_for(project: ProjectConfig) -> str:
    return f'project = "{project.jira_project_key}" AND resolution = Unresolved'


async def run_once(
    settings: Settings,
    jira_client: JiraClient,
    github_client: GitHubClient,
    run_log_store: RunLogStore,
    repo_url_resolver: RepoUrlResolver | None = None,
    projects: list[ProjectConfig] | None = None,
) -> None:
    """One poll cycle across every configured project (spec §3.1).

    `projects` defaults to `settings.projects` (loaded from projects.yaml);
    callers like the demo runner can pass an explicit override instead.
    """
    resolve_repo_url = repo_url_resolver or (lambda p: github_client.push_remote_url(p.github_repo))
    semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_tickets))

    async def _bounded_process(ticket: Ticket, project: ProjectConfig, mirror_path: Path) -> None:
        async with semaphore:
            await process_ticket(
                ticket, project, settings, jira_client, github_client, run_log_store, mirror_path
            )

    tasks: list[asyncio.Task[None]] = []
    for project in projects if projects is not None else settings.projects:
        repo_url = resolve_repo_url(project)
        mirror_path = ensure_mirror(repo_url, project.github_repo, settings.repo_mirror_dir)

        for ticket in jira_client.fetch_tickets(_jql_for(project)):
            tasks.append(asyncio.create_task(_bounded_process(ticket, project, mirror_path)))

    if tasks:
        await asyncio.gather(*tasks)


async def process_ticket(
    ticket: Ticket,
    project: ProjectConfig,
    settings: Settings,
    jira_client: JiraClient,
    github_client: GitHubClient,
    run_log_store: RunLogStore,
    mirror_path: Path,
) -> None:
    """One ticket, end to end (spec §3.1/§9): triage, optionally dispatch the
    Fix-Loop, update Jira, and always write a run log — regardless of outcome.
    """
    run_log = RunLog(ticket=ticket)

    triage = await run_triage(ticket, settings)
    run_log.record_triage(triage)

    if triage.is_bug and triage.repro_clear:
        result = await _run_fix_loop(ticket, project, triage, settings, mirror_path, run_log, github_client)
        if result.outcome is FixOutcome.PR_OPENED:
            jira_client.add_comment(ticket.id, f"Fix proposed: {result.pr_url}")
            jira_client.transition_status(ticket.id, "In Review")
            run_log.finish(
                outcome_line=f"PR opened → `{result.branch}` → [PR link]({result.pr_url})",
                jira_status_line="→ In Review",
            )
        else:
            summary = " / ".join(a.notes.splitlines()[0] for a in result.attempts if a.notes)
            jira_client.add_comment(
                ticket.id,
                f"Automated fix attempt failed after {len(result.attempts)} tries. {summary}",
            )
            run_log.finish(
                outcome_line=f"Escalated after {len(result.attempts)} failed attempts.",
                jira_status_line="unchanged",
            )
    else:
        jira_client.add_comment(ticket.id, triage.reasoning)
        run_log.finish(outcome_line="Triage only — no fix attempted.", jira_status_line="unchanged")

    run_log_store.write(run_log)


async def _run_fix_loop(
    ticket: Ticket,
    project: ProjectConfig,
    triage: TriageResult,
    settings: Settings,
    mirror_path: Path,
    run_log: RunLog,
    github_client: GitHubClient,
) -> FixLoopResult:
    branch_name = f"fix/{ticket.id}"
    attempts: list[AttemptResult] = []

    with DockerTicketContainer(mirror_path) as container:
        prior_notes: str | None = None
        for attempt_number in range(1, settings.max_fix_attempts + 1):
            attempt = await run_fix_attempt(
                container, settings, ticket, triage, attempt_number, settings.max_fix_attempts, prior_notes
            )
            attempts.append(attempt)
            run_log.record_attempt(attempt)

            if attempt.passed:
                files_changed = len(container.exec("git diff --name-only").output.splitlines())
                container.exec(f"git checkout -b {branch_name}")
                container.exec("git add -A")
                container.exec(
                    'git -c user.email=agent@jira-agent.local -c user.name="Jira Auto-Fix Agent" '
                    f'commit -m "Fix {ticket.id}: {ticket.summary}"'
                )
                remote_url = github_client.push_remote_url(project.github_repo)
                container.exec(f"git push {remote_url} HEAD:{branch_name}")

                pr = github_client.open_pr(
                    repo=project.github_repo,
                    branch=branch_name,
                    base=project.default_branch,
                    title=f"Fix {ticket.id}: {ticket.summary}",
                    body=_pr_body(ticket, triage, attempts),
                )
                return FixLoopResult(
                    outcome=FixOutcome.PR_OPENED,
                    attempts=attempts,
                    pr_url=pr.url,
                    branch=branch_name,
                    files_changed=files_changed,
                    commits=1,
                )

            prior_notes = attempt.notes

    return FixLoopResult(outcome=FixOutcome.ESCALATED, attempts=attempts)


def _pr_body(ticket: Ticket, triage: TriageResult, attempts: list[AttemptResult]) -> str:
    lines = [f"Fixes {ticket.id}: {ticket.summary}", "", f"Triage: {triage.reasoning}", "", "Attempts:"]
    for attempt in attempts:
        lines.append(f"- #{attempt.attempt_number}: {'pass' if attempt.passed else 'fail'} — {attempt.notes}")
    return "\n".join(lines)
