from __future__ import annotations

from jira_agent.agents.fix_loop import ValidationCommands, _build_tools
from jira_agent.config import Settings


class _NoopContainer:
    def exec(self, command: str, workdir: str | None = None):
        raise AssertionError("should not be called during tool construction")


def test_build_tools_returns_expected_tool_set() -> None:
    settings = Settings(_env_file=None)
    tools = _build_tools(_NoopContainer(), settings, ValidationCommands())
    assert len(tools) == 6
