# Jira Auto-Fix Agent — Technical Spec (v1)

## 1. Overview

An autonomous agent that monitors Jira for tickets assigned to it, classifies them, and — for bug tickets with a clear reproduction path — attempts an end-to-end fix: reproduce the bug, locate the relevant code via CocoIndex, generate a fix, validate it, and open a PR for human review.

Built on **Google ADK**, using a judge-loop retry pattern with `output_key` state interpolation to pass context between the two agents.

## 2. Scope (v1)

**In scope:**
- Ticket type: **bugs only**
- Precondition: ticket must have a **clear, actionable repro path** (explicit steps, or enough detail to derive one)
- Output: a PR proposing a fix — never an auto-merge

**Out of scope (v1):**
- Feature requests, chores, and any ambiguous ticket type — triaged with a comment only, no code changes attempted
- Bug tickets without a clear repro path — flagged via comment, no fix attempted
- Auto-merging, direct pushes to protected branches
- Real-time triggering (webhooks) — polling only for now

## 3. Architecture

Two ADK agents, each with a single, focused responsibility:

| Agent | Responsibility | Codebase access |
|---|---|---|
| **Triage agent** | Classify ticket type, validate repro clarity, decide proceed/stop | None |
| **Fix-Loop agent** | Reproduce → navigate → fix → validate → retry → PR/escalate | Full (via Docker + MCP) |

State passes between them via ADK's `output_key` interpolation — the Triage agent's classification output becomes an input to the Fix-Loop agent when it dispatches.

### 3.1 High-level flow

```
Project config (Jira project ↔ GitHub repo)
        │
        ▼
Poll Jira (JQL, on interval)
        │
        ▼
Triage agent: classify + check repro clarity
        │
        ├── Bug + clear repro ──────► Fix-Loop agent
        │
        └── Feature / unclear ─────► Comment only, no status change, stop
```

### 3.2 Fix-Loop agent detail

```
Clone repo (Docker, from local mirror) → fix/<ticket-id> branch
        │
        ▼
Reproduce bug (write test from repro steps)
        │
        ▼
Query MCP / CocoIndex → find relevant code region
        │
        ▼
Generate fix → rerun repro (must pass) → run existing suite (must not break)
        │
   (retry up to 3x on failure, feeding prior failure back into next attempt)
        │
        ├── Pass ─────► Open PR (fix/<ticket-id>), never auto-merge, Jira → "In Review"
        │
        └── 3 fails ──► Comment on ticket w/ attempt summary, status unchanged
```

## 4. Ticket Classification

**Method: hybrid.**
1. Primary signal: Jira's own **Issue Type** field (Bug / Story / Task / etc.) — free, already curated by the reporter.
2. The Triage agent's LLM re-reads title + description. If the content doesn't match the declared Issue Type (e.g., a "Bug" that reads like a feature ask), it reclassifies and proceeds on the corrected type.

Repro-clarity check happens after classification, only for tickets classified as bugs: does the ticket contain steps (or sufficient detail to derive steps) that would let the agent trigger the failure? If not → comment only, stop (see §9).

## 5. Code Navigation — CocoIndex + MCP

CocoIndex owns the indexing internals — chunking strategy, BM25 + vector hybrid search, incremental updates. None of that is prescribed here; the agent only interacts with it through a stable interface:

- **Interface**: an **MCP server** exposing a query tool — send a natural-language or symbol-based query, get back relevant file paths + snippets. The Fix-Loop agent consumes this as an ADK MCP toolset.
- **Persistence**: the index itself lives as a long-running service (pgvector-backed), independent of any ticket run — nothing about a ticket run rebuilds or reconfigures it.
- **Reindexing**: only needed when the codebase changes (e.g. after a fix PR merges), not per ticket or per poll cycle. Trigger mechanism (CI step, git hook, or cron) is deferred — future scope.

## 6. Per-Ticket Run Log

Every ticket the agent touches — regardless of outcome — produces one human-readable markdown log. This is the audit trail and the source material for both the PR description and the Jira comment (write once, reuse in both places).

**Location:** `logs/<ticket-id>.md`, in a central log store — **not** inside the target repo, since triage-only and escalated tickets never produce a branch. Primary storage: **GCS** (bucket per environment). Fallback: local filesystem on the machine/instance running the agent, used automatically if GCS is unreachable — so a storage hiccup never blocks a ticket run.

**Behavior:** one file per ticket, appended with a new "Run" section on each (re)processing — reopened tickets keep full history rather than losing prior attempts.

**Template:**

```markdown
# TICKET-123 — Null pointer on checkout when cart is empty

**Jira:** [link] · **Type:** Bug (confirmed) · **First seen:** 2026-07-09 14:02 UTC

## Run 1 — 2026-07-09 14:03–14:11 UTC

**Summary:** Reported crash occurs when checkout is triggered on an empty
cart. Repro steps were clear (empty cart → click checkout → 500 error).

**Classification:** Bug, Jira Issue Type matched, repro steps present.

**Reproduction:** Wrote `test_checkout_empty_cart.py` — confirmed failing
against current `main`.

**Code navigation (via MCP):** Located `checkout/service.py:142`,
`checkout/validators.py:30` as the relevant region.

**Attempts:**
| # | Result | Notes |
|---|---|---|
| 1 | Fail | Fix addressed wrong validator, repro still failed |
| 2 | Pass | Added empty-cart guard in `validators.py`, repro + suite pass |

**Outcome:** PR opened → `fix/TICKET-123` → [PR link]
**Branch:** `fix/TICKET-123` · **Commits:** 2 · **Files changed:** 2
**Jira status:** → In Review
```

**Why this matters:**
- Gives a human reviewer the *reasoning trail*, not just a diff — why the agent believed this was the right fix, and what it tried and discarded along the way.
- Makes escalations genuinely useful: a 3-failed-attempts case shows exactly what was tried and why, not just "I gave up."
- Single source of truth reused in the PR description and the Jira comment, so the narrative never drifts between the two.

## 7. Execution Environment

- **Docker container per ticket run.** Fresh container, dies after the run. Enables safe parallel execution across tickets without state leakage (stale deps, file locks, side effects from a bad test).
- **Python package management: `uv`.** All dependency installation and virtualenv management inside the execution container — and in the agent codebase itself — uses `uv`, consistent with existing tooling conventions. No `pip`/`poetry` in this stack.
- **Repo checkout strategy — avoid redundant clones:**
  - A persistent **bare mirror** of each configured repo is kept on the host (or a shared volume), synced via `git fetch` once per poll cycle — not per ticket.
  - Each ticket container clones from that local mirror (`git clone --reference <mirror> --dissociate`), not from GitHub directly. Fast, local, no per-ticket network round-trip or rate-limit exposure, even under concurrent runs.

## 8. Validation Strategy

A fix is only proposed once **proven**, not just generated:

1. **Reproduce first** — the agent writes a test/script from the ticket's repro steps and confirms it *fails* against current code. This is both a sanity check on the agent's understanding and becomes the regression test.
2. **Apply fix.**
3. **Rerun the repro** — must now pass.
4. **Run the existing test suite** for the affected area — must not introduce regressions.

If reproduction itself fails (agent can't trigger the bug) or the fix doesn't clear validation, that counts as a failed attempt.

**Retry policy:** up to **3 attempts**. Each retry feeds the previous failure back into the next attempt. After 3 failures, the agent stops and escalates.

## 9. Jira Interaction Matrix

| Outcome | Jira action |
|---|---|
| Not a bug / ambiguous type | Comment explaining triage decision. Status unchanged. |
| Bug, but repro unclear | Comment requesting specifics. Status unchanged. |
| Bug, clear repro, fix validated | PR link posted as comment (drawn from the run log). Status → "In Review". |
| Bug, clear repro, 3 fix attempts failed | Comment summarizing what was tried and why (drawn from the run log). Status unchanged. |

## 10. Configuration

**Project mapping** (drives multi-repo support — keyed by Jira project, not hardcoded to one repo):

```yaml
projects:
  - jira_project_key: "ENG"
    github_repo: "org/backend-service"
    default_branch: "main"
  - jira_project_key: "PLAT"
    github_repo: "org/platform-core"
    default_branch: "main"
```

**Other config:**
- `poll_interval_minutes`: JQL polling frequency
- `max_concurrent_tickets`: cap on parallel Fix-Loop runs (configurable)
- `max_fix_attempts`: 3 (default, configurable)

**Credentials:** `.env` file (gitignored) for Jira API token + GitHub token in v1. Vertex AI auth uses standard GCP Application Default Credentials / service account (project ID + region config, no API key in `.env`). Migration to GCP Secret Manager is the planned upgrade path once this moves past prototype (natural fit given existing Vertex AI usage).

## 11. Tech Stack Summary

| Layer | Choice |
|---|---|
| Orchestration | Google ADK |
| LLM | Vertex AI, Gemini 3 Flash (both Triage and Fix-Loop agents) |
| Code navigation | CocoIndex (internals abstracted) + pgvector, via MCP server |
| Execution | Docker, one container per ticket run |
| Python package manager | `uv` |
| Trigger | Polling (JQL) |
| VCS | Git, local mirror + per-ticket clone, PR-based delivery |
| Per-ticket logs | Markdown, GCS (primary) with local-instance fallback |
| Secrets | `.env` (v1) → GCP Secret Manager (future) |

## 12. Open Items / Future Scope

- Reindex trigger mechanism after a merge (CI step vs. git hook vs. cron) — not decided
- Per-attempt execution timeout handling
- Observability/logging integration (existing Grafana/Tempo/Loki/Prometheus/Alloy stack — reuse likely but unconfirmed)
- Migration from polling to Jira webhooks once infra supports a public endpoint
- Expanding scope beyond bugs (small feature requests) once the bug-fix loop is validated in production
