from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

from jira_agent.models import ProjectConfig


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Jira
    jira_base_url: str = ""
    jira_user_email: str = ""
    jira_api_token: str = ""

    # GitHub
    github_token: str = ""

    # Vertex AI (Gemini 3 Flash). Gemini 3 models are only served from the
    # global endpoint on Vertex AI — a regional location (e.g. us-central1)
    # 404s with "Publisher model ... was not found", confirmed against a
    # real project this session.
    google_cloud_project: str = ""
    google_cloud_location: str = "global"
    gemini_model: str = "gemini-3-flash-preview"

    # Client modes: mock | live
    jira_client_mode: str = "mock"
    github_client_mode: str = "mock"

    # CocoIndex MCP server (stdio via `docker exec`, see
    # scripts/cocoindex_setup.sh); empty container name => plain-text search
    # stub instead.
    cocoindex_container_name: str = ""
    cocoindex_repo_dir: str = ""
    # ADK's MCP client default (5s) is too short for `ccc mcp`: docker exec
    # + process startup + embedding-model load + (by default) an index
    # refresh before every search can easily exceed it, especially on a
    # cold start. Confirmed against a real run ("Timed out while waiting
    # for response to ClientRequest. Waited 5.0 seconds.").
    cocoindex_timeout_seconds: float = 60.0

    # Run log storage; empty bucket => local-only
    run_log_gcs_bucket: str = ""
    run_log_local_dir: str = "./logs"

    # Orchestration
    poll_interval_minutes: int = 5
    max_concurrent_tickets: int = 3
    max_fix_attempts: int = 3

    projects_config_path: str = "./config/projects.yaml"
    repo_mirror_dir: str = "./.repo-mirrors"

    @property
    def projects(self) -> list[ProjectConfig]:
        return load_projects(self.projects_config_path)


def load_projects(path: str | Path) -> list[ProjectConfig]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Project mapping config not found: {config_path}")
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return [ProjectConfig(**entry) for entry in data.get("projects", [])]


@lru_cache
def get_settings() -> Settings:
    return Settings()
