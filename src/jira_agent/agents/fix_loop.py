from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from jira_agent.agents.model import build_gemini_model
from jira_agent.agents.runner_utils import run_agent_once
from jira_agent.config import Settings
from jira_agent.execution.docker_runner import DockerTicketContainer
from jira_agent.logging_store.mcp_call_log import COCOINDEX_TOOL_NAMES, McpCallLog
from jira_agent.models import AttemptResult, Ticket, TriageResult
from jira_agent.tools.cocoindex_mcp import build_cocoindex_tool

FIX_LOOP_INSTRUCTION = """\
You are the Fix-Loop agent for an autonomous Jira bug-fix system. You have a
checked-out copy of the target repository and shell access inside a
disposable container. The user message tells you which attempt this is, the
ticket details, triage notes, and (on a retry) the previous attempt's failure.

Do the following, using your tools to actually take each action (don't just
describe what you would do):

1. If a repro test doesn't already exist from a prior attempt, write one
   based on the ticket's repro steps, and run it to confirm it currently
   fails. This is both a sanity check on your understanding of the bug and
   becomes the regression test.
2. Use cocoindex_query to locate the relevant code region.
3. Read the relevant file(s) with read_file, then apply a fix with write_file.
4. Re-run the repro test — it must pass. Then run the existing test suite for
   the affected area — it must not regress.
5. Once you are confident the fix is complete and validated, call
   report_validation_commands with the exact shell command to re-run the
   repro test and the exact shell command to re-run the affected test suite.
   These commands will be re-executed independently to confirm your work —
   they must actually reproduce your validation, not just something plausible.

Before calling report_validation_commands, clean up (run_shell `rm`) any
scratch files you created purely for your own investigation — throwaway
scripts you used to think through the logic, one-off debugging helpers, or
alternate repro attempts you abandoned for a later approach. The final diff
should contain only the real fix and, if useful, one properly-placed repro
test — not a trail of every intermediate script. If a command you ran (e.g.
`npm install`) modified a lockfile without you actually adding a
dependency, that's incidental — leave it, it'll be reverted automatically.
"""


def _build_prompt(
    ticket: Ticket,
    triage: TriageResult,
    attempt_number: int,
    max_attempts: int,
    prior_failure_notes: str | None,
) -> str:
    # Ticket summary/description are free text from Jira and may contain
    # literal `{...}` (e.g. Jira's {{monospace}} wiki markup) — this must go
    # in the user message, never into the agent's `instruction=`, since ADK
    # re-scans instruction text for its own `{var}` session-state
    # interpolation and raises KeyError on any stray braces it doesn't own.
    prior_section = (
        f"\nPrevious attempt failed:\n{prior_failure_notes}\nDo not repeat the same approach.\n"
        if prior_failure_notes
        else ""
    )
    return (
        f"This is attempt {attempt_number} of {max_attempts}.\n\n"
        f"Ticket:\nSummary: {ticket.summary}\nDescription: {ticket.description}\n\n"
        f"Triage notes: {triage.reasoning}\n"
        f"{prior_section}\n"
        "Begin working the ticket now."
    )


@dataclass
class ValidationCommands:
    repro_command: str | None = None
    suite_command: str | None = None


# A single tool result this large (e.g. `cat package-lock.json`, a verbose
# `npm install`/build log) can by itself push a long-running attempt's
# conversation past Gemini's 1M-token context limit, crashing the whole
# attempt. Confirmed against a real run against an Angular repo (polaris-fe)
# with "input token count exceeds the maximum number of tokens allowed
# 1048576". Cap any single tool output rather than trying to raise the
# context limit.
_MAX_TOOL_OUTPUT_CHARS = 20_000


def _truncate(text: str, limit: int = _MAX_TOOL_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit]}\n... [truncated {omitted} more characters — output too large to include in full]"


def _build_tools(
    container: DockerTicketContainer, settings: Settings, recorder: ValidationCommands
) -> list[Any]:
    def read_file(path: str) -> str:
        """Reads a file from the checked-out repo. On failure (e.g. the path
        doesn't exist), returns an "ERROR: ..." string instead of raising —
        a tool exception here would crash the entire run rather than give
        you a chance to correct course (e.g. by searching for the right
        path first). Very large files are truncated — prefer targeted
        reads/greps over catting generated files like lock files."""
        try:
            return _truncate(container.read_file(path))
        except Exception as exc:
            return f"ERROR: {exc}"

    def write_file(path: str, content: str) -> str:
        """Writes (overwrites) a file in the checked-out repo. On failure,
        returns an "ERROR: ..." string instead of raising."""
        try:
            container.write_file(path, content)
        except Exception as exc:
            return f"ERROR: {exc}"
        return f"wrote {path}"

    def run_shell(command: str) -> dict[str, Any]:
        """Runs a shell command in the checked-out repo. Returns exit_code
        and output (very large output, e.g. from `npm install`, is
        truncated — prefer quiet/summary flags where available)."""
        result = container.exec(command)
        return {"exit_code": result.exit_code, "output": _truncate(result.output)}

    def git_diff() -> str:
        """Returns the current `git diff` against the repo's checked-out commit."""
        return _truncate(container.exec("git diff").output)

    def report_validation_commands(repro_command: str, suite_command: str) -> str:
        """Records the exact shell commands used to validate the fix.

        Call this exactly once, when you believe the fix is complete. These
        commands are re-executed independently afterwards to confirm the
        result — do not report commands you haven't actually run successfully.
        """
        recorder.repro_command = repro_command
        recorder.suite_command = suite_command
        return "recorded"

    return [
        FunctionTool(read_file),
        FunctionTool(write_file),
        FunctionTool(run_shell),
        FunctionTool(git_diff),
        FunctionTool(report_validation_commands),
        build_cocoindex_tool(container, settings),
    ]


def _build_mcp_logging_callback(mcp_log: McpCallLog, attempt_number: int):
    def _log_cocoindex_calls(*, tool, args, tool_context, tool_response):
        if tool.name in COCOINDEX_TOOL_NAMES:
            mcp_log.record(attempt_number, tool.name, args, tool_response)
        return None  # never override the actual tool response

    return _log_cocoindex_calls


async def run_fix_attempt(
    container: DockerTicketContainer,
    settings: Settings,
    ticket: Ticket,
    triage: TriageResult,
    attempt_number: int,
    max_attempts: int,
    prior_failure_notes: str | None,
) -> AttemptResult:
    """Runs one Fix-Loop attempt (one ADK agent turn), then deterministically
    re-executes the commands the agent reported to decide pass/fail — the
    agent's own claim that validation passed is never trusted on its own.
    """
    recorder = ValidationCommands()
    mcp_log = McpCallLog(settings.run_log_local_dir, ticket.id)
    agent = LlmAgent(
        name="fix_loop_agent",
        model=build_gemini_model(settings),
        instruction=FIX_LOOP_INSTRUCTION,
        tools=_build_tools(container, settings, recorder),
        after_tool_callback=_build_mcp_logging_callback(mcp_log, attempt_number),
    )
    prompt = _build_prompt(ticket, triage, attempt_number, max_attempts, prior_failure_notes)
    await run_agent_once(agent, prompt, app_name="jira_agent_fix_loop")

    if not recorder.repro_command or not recorder.suite_command:
        return AttemptResult(
            attempt_number=attempt_number,
            passed=False,
            notes="Agent did not report validation commands before ending its turn.",
        )

    repro_result = container.exec(recorder.repro_command)
    suite_result = container.exec(recorder.suite_command)
    passed = repro_result.ok and suite_result.ok
    notes = (
        f"repro (`{recorder.repro_command}`): {'pass' if repro_result.ok else 'FAIL'}\n"
        f"suite (`{recorder.suite_command}`): {'pass' if suite_result.ok else 'FAIL'}"
    )
    if not passed:
        # Truncated: this text becomes the next attempt's prior_failure_notes
        # (see _build_prompt) — an oversized validation log here would bloat
        # that attempt's starting prompt the same way an untruncated tool
        # result would.
        notes += (
            f"\n\nrepro output:\n{_truncate(repro_result.output)}"
            f"\n\nsuite output:\n{_truncate(suite_result.output)}"
        )
    return AttemptResult(attempt_number=attempt_number, passed=passed, notes=notes)
