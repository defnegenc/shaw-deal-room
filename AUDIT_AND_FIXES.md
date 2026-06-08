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

## Removing company-specific hardcoding (fixed)

**Was:** even with a live Serper key, web research threw away most of what it
found. Extraction was a set of fixed lookup tables — a 5-city headquarters list,
a 7-name investor whitelist, and a founders list that only contained Rogo's
founders — so it could only "find" facts for the three demo companies. Company
enrichment was a 2-company dict that returned `None` for anything else.

**Fix:**
- Web-snippet extraction now goes through Gemini (`extract_web_snippet_facts`):
  Serper fetches the real search results, the model extracts sector,
  headquarters, founders, latest round, investors, headcount, founding year, and
  market position with per-fact confidence and a quoted snippet. The hardcoded
  city/investor/founder tables are deleted. One general-purpose regex (a
  `$X{M,B} Series Y` round pattern) remains only as the no-LLM fallback.
- A mistyped/empty `site:` query now retries without the site filter instead of
  silently returning nothing.
- `CompanyEnrichmentService` keeps the mock for the seeded demos and falls back
  to a Gemini lookup for any other company; the fact records which path produced
  it (`mock_company_provider` vs `gemini_enrichment`), so the source label is
  always truthful.
- When neither key is set, web research returns empty **without** fabricating a
  "cannot identify company" review item — the cause is missing config, not
  ambiguity.

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
- **LLM citation integrity is not verified.** All three Gemini paths (document
  fallback, image/vision, web-snippet extraction) trust the model's
  `quoted_evidence`; it is not checked back against the source text/snippet, so a
  fabricated citation is possible. (The regex document path is verified.)
  Highest-value next fix.
- **Field definitions are duplicated** across the parser, fact service, conflict
  service, LLM extractor, and the agent's stage requirements. A single field
  registry would prevent drift. Deferred.
- **No authentication/authorization** on the API. Acceptable for a prototype;
  production needs SSO + per-deal access control.
- **Gemini key is sent as a URL query parameter** in the extraction/planner
  calls; production should use a header so keys don't land in logs.
- **Document regex extraction is format-locked** to the seed documents'
  `Label: value` style and will not generalize to arbitrary PDFs; the Gemini
  lane is the real path for messy documents. The money-scaling helper only
  handles `K`/`M` suffixes (not `B`), so a `$1.2B` in a *document* would mis-parse
  — web research handles billions, documents do not yet.
- **SQLite on the app filesystem** is ephemeral on Railway; production needs
  Postgres.

## What is and isn't hardcoded (current state)

**Still intentionally hardcoded (correct for the scope):**
- `MOCK_WEB_RESULTS` (3 companies) and `MOCK_COMPANIES` (2 companies) — *fallbacks
  only*, used when the relevant API key is absent, for repeatable offline demos.
- `CONFLICT_FIELDS` (5 numeric fields) and the 5% conflict tolerance — the
  numeric fields where contradictions matter for a screen.
- Deal stage names and per-stage required fields — the deal model's enum.
- The deterministic fallback plan order — the no-LLM checklist.
- Confidence constants per extraction method, and the 0.80 review threshold /
  6-month staleness window.

**No longer hardcoded (fixed this session):** web-research city/investor/founder
tables, and single-company enrichment — both now run through Serper + Gemini for
any company.

## Did we get rid of regex? (No — and that is deliberate)

Regex was never the problem; *company-specific* regex/lookup tables were. After
the fixes, regex survives in five places, all general-purpose:
1. `document_parser.py` — the deterministic `Label: value` document-extraction
   lane (the cheap, verifiable front of the two-lane extractor).
2. `web_research.py` — one `$X{M,B} Series Y` round pattern, no-LLM fallback only.
3. `review_resolution.py` — normalizing an associate's free-text correction
   (number+magnitude, ISO date, `Qn YYYY`, year).
4. `reasoning.py` / `llm_extraction.py` — unwrapping a JSON object from an LLM
   response (`{ … }`).
5. `api/main.py` — sanitizing uploaded filenames (security).

None of these key off a company name. The deterministic document lane is a
feature, not debt: it keeps high-confidence extraction free and auditable, with
the LLM lane filling only the gaps.

## Demo disclaimers (state these when presenting)

- **API keys drive behavior.** With `GEMINI_API_KEY` + `SERPER_API_KEY` set, the
  agent reasons with Gemini and researches the live web for *any* company.
  Without them it runs the deterministic plan and returns mocked results for the
  three seeded companies only — the demo still works offline, just narrower.
- **Web/LLM facts are unverified evidence.** Live web and Gemini-extracted facts
  enter as `review_required`, not canonical — the citation quote is the model's,
  not yet checked against the source.
- **Enrichment is mocked for the seed companies**, Gemini-backed for others; it
  is not a real PitchBook/Crunchbase integration (that sits behind the same
  provider boundary).
- **No auth, single user, SQLite.** Anyone reaching the API can read/edit/delete
  deals; data is not durable across Railway redeploys.
- **The live "agent steps" shown in the UI are a progress indicator** for the
  pipeline stages, rendered while the run is in flight; the authoritative,
  actually-executed plan and rationale render when the run returns.

## If we had more time (highest-value first)

1. **Verify LLM citations** against the source text/snippet before a fact is
   storable — closes the one path where a number could be fabricated.
2. **Source-authority reconciliation:** auto-rank conflicts by source tier
   (signed term sheet > data-room export > web) and recency instead of always
   routing to a human.
3. **Single field registry** to remove the field-definition duplication across
   parser, fact/conflict services, LLM extractor, and stage requirements.
4. **Stream real agent steps** over SSE so the UI shows the genuine tool
   sequence live rather than a staged indicator.
5. **Auth + Postgres + per-deal access control** for a real multi-user internal
   tool, and move the Gemini key from URL query param to a header.
6. **Promote repeated facts to typed tables** (`company_people`,
   `company_signals`) once the team proves they are queried often.
7. **An adversarial verifier agent** that re-checks high-stakes numbers
   (valuations, term-sheet terms) from a second source before they go canonical.

## Multi-agent vs. single agent

For this scope, **one orchestrator with specialized tools is correct**;
multi-agent would add coordination cost without decision-quality gain. The
"source-audit agent" people imagine already exists as `SourceReliabilityService`
— it is a pre-flight context provider to the one agent, not a separate process.
The only split worth considering later is an independent **verifier** agent that
adversarially re-checks high-stakes facts (valuations, term-sheet numbers) from
a second source before they are marked canonical.
