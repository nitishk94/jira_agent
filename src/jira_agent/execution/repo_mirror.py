from __future__ import annotations

import subprocess
from pathlib import Path


def mirror_path_for(repo: str, mirror_dir: str | Path) -> Path:
    # Always absolute: Docker's bind-mount volumes require an absolute host
    # path, and settings.repo_mirror_dir defaults to a relative "./..." path
    # — a relative mirror path here previously produced a malformed-path
    # error from Docker Desktop on Windows (500 Server Error on create).
    return (Path(mirror_dir) / f"{repo.replace('/', '__')}.git").resolve()


def ensure_mirror(repo_url: str, repo: str, mirror_dir: str | Path) -> Path:
    """Keeps a persistent bare mirror of `repo` up to date on the host.

    Clones it if missing, otherwise fetches. Call once per poll cycle per
    configured repo — not per ticket (spec §7) — so per-ticket container
    clones (`git clone --reference <mirror> --dissociate`) are fast, local,
    and don't hit GitHub or rate limits.
    """
    path = mirror_path_for(repo, mirror_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        subprocess.run(["git", "-C", str(path), "fetch", "--all", "--prune"], check=True)
    else:
        subprocess.run(["git", "clone", "--mirror", repo_url, str(path)], check=True)
    return path
