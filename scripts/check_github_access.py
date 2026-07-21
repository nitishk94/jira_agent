"""Diagnostic: confirm GITHUB_TOKEN actually authenticates and has the
access the Fix-Loop needs (pull to clone, push to deliver a fix) for every
repo configured in projects.yaml -- or a specific repo passed as an arg.

Checks two separate things, since they fail for different reasons:
- The token's own configured permissions (repo.permissions) -- what you set
  when creating the fine-grained token.
- Your account's actual collaborator role on the repo (get_collaborator_permission)
  -- the ceiling the token can never exceed, regardless of how it's configured.
  A token with every box checked still shows push=False if the account
  itself is only a Read collaborator.

Run: uv run python scripts/check_github_access.py
     uv run python scripts/check_github_access.py KanakaSoftware/po-nexus
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv
from github import Github

from jira_agent.config import get_settings


def check_repo(gh: Github, username: str, repo_name: str) -> bool:
    print(f"=== {repo_name} ===")
    try:
        repo = gh.get_repo(repo_name)
    except Exception as exc:
        print(f"  FAIL: could not access repo: {exc}")
        return False

    perms = repo.permissions
    print(f"  Token permissions -> pull={perms.pull} push={perms.push} admin={perms.admin}")

    try:
        role = gh.get_repo(repo_name).get_collaborator_permission(username)
        print(f"  Your account's collaborator role -> {role}")
    except Exception as exc:
        role = None
        print(f"  Could not determine collaborator role: {exc}")

    ok = bool(perms.pull and perms.push)
    if not ok:
        if role in ("read", "none", None):
            print(
                "  -> Likely cause: your account's collaborator role on this repo is "
                f"{role!r}, not write/admin/maintain. A token can never exceed what the "
                "account already has -- ask a repo/org admin to upgrade your role."
            )
        else:
            print(
                "  -> Account role looks sufficient, but the token itself doesn't have "
                "push. Likely cause: fine-grained token pending org approval, wrong "
                "repository selected on the token, or Contents permission not set to "
                "Read and write."
            )
    print(f"  {'PASS' if ok else 'FAIL'}: pull+push {'available' if ok else 'NOT both available'}")
    print()
    return ok


def main() -> None:
    load_dotenv()
    settings = get_settings()
    if not settings.github_token:
        raise SystemExit("GITHUB_TOKEN is not set in .env")

    gh = Github(settings.github_token)
    username = gh.get_user().login
    print(f"Authenticated as: {username}\n")

    repos = sys.argv[1:] or [p.github_repo for p in settings.projects]
    if not repos:
        raise SystemExit("No repos to check: pass one as an argument, or configure config/projects.yaml")

    results = [check_repo(gh, username, repo) for repo in repos]
    if not all(results):
        raise SystemExit(1)
    print("All repos OK.")


if __name__ == "__main__":
    main()
