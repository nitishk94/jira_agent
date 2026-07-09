from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from jira_agent.config import Settings
from jira_agent.models import AttemptResult, Ticket, TriageResult


@dataclass
class RunLog:
    """Accumulates one ticket run's narrative; rendered as one `## Run N`
    markdown section (spec §6) and appended to the ticket's log file — the
    single source of truth reused in both the PR description and Jira
    comment, so the narrative never drifts between the two.
    """

    ticket: Ticket
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    triage: TriageResult | None = None
    reproduction_note: str = ""
    code_navigation_note: str = ""
    attempts: list[AttemptResult] = field(default_factory=list)
    outcome_line: str = ""
    jira_status_line: str = ""
    ended_at: datetime | None = None

    def record_triage(self, triage: TriageResult) -> None:
        self.triage = triage

    def record_reproduction(self, note: str) -> None:
        self.reproduction_note = note

    def record_code_navigation(self, note: str) -> None:
        self.code_navigation_note = note

    def record_attempt(self, attempt: AttemptResult) -> None:
        self.attempts.append(attempt)

    def finish(self, outcome_line: str, jira_status_line: str) -> None:
        self.outcome_line = outcome_line
        self.jira_status_line = jira_status_line
        self.ended_at = datetime.now(timezone.utc)

    def render_header(self) -> str:
        t = self.ticket
        return (
            f"# {t.id} — {t.summary}\n\n"
            f"**Jira:** [{t.id}]({t.url}) · **Type:** {t.issue_type} · "
            f"**First seen:** {self.started_at:%Y-%m-%d %H:%M} UTC\n"
        )

    def render_section(self, run_number: int) -> str:
        ended = self.ended_at or datetime.now(timezone.utc)
        lines = [f"\n## Run {run_number} — {self.started_at:%Y-%m-%d %H:%M}–{ended:%H:%M} UTC\n"]

        if self.triage is not None:
            classification = "Bug" if self.triage.is_bug else "Not a bug"
            matched = "Jira Issue Type matched" if self.triage.issue_type_matched else "reclassified"
            repro = "repro steps present" if self.triage.repro_clear else "repro unclear"
            lines.append(f"\n**Classification:** {classification}, {matched}, {repro}.\n")
            lines.append(f"\n**Summary:** {self.triage.reasoning}\n")

        if self.reproduction_note:
            lines.append(f"\n**Reproduction:** {self.reproduction_note}\n")

        if self.code_navigation_note:
            lines.append(f"\n**Code navigation (via MCP):** {self.code_navigation_note}\n")

        if self.attempts:
            lines.append("\n**Attempts:**\n| # | Result | Notes |\n|---|---|---|\n")
            for attempt in self.attempts:
                result = "Pass" if attempt.passed else "Fail"
                notes = attempt.notes.replace("\n", " ").replace("|", "\\|")
                lines.append(f"| {attempt.attempt_number} | {result} | {notes} |\n")

        if self.outcome_line:
            lines.append(f"\n**Outcome:** {self.outcome_line}\n")
        if self.jira_status_line:
            lines.append(f"**Jira status:** {self.jira_status_line}\n")

        # Hidden marker (invisible when rendered) recording the ticket's
        # `updated_at` as of this run — lets RunLogStore.last_processed_at
        # tell "already handled, nothing changed" apart from "reopened /
        # edited since" without a separate state store (spec §6: reopened
        # tickets should be reprocessed, not silently skipped forever).
        lines.append(f"<!-- ticket_updated_at: {self.ticket.updated_at.isoformat()} -->\n")

        return "".join(lines)


class RunLogStore:
    """Writes/reads per-ticket run logs. Tries GCS first when a bucket is
    configured, falling back to the local filesystem automatically on any
    GCS error — a storage hiccup should never block a ticket run (spec §6).
    """

    def __init__(self, settings: Settings) -> None:
        self._bucket_name = settings.run_log_gcs_bucket
        self._local_dir = Path(settings.run_log_local_dir)

    def last_processed_at(self, ticket_id: str) -> datetime | None:
        """The ticket's `updated_at` as of the most recent run in its log,
        or None if the ticket has never been processed. Used by the
        orchestrator to skip tickets that haven't changed since last time.
        """
        existing = self._read_existing(f"{ticket_id}.md")
        matches = re.findall(r"<!-- ticket_updated_at: (.+?) -->", existing)
        return datetime.fromisoformat(matches[-1]) if matches else None

    def write(self, run_log: RunLog) -> str:
        filename = f"{run_log.ticket.id}.md"
        existing = self._read_existing(filename)
        run_number = existing.count("## Run ") + 1
        content = existing + run_log.render_section(run_number) if existing else (
            run_log.render_header() + run_log.render_section(run_number)
        )
        return self._write(filename, content)

    def _read_existing(self, filename: str) -> str:
        if self._bucket_name:
            try:
                text = self._read_gcs(filename)
                if text is not None:
                    return text
            except Exception:
                pass  # GCS unreachable — fall through to local
        local_path = self._local_dir / filename
        return local_path.read_text(encoding="utf-8") if local_path.exists() else ""

    def _write(self, filename: str, content: str) -> str:
        if self._bucket_name:
            try:
                self._write_gcs(filename, content)
                return f"gs://{self._bucket_name}/logs/{filename}"
            except Exception:
                pass  # GCS unreachable — fall back to local automatically
        self._local_dir.mkdir(parents=True, exist_ok=True)
        local_path = self._local_dir / filename
        local_path.write_text(content, encoding="utf-8")
        return str(local_path)

    def _read_gcs(self, filename: str) -> str | None:
        from google.cloud import storage

        client = storage.Client()
        blob = client.bucket(self._bucket_name).blob(f"logs/{filename}")
        return blob.download_as_text() if blob.exists() else None

    def _write_gcs(self, filename: str, content: str) -> None:
        from google.cloud import storage

        client = storage.Client()
        blob = client.bucket(self._bucket_name).blob(f"logs/{filename}")
        blob.upload_from_string(content, content_type="text/markdown")
