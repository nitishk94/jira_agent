from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable

from jira_agent.agents.fix_loop import run_fix_attempt
from jira_agent.agents.triage import run_triage
from jira_agent.clients.github_client import GitHubClient
from jira_agent.clients.jira_client import JiraClient
from jira_agent.config import Settings
from jira_agent.execution.docker_runner import IMAGE_TAG, DockerTicketContainer
from jira_agent.execution.repo_mirror import ensure_mirror
from jira_agent.logging_store.run_log import RunLog, RunLogStore
from jira_agent.logging_store.timing_log import TimingLog
from jira_agent.models import AttemptResult, FixLoopResult, FixOutcome, ProjectConfig, Ticket, TriageResult

RepoUrlResolver = Callable[[ProjectConfig], str]


def _jql_for(project: ProjectConfig, ticket_key: str | None = None) -> str:
    if ticket_key:
        # Scoped to exactly one ticket, bypassing the assignee/resolution
        # filters — for controlled manual testing against a single real
        # ticket without touching everything else assigned to the account.
        return f'key = "{ticket_key}"'
    # Only tickets assigned to the agent's own Jira account (spec §1: "tickets
    # assigned to it") — currentUser() resolves server-side to whichever
    # account JIRA_USER_EMAIL/JIRA_API_TOKEN authenticates as.
    return f'project = "{project.jira_project_key}" AND resolution = Unresolved AND assignee = currentUser()'


async def run_once(
    settings: Settings,
    jira_client: JiraClient,
    github_client: GitHubClient,
    run_log_store: RunLogStore,
    repo_url_resolver: RepoUrlResolver | None = None,
    projects: list[ProjectConfig] | None = None,
    ticket_key: str | None = None,
) -> None:
    """One poll cycle across every configured project (spec §3.1).

    `projects` defaults to `settings.projects` (loaded from projects.yaml);
    callers like the demo runner can pass an explicit override instead.
    `ticket_key`, if given, restricts processing to that one ticket only.
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

        for ticket in jira_client.fetch_tickets(_jql_for(project, ticket_key)):
            last_processed = run_log_store.last_processed_at(ticket.id)
            if last_processed is not None and ticket.updated_at <= last_processed:
                # Nothing has changed on this ticket since our last run (its
                # JQL-matching state — e.g. "comment only, status unchanged"
                # — would otherwise make it match every poll cycle forever).
                # A newer `updated_at` (edit, new comment, reopen) clears
                # this and lets it be reprocessed, per spec §6.
                continue
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
    timing_log = TimingLog(settings.run_log_local_dir)
    start_time = timing_log.record_start(ticket.id)
    outcome = "crashed"  # overwritten below on any non-exceptional path
    try:
        triage = await run_triage(ticket, settings)
        run_log.record_triage(triage)

        if triage.is_bug and triage.repro_clear:
            result = await _run_fix_loop(
                ticket, project, triage, settings, mirror_path, run_log, github_client
            )
            if result.outcome is FixOutcome.PR_OPENED:
                jira_client.add_comment(ticket.id, f"Fix proposed: {result.pr_url}")
                jira_client.transition_status(ticket.id, "In Review")
                run_log.finish(
                    outcome_line=f"PR opened → `{result.branch}` → [PR link]({result.pr_url})",
                    jira_status_line="→ In Review",
                )
                outcome = "pr_opened"
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
                outcome = "escalated"
        else:
            jira_client.add_comment(ticket.id, triage.reasoning)
            run_log.finish(outcome_line="Triage only — no fix attempted.", jira_status_line="unchanged")
            outcome = "triage_only"

        run_log_store.write(run_log)
    finally:
        # Recorded even on a crash (outcome stays "crashed") -- how long a
        # run lasted before failing is useful debugging info on its own.
        timing_log.record_end(ticket.id, start_time, outcome)


_LOCKFILES = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock")
_MANIFESTS = {
    "package-lock.json": "package.json",
    "yarn.lock": "package.json",
    "pnpm-lock.yaml": "package.json",
    "uv.lock": "pyproject.toml",
}


def _revert_incidental_lockfile_churn(container: DockerTicketContainer) -> None:
    """Running `npm install`/etc. during validation can regenerate a
    lockfile wholesale (confirmed on a real PR: package-lock.json with
    +9258/-5729 lines for an unrelated one-line bug fix), swamping the diff
    with noise. If the corresponding manifest (package.json, pyproject.toml)
    didn't actually change -- i.e. no dependency was genuinely added -- the
    lockfile churn is incidental, so discard it before committing.
    """
    for lockfile in _LOCKFILES:
        manifest = _MANIFESTS[lockfile]
        lockfile_changed = container.exec(f"git diff --name-only -- {lockfile}").output.strip()
        manifest_changed = container.exec(f"git diff --name-only -- {manifest}").output.strip()
        if lockfile_changed and not manifest_changed:
            container.exec(f"git checkout -- {lockfile}")


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

    image_tag = project.docker_image or IMAGE_TAG
    with DockerTicketContainer(mirror_path, branch=project.default_branch, image_tag=image_tag) as container:
        prior_notes: str | None = None
        for attempt_number in range(1, settings.max_fix_attempts + 1):
            attempt = await run_fix_attempt(
                container, settings, ticket, triage, attempt_number, settings.max_fix_attempts, prior_notes
            )
            attempts.append(attempt)
            run_log.record_attempt(attempt)

            # Surfaced explicitly (including the zero case) because it was
            # otherwise invisible outside the raw mcp-calls.log: confirmed on
            # a real run that an attempt can open a PR while never calling
            # CocoIndex at all.
            total_cocoindex_calls = sum(a.cocoindex_calls for a in attempts)
            run_log.record_code_navigation(
                f"Queried CocoIndex {total_cocoindex_calls} time(s) across {len(attempts)} attempt(s)."
                if total_cocoindex_calls
                else f"Did not call CocoIndex code search in {len(attempts)} attempt(s) so far."
            )

            if attempt.passed:
                _revert_incidental_lockfile_churn(container)
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
