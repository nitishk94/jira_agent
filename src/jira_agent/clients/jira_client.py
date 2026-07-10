from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from jira_agent.models import Ticket


class JiraClient(ABC):
    @abstractmethod
    def fetch_tickets(self, jql: str) -> list[Ticket]: ...

    @abstractmethod
    def add_comment(self, ticket_id: str, text: str) -> None: ...

    @abstractmethod
    def transition_status(self, ticket_id: str, status: str) -> None: ...


class MockJiraClient(JiraClient):
    """In-memory Jira client backed by seeded fixture tickets. No network calls."""

    def __init__(self, tickets: list[Ticket] | None = None) -> None:
        self._tickets: dict[str, Ticket] = {t.id: t for t in (tickets or [])}
        self.comments: dict[str, list[str]] = {}
        self.statuses: dict[str, str] = {}

    def seed(self, ticket: Ticket) -> None:
        self._tickets[ticket.id] = ticket

    def fetch_tickets(self, jql: str) -> list[Ticket]:
        # The mock ignores JQL filtering and returns every seeded ticket that
        # hasn't already been transitioned to a terminal status.
        return [t for t in self._tickets.values() if t.id not in self.statuses]

    def add_comment(self, ticket_id: str, text: str) -> None:
        self.comments.setdefault(ticket_id, []).append(text)

    def transition_status(self, ticket_id: str, status: str) -> None:
        self.statuses[ticket_id] = status


class LiveJiraClient(JiraClient):
    """Real Jira client via the `jira` package.

    Set JIRA_BASE_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN and
    JIRA_CLIENT_MODE=live to exercise this against a real Jira site.
    """

    def __init__(self, base_url: str, user_email: str, api_token: str) -> None:
        from jira import JIRA

        self._jira = JIRA(server=base_url, basic_auth=(user_email, api_token))

    def fetch_tickets(self, jql: str) -> list[Ticket]:
        issues = self._jira.search_issues(jql)
        return [
            Ticket(
                id=issue.key,
                project_key=issue.fields.project.key,
                issue_type=issue.fields.issuetype.name,
                summary=issue.fields.summary,
                description=issue.fields.description or "",
                url=issue.permalink(),
                created_at=datetime.fromisoformat(issue.fields.created),
                updated_at=datetime.fromisoformat(issue.fields.updated),
            )
            for issue in issues
        ]

    def add_comment(self, ticket_id: str, text: str) -> None:
        self._jira.add_comment(ticket_id, text)

    def transition_status(self, ticket_id: str, status: str) -> None:
        # A Jira transition is identified by its own name/id, not by the
        # target status name -- passing the status straight to
        # transition_issue() only works by coincidence. Look up the
        # transition whose destination status matches instead. Confirmed
        # against a real project (POL): its workflow has no direct
        # "To Do" -> "In Review" transition at all (only "In Progress"), so
        # treat "no matching transition" as a soft no-op rather than a
        # crash -- the more important side effects (comment, PR) already
        # happened by the time this runs and shouldn't be lost over it.
        available = self._jira.transitions(ticket_id)
        match = next(
            (t for t in available if t["to"]["name"].lower() == status.lower()), None
        )
        if match is None:
            return
        self._jira.transition_issue(ticket_id, match["id"])
