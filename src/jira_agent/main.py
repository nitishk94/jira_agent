from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import stat
import subprocess
from pathlib import Path

from google.auth.exceptions import DefaultCredentialsError

from jira_agent.clients import get_github_client, get_jira_client
from jira_agent.clients.github_client import MockGitHubClient
from jira_agent.clients.jira_client import MockJiraClient
from jira_agent.config import Settings, get_settings
from jira_agent.logging_store.run_log import RunLogStore
from jira_agent.models import ProjectConfig, Ticket
from jira_agent.orchestrator import run_once

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("jira_agent")


def _demo_ticket() -> Ticket:
    return Ticket(
        id="DEMO-1",
        project_key="DEMO",
        issue_type="Bug",
        summary="Checkout crashes when cart is empty",
        description=(
            "Steps to reproduce:\n"
            "1. Start checkout with an empty cart (no items added).\n"
            "2. Observe the request fails instead of showing a validation error.\n\n"
            "Expected: a clear 'cart is empty' error.\n"
            "Actual: an unhandled exception."
        ),
        url="https://example.atlassian.net/browse/DEMO-1",
    )


def _rmtree_git(path: Path) -> None:
    """`shutil.rmtree` chokes on git's read-only object files on Windows.
    Clear the read-only bit on failure and retry the removal."""

    def _on_error(func, target_path, exc) -> None:
        os.chmod(target_path, stat.S_IWRITE)
        func(target_path)

    shutil.rmtree(path, onexc=_on_error)


def _materialize_demo_repo(dest_dir: Path) -> Path:
    """Copies the bundled fixture repo into `dest_dir` as a real, committed
    git repo. Standalone counterpart to tests/conftest.py:sample_repo_git,
    duplicated rather than shared since importing across the src/tests
    package boundary isn't worth it for ~10 lines.
    """
    source = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "sample_repo"
    if not source.exists():
        raise SystemExit(f"Demo fixture repo not found at {source}")

    repo_path = dest_dir / "sample_repo"
    if repo_path.exists():
        _rmtree_git(repo_path)
    shutil.copytree(source, repo_path)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=demo@jira-agent.local",
            "-c",
            "user.name=Demo",
            "commit",
            "-q",
            "-m",
            "Initial commit",
        ],
        cwd=repo_path,
        check=True,
    )
    return repo_path


async def _run_demo(settings: Settings) -> None:
    demo_src_dir = Path(settings.repo_mirror_dir).parent / ".demo-repo-src"
    demo_src_dir.mkdir(parents=True, exist_ok=True)
    repo_path = _materialize_demo_repo(demo_src_dir)

    # Demo mode always uses mock Jira/GitHub clients, regardless of
    # JIRA_CLIENT_MODE/GITHUB_CLIENT_MODE — it's meant to be a safe, fully
    # local dry run (only the Vertex AI calls are real) and must never touch
    # real Jira tickets or push/open a PR against a real GitHub repo.
    jira_client = MockJiraClient(tickets=[_demo_ticket()])
    github_client = MockGitHubClient()
    run_log_store = RunLogStore(settings)
    project = ProjectConfig(jira_project_key="DEMO", github_repo="demo/sample-repo", default_branch="main")

    await run_once(
        settings=settings,
        jira_client=jira_client,
        github_client=github_client,
        run_log_store=run_log_store,
        repo_url_resolver=lambda _p: str(repo_path),
        projects=[project],
    )

    logger.info("Demo run complete.")
    logger.info("Jira comments: %s", jira_client.comments)
    logger.info("Jira statuses: %s", jira_client.statuses)
    if hasattr(github_client, "prs"):
        logger.info("Mock PRs opened: %s", github_client.prs)
    logger.info("Run log written under %s", settings.run_log_local_dir)


async def _run_once_live(settings: Settings) -> None:
    jira_client = get_jira_client(settings)
    github_client = get_github_client(settings)
    run_log_store = RunLogStore(settings)
    logger.info("Running a single live poll cycle (mode: jira=%s, github=%s)...",
                settings.jira_client_mode, settings.github_client_mode)
    await run_once(settings, jira_client, github_client, run_log_store)
    logger.info("Cycle complete.")


async def _poll_loop(settings: Settings) -> None:
    interval_seconds = settings.poll_interval_minutes * 60

    while True:
        logger.info("Starting poll cycle")
        await _run_once_live(settings)
        logger.info("Poll cycle complete, sleeping %ss", interval_seconds)
        await asyncio.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(prog="jira-agent")
    parser.add_argument(
        "--demo",
        action="store_true",
        help=(
            "Run a single end-to-end dry run against the bundled fixture repo "
            "(mock Jira/GitHub, real Triage + Fix-Loop agents against Vertex AI). "
            "No real Jira/GitHub network calls."
        ),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help=(
            "Run a single live poll cycle (real Jira/GitHub per JIRA_CLIENT_MODE/"
            "GITHUB_CLIENT_MODE, real Vertex AI) and exit, instead of polling forever. "
            "For controlled manual testing against real tickets."
        ),
    )
    args = parser.parse_args()

    settings = get_settings()
    try:
        if args.demo:
            asyncio.run(_run_demo(settings))
        elif args.once:
            asyncio.run(_run_once_live(settings))
        else:
            asyncio.run(_poll_loop(settings))
    except DefaultCredentialsError as exc:
        raise SystemExit(
            "Vertex AI call failed: no Google Cloud Application Default Credentials found.\n"
            f"GOOGLE_CLOUD_PROJECT={settings.google_cloud_project or '(not set)'}\n"
            "Run `gcloud auth application-default login` (or set GOOGLE_APPLICATION_CREDENTIALS "
            "to a service account key) for a project with the Vertex AI API enabled, then retry.\n"
            f"Original error: {exc}"
        ) from None


if __name__ == "__main__":
    main()
