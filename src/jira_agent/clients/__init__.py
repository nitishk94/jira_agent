from __future__ import annotations

from jira_agent.clients.github_client import GitHubClient, LiveGitHubClient, MockGitHubClient
from jira_agent.clients.jira_client import JiraClient, LiveJiraClient, MockJiraClient
from jira_agent.config import Settings


def get_jira_client(settings: Settings) -> JiraClient:
    if settings.jira_client_mode == "live":
        return LiveJiraClient(
            base_url=settings.jira_base_url,
            user_email=settings.jira_user_email,
            api_token=settings.jira_api_token,
        )
    return MockJiraClient()


def get_github_client(settings: Settings) -> GitHubClient:
    if settings.github_client_mode == "live":
        return LiveGitHubClient(token=settings.github_token)
    return MockGitHubClient()


__all__ = [
    "JiraClient",
    "MockJiraClient",
    "LiveJiraClient",
    "GitHubClient",
    "MockGitHubClient",
    "LiveGitHubClient",
    "get_jira_client",
    "get_github_client",
]
