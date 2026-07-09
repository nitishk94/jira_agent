from __future__ import annotations

from pathlib import Path

from jira_agent.execution.repo_mirror import ensure_mirror, mirror_path_for


def test_ensure_mirror_clones_then_fetches(tmp_path: Path, sample_repo_git: Path) -> None:
    mirror_dir = tmp_path / "mirrors"
    repo = "demo/sample-repo"

    path1 = ensure_mirror(str(sample_repo_git), repo, mirror_dir)
    assert path1 == mirror_path_for(repo, mirror_dir)
    assert path1.exists()

    # second call fetches an already-cloned mirror instead of re-cloning
    path2 = ensure_mirror(str(sample_repo_git), repo, mirror_dir)
    assert path2 == path1
