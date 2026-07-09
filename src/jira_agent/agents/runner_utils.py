from __future__ import annotations

import uuid
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.runners import InMemoryRunner
from google.genai import types


async def run_agent_once(
    agent: BaseAgent,
    prompt: str,
    *,
    app_name: str,
    initial_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Runs `agent` for a single turn in a fresh session and returns the
    resulting session state (where structured `output_key` results land).
    """
    runner = InMemoryRunner(agent=agent, app_name=app_name)
    user_id = "jira-agent"
    session_id = str(uuid.uuid4())

    await runner.session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
        state=initial_state or {},
    )

    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    async for _event in runner.run_async(user_id=user_id, session_id=session_id, new_message=message):
        pass

    session = await runner.session_service.get_session(
        app_name=app_name, user_id=user_id, session_id=session_id
    )
    assert session is not None
    return dict(session.state)
