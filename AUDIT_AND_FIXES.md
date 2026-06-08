# Agent Pipeline Audit & Fixes

This document records an audit of the AI Deal Room agent pipeline, the fixes
applied, and the gaps that remain open. Each fix maps to a single commit so the
change is reviewable in isolation.

## Summary

The schema and provenance design were sound (a real time-series for evolving
metrics, a citation for every fact). The pipeline had three defects that
contradicted the product's purpose, plus a missing agentic core. All are now
fixed; the remaining items are documented limitations, not silent gaps.

## Critical findings (fixed)

### 1. Agent runs destroyed human corrections → re-validation loop
**Was:** every run called `clear_generated_intelligence`, which deleted *all*
facts for the deal — including associate corrections — then re-extracted. A
human-entered value survived exactly one run before being wiped and re-flagged.
This is the opposite of reducing manual entry.

**Fix (`Preserve human-authored facts…`):**
- Added `Fact.locked` / `MetricObservation.locked` to mark human-authored,
  canonical data.
- Review resolution writes `locked=True`.
- A locked field is *settled*: a non-locked re-extraction for the same
  `(deal, field)` is skipped, so the agent never re-opens a value a human
  decided.
- `clear_generated_intelligence` now clears only agent-regenerable data and
  preserves locked facts/sources/observations, *resolved* review items and
  conflicts (decision history), and the `agent_runs` audit trail.
- Also fixed a latent crash: `log_deal_event` used `new_id` without importing
  it, so every review resolution raised `NameError` — the entire human-in-the-
  loop path was broken.

### 2/3. Source-reliability feedback loop was dead code; the audit log was never read
**Was:** `SourceReliabilityService` and a `force_review` hook existed but were
never called. The agent never read the `DealEvent` audit log, so it could not
learn from being corrected.

**Fix (`Wire source-reliability feedback loop…`):** at the start of every run
the agent reads the audit log via `context_for_deal` and distrusts any
provider/source a human previously corrected on this deal — routing that
provider's *other* facts to review (with an explaining reason) instead of
auto-accepting. Recorded in `tools_used` and the trace.

### 4. No transaction boundary; failed runs left no trace
**Was:** the run wiped-then-rebuilt with a single commit at the end. Data loss
was avoided in practice (session close rolls back), but atomicity was implicit
and a crashed run left nothing in the audit log.

**Fix (`Make an agent run atomic…`):** the run body executes inside an explicit
try/except; on failure it rolls back and commits a `failed` `AgentRun` so the
run is recorded.

## Agentic core (added)

**Was:** the "agent" was a hardcoded `if/else` planner; the LLM was only a
fallback field *extractor*, never a decision-maker. The case study asks for an
agent that decides which actions to take, which tools to use, and adapts.

**Added (`Add LLM reasoning loop…`):** a genuine reasoning loop.
- `LLMReasoningPlanner` (Gemini) chooses the next tool from a catalog,
  reasoning over open coverage gaps, distrusted providers, and prior
  observations; the loop executes one tool, re-senses coverage, and plans
  again, up to a step cap. Every decision + rationale is logged to the trace.
- The model owns **control flow**; the deterministic tools own **fact
  production**, so reasoning is adaptive while every fact stays cited.
- Planner selection: injected planner > LLM (if `GEMINI_API_KEY`) >
  deterministic plan. With no key (tests, offline demos) the deterministic
  path runs unchanged.
- If the LLM is unreachable, the run **degrades to the deterministic plan**
  rather than producing an empty report (`Fall back to deterministic plan…`).

## The three modeling questions from the brief

- **Evolving data:** modeled as append-only `metric_observations` keyed by
  `as_of_date`; `MetricService` selects the latest. Now durable across runs —
  locked observations are never wiped, so human-confirmed values persist while
  agent-derived ones are rebuilt idempotently.
- **Documents → extracted data → schema:** `Document → DocumentChunk → Fact →
  FactSource → MetricObservation`, with `extraction_method`, `confidence_score`,
  and `quoted_evidence` on every fact. This is what powers click-through
  citations.
- **Conflict reconciliation:** `ConflictService` flags material numeric
  disagreement for human review; a human resolution locks the field as
  canonical, so the conflict does not re-appear on the next run. See gaps below
  for what reconciliation does *not* yet do.

## Remaining gaps & limitations (documented, not fixed)

These are deliberate prototype boundaries. Listed so they are explicit.

- **Conflict reconciliation is detection + human routing, not automated
  arbitration.** There is no source-authority/recency policy that auto-selects
  a winner (e.g., signed term sheet > pitch deck). Only numeric fields in
  `CONFLICT_FIELDS` conflict; text-field disagreements are invisible.
- **LLM citation integrity is not verified.** The Gemini extraction path trusts
  the model's `quoted_evidence`; it is not checked against the source text, so a
  fabricated citation is possible. (The regex path is verified.) High-value next
  fix.
- **Field definitions are duplicated** across the parser, fact service, conflict
  service, LLM extractor, and the agent's stage requirements. A single field
  registry would prevent drift. Deferred.
- **No authentication/authorization** on the API. Acceptable for a prototype;
  production needs SSO + per-deal access control.
- **Gemini key is sent as a URL query parameter** in the extraction/planner
  calls; production should use a header so keys don't land in logs.
- **Regex extraction is format-locked** to the seed documents' `Label: value`
  style and will not generalize to arbitrary PDFs; the LLM lane is the real
  path.
- **SQLite on the app filesystem** is ephemeral on Railway; production needs
  Postgres.

## Multi-agent vs. single agent

For this scope, **one orchestrator with specialized tools is correct**;
multi-agent would add coordination cost without decision-quality gain. The
"source-audit agent" people imagine already exists as `SourceReliabilityService`
— it is a pre-flight context provider to the one agent, not a separate process.
The only split worth considering later is an independent **verifier** agent that
adversarially re-checks high-stakes facts (valuations, term-sheet numbers) from
a second source before they are marked canonical.
