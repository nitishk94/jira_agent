from __future__ import annotations

from typing import Any

from google.adk.tools import FunctionTool
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from mcp import StdioServerParameters

from jira_agent.config import Settings
from jira_agent.execution.docker_runner import DockerTicketContainer


def build_cocoindex_tool(container: DockerTicketContainer, settings: Settings) -> Any:
    """Returns the ADK tool the Fix-Loop agent calls to find relevant code.

    Real mode (COCOINDEX_CONTAINER_NAME set): the official `cocoindex-code`
    MCP server (`ccc mcp`) runs stdio-only — no HTTP/SSE transport — inside
    its own long-running container (see docker/cocoindex-compose.yml and
    scripts/cocoindex_setup.sh), independent of any ticket run per spec §5.
    We reach it the same way CocoIndex's own docs document for Docker use:
    `docker exec -i -w /workspace/<repo> <container> ccc mcp`.

    Stub mode (no container configured yet): falls back to a plain-text
    search (`git grep`) over the ticket's checked-out repo inside its own
    Fix-Loop container, so the rest of the pipeline (navigate -> fix ->
    validate) is still exercisable without a real index. This is a
    stand-in, not a pretend semantic search.
    """
    if settings.cocoindex_container_name:
        return McpToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command="docker",
                    args=[
                        "exec",
                        "-i",
                        "-w",
                        f"/workspace/{settings.cocoindex_repo_dir}",
                        settings.cocoindex_container_name,
                        "ccc",
                        "mcp",
                    ],
                ),
                # ADK's default is 5s -- too short for ccc mcp's docker exec +
                # process/model startup + index refresh. See Settings docstring.
                timeout=settings.cocoindex_timeout_seconds,
            ),
        )

    def cocoindex_query(query: str) -> list[dict[str, str]]:
        """Searches the checked-out repository for code relevant to `query`.

        Returns up to 20 hits, each with `file` and `snippet` (the matching
        line). STUB: plain case-insensitive text search, standing in for the
        real CocoIndex MCP server until COCOINDEX_CONTAINER_NAME is configured.
        """
        result = container.exec(f"git grep -n -i -I --no-color -- {_shell_quote(query)} || true")
        hits: list[dict[str, str]] = []
        for line in result.output.splitlines():
            path, sep, rest = line.partition(":")
            if not sep:
                continue
            hits.append({"file": path, "snippet": rest.strip()})
            if len(hits) >= 20:
                break
        return hits

    return FunctionTool(cocoindex_query)


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"
