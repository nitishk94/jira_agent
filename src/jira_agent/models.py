from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class ProjectConfig(BaseModel):
    jira_project_key: str
    github_repo: str
    default_branch: str = "main"


class Ticket(BaseModel):
    id: str
    project_key: str
    issue_type: str
    summary: str
    description: str
    url: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TriageResult(BaseModel):
    is_bug: bool
    issue_type_matched: bool
    repro_clear: bool
    reasoning: str


class AttemptResult(BaseModel):
    attempt_number: int
    passed: bool
    notes: str


class FixOutcome(str, Enum):
    PR_OPENED = "pr_opened"
    ESCALATED = "escalated"


class FixLoopResult(BaseModel):
    outcome: FixOutcome
    attempts: list[AttemptResult]
    pr_url: str | None = None
    branch: str | None = None
    files_changed: int = 0
    commits: int = 0
