from __future__ import annotations

import io
import logging
import tarfile
from dataclasses import dataclass
from pathlib import Path

import docker
import docker.errors

logger = logging.getLogger("jira_agent")

_DOCKER_DIR = Path(__file__).resolve().parents[3] / "docker"
IMAGE_TAG = "jira-agent-fix-loop:latest"
NODE_IMAGE_TAG = "jira-agent-fix-loop-node:latest"
CONTAINER_LABELS = {"app": "jira-agent-fix-loop"}

# Which Dockerfile builds which image tag, so DockerTicketContainer can
# auto-build whichever one a project selects (ProjectConfig.docker_image).
_DOCKERFILES = {
    IMAGE_TAG: "fix-loop.Dockerfile",
    NODE_IMAGE_TAG: "fix-loop-node.Dockerfile",
}

# Any container we create carries this label, so orphans (e.g. left behind by
# a Ctrl+C that lands mid blocking docker-py call, before __exit__ gets a
# chance to run) can always be found and swept:
#   docker ps -aq --filter label=app=jira-agent-fix-loop | xargs -r docker rm -f


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

    def __init__(
        self,
        mirror_path: Path,
        branch: str,
        image_tag: str = IMAGE_TAG,
        workdir: str = "/workspace/repo",
    ) -> None:
        self._client = docker.from_env()
        self._mirror_path = mirror_path
        self._branch = branch
        self._image_tag = image_tag
        self._workdir = workdir
        self._container = None

    def __enter__(self) -> "DockerTicketContainer":
        self._ensure_image()
        self._container = self._client.containers.run(
            self._image_tag,
            command="sleep infinity",
            volumes={str(self._mirror_path): {"bind": "/mirror", "mode": "ro"}},
            labels=CONTAINER_LABELS,
            detach=True,
        )
        # --branch is required: a bare-mirror clone otherwise checks out
        # whichever ref the mirror's HEAD happens to point at, which may not
        # be the project's configured default_branch (confirmed against a
        # real repo where HEAD/main was a near-empty skeleton and all real
        # code lived on dev).
        clone = self.exec(
            f"git clone --reference /mirror --dissociate --branch {self._branch} /mirror {self._workdir}",
            workdir="/",
        )
        if not clone.ok:
            self.__exit__(None, None, None)
            raise RuntimeError(f"repo clone into container failed: {clone.output}")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._container is None:
            return
        try:
            self._container.remove(force=True)
        except Exception:
            # Never let a cleanup failure mask the original exception (if
            # any) that's already propagating. Log it so a leaked container
            # is at least visible instead of silently orphaned -- sweep with
            # `docker ps -aq --filter label=app=jira-agent-fix-loop | xargs -r docker rm -f`.
            logger.exception("Failed to remove Fix-Loop container %s", self._container.id)
        finally:
            self._container = None

    def _ensure_image(self) -> None:
        try:
            self._client.images.get(self._image_tag)
        except docker.errors.ImageNotFound:
            dockerfile = _DOCKERFILES.get(self._image_tag)
            if dockerfile is None:
                raise ValueError(
                    f"No Dockerfile known for image tag {self._image_tag!r}. "
                    f"Known tags: {sorted(_DOCKERFILES)}"
                ) from None
            self._client.images.build(path=str(_DOCKER_DIR), dockerfile=dockerfile, tag=self._image_tag)

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
