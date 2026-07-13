from __future__ import annotations

import json
from pathlib import Path

from jira_agent.agents.fix_loop import _build_mcp_logging_callback
from jira_agent.logging_store.mcp_call_log import McpCallLog


def test_record_appends_jsonl_entries(tmp_path: Path) -> None:
    log = McpCallLog(str(tmp_path), "ENG-1")
    log.record(1, "search", {"query": "empty cart"}, [{"file": "a.py"}])
    log.record(2, "search", {"query": "checkout"}, [])

    lines = (tmp_path / "ENG-1-mcp-calls.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["attempt"] == 1
    assert first["tool"] == "search"
    assert first["query_args"] == {"query": "empty cart"}
    assert first["response"] == [{"file": "a.py"}]


def test_logging_callback_only_records_cocoindex_tools(tmp_path: Path) -> None:
    log = McpCallLog(str(tmp_path), "ENG-1")
    callback = _build_mcp_logging_callback(log, attempt_number=1)

    class _FakeTool:
        def __init__(self, name: str) -> None:
            self.name = name

    result = callback(
        tool=_FakeTool("search"), args={"query": "q"}, tool_context=None, tool_response={"ok": True}
    )
    assert result is None  # never overrides the real tool response

    result = callback(
        tool=_FakeTool("run_shell"), args={"command": "ls"}, tool_context=None, tool_response={"ok": True}
    )
    assert result is None

    lines = (tmp_path / "ENG-1-mcp-calls.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1  # only the "search" call was recorded, not run_shell
    assert json.loads(lines[0])["tool"] == "search"
