from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PullRequest:
    url: str
    number: int
    branch: str


class GitHubClient(ABC):
    """Only covers the GitHub-API surface (opening a PR) and producing an
    authenticated remote URL. The actual branch/commit work happens as real
    `git` commands run inside the ticket's container (see
    execution/docker_runner.py) against that remote URL — PyGithub has no
    role in local git operations.
    """

    @abstractmethod
    def push_remote_url(self, repo: str) -> str:
        """An authenticated `https://...` remote URL suitable for `git push`."""

    @abstractmethod
    def open_pr(self, repo: str, branch: str, base: str, title: str, body: str) -> PullRequest: ...


class MockGitHubClient(GitHubClient):
    """Records calls instead of hitting GitHub. Used by the demo run and
    tests to inspect what would have been pushed/opened."""

    def __init__(self) -> None:
        self.prs: list[PullRequest] = []
        self._pr_counter = 0

    def push_remote_url(self, repo: str) -> str:
        return f"https://mock-remote.invalid/{repo}.git"

    def open_pr(self, repo: str, branch: str, base: str, title: str, body: str) -> PullRequest:
        self._pr_counter += 1
        pr = PullRequest(
            url=f"https://github.com/{repo}/pull/{self._pr_counter}",
            number=self._pr_counter,
            branch=branch,
        )
        self.prs.append(pr)
        return pr


class LiveGitHubClient(GitHubClient):
    """Real GitHub client via PyGithub.

    Untested — no credentials configured yet. Set GITHUB_TOKEN and
    GITHUB_CLIENT_MODE=live to exercise this against a real repo.
    """

    def __init__(self, token: str) -> None:
        from github import Github

        self._token = token
        self._gh = Github(token)

    def push_remote_url(self, repo: str) -> str:
        return f"https://x-access-token:{self._token}@github.com/{repo}.git"

    def open_pr(self, repo: str, branch: str, base: str, title: str, body: str) -> PullRequest:
        repository = self._gh.get_repo(repo)
        pr = repository.create_pull(title=title, body=body, head=branch, base=base)
        return PullRequest(url=pr.html_url, number=pr.number, branch=branch)
