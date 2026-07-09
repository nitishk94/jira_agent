from __future__ import annotations

from jira_agent.clients.github_client import MockGitHubClient
from jira_agent.clients.jira_client import MockJiraClient
from jira_agent.models import Ticket


def _ticket(ticket_id: str = "T-1") -> Ticket:
    return Ticket(id=ticket_id, project_key="ENG", issue_type="Bug", summary="s", description="d")


def test_mock_jira_fetch_add_comment_transition() -> None:
    client = MockJiraClient(tickets=[_ticket()])

    assert [t.id for t in client.fetch_tickets("irrelevant jql")] == ["T-1"]

    client.add_comment("T-1", "hello")
    assert client.comments["T-1"] == ["hello"]

    client.transition_status("T-1", "In Review")
    assert client.statuses["T-1"] == "In Review"
    # transitioned tickets drop out of the fetch queue
    assert client.fetch_tickets("irrelevant jql") == []


def test_mock_github_open_pr_and_remote_url() -> None:
    client = MockGitHubClient()

    url = client.push_remote_url("org/repo")
    assert url.endswith("org/repo.git")

    pr = client.open_pr("org/repo", "fix/T-1", "main", "title", "body")
    assert pr.number == 1
    assert "org/repo" in pr.url
    assert client.prs == [pr]
