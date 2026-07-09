from __future__ import annotations

from typing import Any

from google.adk.tools import FunctionTool
from google.adk.tools.mcp_tool import MCPToolset, StreamableHTTPConnectionParams

from jira_agent.config import Settings
from jira_agent.execution.docker_runner import DockerTicketContainer


def build_cocoindex_tool(container: DockerTicketContainer, settings: Settings) -> Any:
    """Returns the ADK tool the Fix-Loop agent calls to find relevant code.

    Real mode (COCOINDEX_MCP_URL set): connects to the CocoIndex MCP server
    for BM25 + vector hybrid search, per spec §5 — CocoIndex's indexing
    internals stay fully abstracted behind this MCP interface.

    Stub mode (no URL configured yet): falls back to a plain-text search
    (`git grep`) over the ticket's checked-out repo inside its container, so
    the rest of the pipeline (navigate -> fix -> validate) is still
    exercisable without a real index. This is a stand-in, not a pretend
    semantic search.
    """
    if settings.cocoindex_mcp_url:
        return MCPToolset(
            connection_params=StreamableHTTPConnectionParams(url=settings.cocoindex_mcp_url),
        )

    def cocoindex_query(query: str) -> list[dict[str, str]]:
        """Searches the checked-out repository for code relevant to `query`.

        Returns up to 20 hits, each with `file` and `snippet` (the matching
        line). STUB: plain case-insensitive text search, standing in for the
        real CocoIndex MCP server until COCOINDEX_MCP_URL is configured.
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
