from __future__ import annotations

from pathlib import Path

import pytest

from jira_agent.config import Settings, load_projects


def test_load_projects_from_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / "projects.yaml"
    yaml_path.write_text(
        "projects:\n"
        "  - jira_project_key: ENG\n"
        "    github_repo: org/backend-service\n"
        "    default_branch: main\n"
    )
    projects = load_projects(yaml_path)
    assert len(projects) == 1
    assert projects[0].jira_project_key == "ENG"
    assert projects[0].github_repo == "org/backend-service"
    assert projects[0].default_branch == "main"


def test_load_projects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_projects(tmp_path / "does-not-exist.yaml")


def test_settings_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.jira_client_mode == "mock"
    assert settings.github_client_mode == "mock"
    assert settings.max_fix_attempts == 3
    assert settings.gemini_model == "gemini-3-flash-preview"


def test_settings_overrides() -> None:
    settings = Settings(_env_file=None, jira_client_mode="live", max_fix_attempts=5)
    assert settings.jira_client_mode == "live"
    assert settings.max_fix_attempts == 5


def test_repo_projects_yaml_loads() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    projects = load_projects(repo_root / "config" / "projects.yaml")
    assert {p.jira_project_key for p in projects} == {"ENG", "PLAT"}
