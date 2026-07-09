from __future__ import annotations

from google.adk.tools import FunctionTool
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams

from jira_agent.config import Settings
from jira_agent.tools.cocoindex_mcp import build_cocoindex_tool


class _NoopContainer:
    def exec(self, command: str, workdir: str | None = None):
        raise AssertionError("should not be called during tool construction")


def test_stub_mode_returns_function_tool_when_container_name_unset() -> None:
    settings = Settings(_env_file=None)
    tool = build_cocoindex_tool(_NoopContainer(), settings)
    assert isinstance(tool, FunctionTool)


def test_real_mode_builds_docker_exec_stdio_toolset() -> None:
    settings = Settings(
        _env_file=None, cocoindex_container_name="cocoindex-code", cocoindex_repo_dir="polaris-FDD"
    )
    tool = build_cocoindex_tool(_NoopContainer(), settings)

    assert isinstance(tool, McpToolset)
    params = tool.connection_params
    assert isinstance(params, StdioConnectionParams)
    server_params = params.server_params
    assert server_params.command == "docker"
    assert server_params.args == [
        "exec",
        "-i",
        "-w",
        "/workspace/polaris-FDD",
        "cocoindex-code",
        "ccc",
        "mcp",
    ]
