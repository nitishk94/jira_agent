from __future__ import annotations

import io
import tarfile
from dataclasses import dataclass
from pathlib import Path

import docker
import docker.errors

_DOCKERFILE = Path(__file__).resolve().parents[3] / "docker" / "fix-loop.Dockerfile"
IMAGE_TAG = "jira-agent-fix-loop:latest"


@dataclass
class ExecResult:
    exit_code: int
    output: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class DockerTicketContainer:
    """One Docker container per ticket run.

    Clones the repo from the local bare mirror (mounted read-only) using
    `git clone --reference <mirror> --dissociate` — fast and local, no
    per-ticket network round-trip. Lives for the duration of the ticket's
    fix attempts; always removed on exit (spec §7), enabling safe parallel
    execution across tickets without state leakage.
    """

    def __init__(self, mirror_path: Path, workdir: str = "/workspace/repo") -> None:
        self._client = docker.from_env()
        self._mirror_path = mirror_path
        self._workdir = workdir
        self._container = None

    def __enter__(self) -> "DockerTicketContainer":
        self._ensure_image()
        self._container = self._client.containers.run(
            IMAGE_TAG,
            command="sleep infinity",
            volumes={str(self._mirror_path): {"bind": "/mirror", "mode": "ro"}},
            detach=True,
        )
        clone = self.exec(f"git clone --reference /mirror --dissociate /mirror {self._workdir}", workdir="/")
        if not clone.ok:
            self.__exit__(None, None, None)
            raise RuntimeError(f"repo clone into container failed: {clone.output}")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._container is not None:
            self._container.remove(force=True)
            self._container = None

    def _ensure_image(self) -> None:
        try:
            self._client.images.get(IMAGE_TAG)
        except docker.errors.ImageNotFound:
            self._client.images.build(
                path=str(_DOCKERFILE.parent), dockerfile=_DOCKERFILE.name, tag=IMAGE_TAG
            )

    def exec(self, command: str, workdir: str | None = None) -> ExecResult:
        assert self._container is not None, "container not started"
        exit_code, output = self._container.exec_run(
            ["sh", "-c", command], workdir=workdir or self._workdir
        )
        return ExecResult(exit_code=exit_code, output=output.decode("utf-8", errors="replace"))

    def read_file(self, path: str) -> str:
        result = self.exec(f"cat {path}")
        if not result.ok:
            raise FileNotFoundError(f"{path}: {result.output}")
        return result.output

    def write_file(self, path: str, content: str) -> None:
        assert self._container is not None, "container not started"
        data = content.encode("utf-8")
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as tar:
            info = tarfile.TarInfo(name=path)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        archive.seek(0)
        self._container.put_archive(self._workdir, archive)
