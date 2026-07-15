from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class ProjectConfig(BaseModel):
    jira_project_key: str
    github_repo: str
    default_branch: str = "main"
    # Fix-Loop container image for this project's repo; empty uses the
    # default Python-only image (docker_runner.IMAGE_TAG). Set to
    # docker_runner.NODE_IMAGE_TAG (or another built image) for repos that
    # need a different toolchain, e.g. a JS/TypeScript frontend needing Node.
    docker_image: str = ""


class Ticket(BaseModel):
    id: str
    project_key: str
    issue_type: str
    summary: str
    description: str
    url: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TriageResult(BaseModel):
    is_bug: bool
    issue_type_matched: bool
    repro_clear: bool
    reasoning: str


class AttemptResult(BaseModel):
    attempt_number: int
    passed: bool
    notes: str
    # How many times this attempt called the CocoIndex code-search tool.
    # Surfaced separately from `notes` so the human-readable run log can
    # flag the zero-call case explicitly — confirmed on a real run that an
    # attempt can open a real PR while never using code search at all,
    # which was otherwise invisible outside the raw mcp-calls.log.
    cocoindex_calls: int = 0


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
