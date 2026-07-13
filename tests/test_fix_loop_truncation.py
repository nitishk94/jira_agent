from __future__ import annotations

from jira_agent.agents.fix_loop import _MAX_TOOL_OUTPUT_CHARS, _truncate


def test_truncate_leaves_short_text_untouched() -> None:
    assert _truncate("short output") == "short output"


def test_truncate_caps_long_text_with_marker() -> None:
    text = "x" * (_MAX_TOOL_OUTPUT_CHARS + 500)
    result = _truncate(text)

    assert len(result) < len(text)
    assert result.startswith("x" * 100)
    assert "truncated 500 more characters" in result
