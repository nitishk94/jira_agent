from __future__ import annotations

from google.adk.agents import LlmAgent

from jira_agent.agents.model import build_gemini_model
from jira_agent.agents.runner_utils import run_agent_once
from jira_agent.config import Settings
from jira_agent.models import Ticket, TriageResult

TRIAGE_INSTRUCTION = """\
You are the Triage agent for an autonomous Jira bug-fix system.

You will be given a Jira ticket's Issue Type, title, and description. Decide:

1. `is_bug`: Is this genuinely a bug report, based on the title/description content
   — not just the declared Issue Type? A ticket declared "Bug" that actually reads
   like a feature request should be marked `is_bug=false`, and vice versa.
2. `issue_type_matched`: Did the declared Issue Type agree with your judgment in (1)?
3. `repro_clear`: Only meaningful when `is_bug` is true. Does the ticket contain
   explicit repro steps, or enough concrete detail (inputs, environment, observed
   vs. expected behavior) that someone could derive steps to trigger the failure?
   If the ticket is vague ("sometimes crashes", "doesn't work right") mark this false.
4. `reasoning`: A short (2-4 sentence) explanation a human reviewer or the ticket
   reporter could read, justifying the decision above. If `is_bug` is false or
   `repro_clear` is false, explain what's missing or why it was reclassified.

Respond only via the structured output schema.
"""


def build_triage_agent(settings: Settings) -> LlmAgent:
    return LlmAgent(
        name="triage_agent",
        model=build_gemini_model(settings),
        instruction=TRIAGE_INSTRUCTION,
        output_schema=TriageResult,
        output_key="triage_result",
    )


async def run_triage(ticket: Ticket, settings: Settings) -> TriageResult:
    agent = build_triage_agent(settings)
    prompt = (
        f"Issue Type: {ticket.issue_type}\n"
        f"Title: {ticket.summary}\n"
        f"Description:\n{ticket.description}\n"
    )
    state = await run_agent_once(agent, prompt, app_name="jira_agent_triage")
    return TriageResult(**state["triage_result"])
