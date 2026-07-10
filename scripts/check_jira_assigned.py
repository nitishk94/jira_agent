"""Diagnostic: list Jira tickets assigned to the authenticated account.

Bypasses JIRA_CLIENT_MODE (always uses a real Jira connection) and doesn't
filter by project, since the goal is to sanity-check the credentials/account
and the `assignee = currentUser()` JQL the orchestrator relies on
(see orchestrator.py:_jql_for) independent of project config.

Run: uv run python scripts/check_jira_assigned.py
     uv run python scripts/check_jira_assigned.py "Dev complete"   # filter by status
"""

from __future__ import annotations

import sys

from jira_agent.clients.jira_client import LiveJiraClient
from jira_agent.config import get_settings


def main() -> None:
    settings = get_settings()
    if not (settings.jira_base_url and settings.jira_user_email and settings.jira_api_token):
        raise SystemExit("JIRA_BASE_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN must all be set in .env")

    client = LiveJiraClient(
        base_url=settings.jira_base_url,
        user_email=settings.jira_user_email,
        api_token=settings.jira_api_token,
    )

    status_filter = sys.argv[1] if len(sys.argv) > 1 else None
    jql = "assignee = currentUser()"
    jql += f' AND status = "{status_filter}"' if status_filter else " AND resolution = Unresolved"
    jql += " ORDER BY updated DESC"

    tickets = client.fetch_tickets(jql)
    label = f'status = "{status_filter}"' if status_filter else "unresolved"

    if not tickets:
        print(f"No {label} tickets assigned to {settings.jira_user_email}.")
        print(f"JQL used: {jql}")
        return

    print(f"{len(tickets)} {label} ticket(s) assigned to {settings.jira_user_email}:\n")
    for t in tickets:
        print(f"- {t.id} [{t.project_key}] {t.issue_type}: {t.summary}")
        print(f"    updated: {t.updated_at.isoformat()}")
        print(f"    {t.url}")


if __name__ == "__main__":
    main()
