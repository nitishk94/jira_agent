from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURE_SOURCE = Path(__file__).parent / "fixtures" / "sample_repo"


@pytest.fixture
def sample_repo_git(tmp_path: Path) -> Path:
    """Materializes tests/fixtures/sample_repo as a real, committed git repo
    in a temp directory — the clone source used by repo-mirror tests and the
    `--demo` CLI mode.
    """
    repo_path = tmp_path / "sample_repo"
    shutil.copytree(FIXTURE_SOURCE, repo_path)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test",
            "commit",
            "-q",
            "-m",
            "Initial commit",
        ],
        cwd=repo_path,
        check=True,
    )
    return repo_path
