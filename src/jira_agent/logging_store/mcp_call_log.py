from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Tool name differs by mode: the stub (tools/cocoindex_mcp.py) registers a
# FunctionTool named after the Python function; the real CocoIndex MCP
# server's own tool is named "search" (per its documented schema).
COCOINDEX_TOOL_NAMES = {"cocoindex_query", "search"}


class McpCallLog:
    """Appends every CocoIndex tool call (query args + result) for one
    ticket run to a dedicated JSONL log — a raw debug trace of code
    navigation quality, separate from the human-readable run log/PR
    narrative.
    """

    def __init__(self, local_dir: str, ticket_id: str) -> None:
        self._path = Path(local_dir) / f"{ticket_id}-mcp-calls.log"

    def record(self, attempt_number: int, tool_name: str, args: dict[str, Any], response: Any) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "attempt": attempt_number,
            "tool": tool_name,
            "query_args": args,
            "response": response,
        }
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
