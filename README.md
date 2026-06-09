# AI Deal Room MVP

Lightweight prototype for an Associate-facing AI Deal Room. It centralizes seed deals and local documents, extracts structured company facts, enriches company metadata from a mocked provider, computes investment metrics, and highlights conflicts, stale data, and low-confidence values.

## Quick Start

```bash
python -m scripts.build_db
python -m scripts.run_agent --deal-id d_orbit
```

Run the stale-data example:

```bash
python -m scripts.run_agent --deal-id d_nova
```

Run the no-documents public-research example:

```bash
python -m scripts.run_agent --deal-id d_rogo
```

Run the same "start from scratch" flow for any startup:

```bash
python -m scripts.run_agent --company "Rogo" --website "https://rogo.ai"
python -m scripts.run_agent --company "Ramp" --website "https://ramp.com"
```

You can also add a company from the browser UI, then run the agent. If `SERPER_API_KEY` is set, the web research tool uses live search. If it is not set, the demo falls back to mocked results for the seeded companies only.

Return JSON instead of the formatted CLI report:

```bash
python -m scripts.run_agent --deal-id d_orbit --json
```

Optional Gemini Flash fallback:

```bash
cp .env.example .env
# Add GEMINI_API_KEY to .env
python -m scripts.run_agent --deal-id d_orbit --docs data/documents/orbit_narrative_update_2026.txt
```

Regex extraction runs first. If `GEMINI_API_KEY` is present, Gemini Flash is only called for fields the deterministic parser missed. LLM-derived facts are marked with `gemini_flash_fallback` internally and are treated as review-oriented rather than silently canonical.

Optional live web search:

```bash
# Add this to .env to use Serper instead of mocked web-search results
SERPER_API_KEY=your_key_here
```

When `SERPER_API_KEY` is set, the agent runs a live Google search through Serper and then uses Gemini to extract structured facts (sector, headquarters, founders, latest round, investors, headcount) from the result snippets — there is no hardcoded list of cities, investors, or founders. If the search is site-restricted by the company website and returns nothing (e.g. a mistyped domain), it retries without the site filter. If `SERPER_API_KEY` is not set, the agent falls back to mocked web-search results for the three seeded demo companies only. The agent chooses web research only after it sees stale metrics, missing important fields, or conflicting sources.

Start the API:

```bash
python -m uvicorn src.api.main:app --port 8000
```

Then open `http://127.0.0.1:8000/docs` and call:

```text
POST /agent-runs/update-deal-intelligence
```

Example body:

```json
{
  "deal_id": "d_orbit"
}
```

## What the Demo Shows

- `d_orbit`: processes two documents, extracts cited facts, flags a conflicting pre-money valuation, highlights a low-confidence headcount extraction, and computes valuation/burn metrics.
- `d_nova`: processes an older diligence memo and flags stale ARR, headcount, valuation, growth, and burn observations.
- `d_rogo`: starts from only company name and website, then chooses web research because no diligence materials are available and important fields are missing.
- The agent now exposes an explicit plan. It chooses document processing when diligence files are available, enrichment when company profile fields are missing, and web research when values are stale, missing, or conflicted.

## Browser Demo

With the API server running, open:

```text
http://127.0.0.1:8000/ui
```

The UI is intentionally lightweight: it is an Associate workbench for running the planning agent and reviewing accepted facts, computed metrics, stale values, conflicts, review items, and citations.

The `Diligence Materials` panel links to the exact local documents the agent reads. Use `View` to inspect the source text in the browser and `Download` to save a copy.

## Architecture

The agent has two planning modes behind one interface:

- **LLM reasoning loop** (default when `GEMINI_API_KEY` is set): the model
  chooses the next tool to run from a catalog, observes the result, re-senses
  the deal, and decides again until it finishes — a genuine agentic loop. Every
  decision and rationale is logged to the run trace.
- **Deterministic plan** (fallback for no-key / offline / tests, and if the LLM
  is unreachable): the stage-aware checklist below.

In both modes the **tools are deterministic and produce cited, confidence-scored
facts** — the model decides *what to do*, never *what is true*. The agent also
reads the deal audit log first, so providers a human previously corrected are
distrusted on later runs. See [ARCHITECTURE.md](ARCHITECTURE.md) and
[AUDIT_AND_FIXES.md](AUDIT_AND_FIXES.md).

The deterministic tools, in the fallback order:

1. Inspect deal state.
2. Process uploaded or inferred local documents.
3. Extract structured facts with regex-based parsers.
4. Enrich company profile — a mocked provider for the seeded demo companies, and a Gemini lookup as the fallback for any other company when `GEMINI_API_KEY` is set.
5. Detect conflicts against existing facts.
6. Compute derived metrics.
7. Create review items for stale, conflicting, or low-confidence values.
8. Emit a cited Deal Intelligence Report.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design rationale.

## Tests

```bash
python -m unittest
```

## Deploy on Railway

This app can be deployed directly on Railway.

1. Push the repo to GitHub.
2. Create a new Railway project from the GitHub repo.
3. Railway will use `railway.json` and run:

```bash
python -m uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

4. Add environment variables in Railway:

```bash
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
SERPER_API_KEY=...
# Optional. The app resets to a clean seeded state on every startup by default
# so demo sessions never accumulate stale data. Set DEAL_ROOM_RESET=0 to keep
# data across restarts.
DEAL_ROOM_RESET=1
```

The deployed app will be available at:

```text
https://your-railway-domain/ui
```

Important caveat: the MVP uses SQLite on the app filesystem and, by default,
resets to the seeded demo companies on every startup (`DEAL_ROOM_RESET=1`). That
keeps the demo clean but means companies you add do not survive a restart. For a
persistent multi-user deployment, set `DEAL_ROOM_RESET=0` and move to Postgres so
created deals and review decisions persist across deploys and restarts.

## GenAI Usage Disclosure

See [GENAI_USAGE.md](GENAI_USAGE.md) for the full disclosure — tools used, what
the LLMs did (in development and inside the product), representative prompts, and
the general prompting approach. Summary below.

Two GenAI tools were used on this project:

**ChatGPT / Codex** — initial architecture planning, scaffolding of the data
model and services, and a first draft of the deterministic pipeline.

**Claude Code (Claude Opus 4.x / Sonnet)** — a full audit of the agent pipeline
followed by the fixes and the agentic build-out. Specifically:
- preserving human-authored (`locked`) facts across agent runs so corrections
  are not wiped and re-validated;
- wiring the source-reliability feedback loop (the agent reads the deal audit
  log and distrusts previously-corrected providers);
- making a run atomic and recording failed runs;
- adding the **LLM reasoning loop** (the agentic core) with a deterministic
  fallback and a no-progress guard;
- the architecture/audit documentation.

The work was done test-first; see `AUDIT_AND_FIXES.md` for the per-change record
mapped to commits.

Representative prompts:
- "Do a whole audit of the agentic pipeline and tell me where it could be way
  better" — and, on the findings, "before flagging, fix them and document the
  fixes."
- "Why doesn't it have an agentic reasoning loop? It should reason through which
  tools to use instead of deterministic rules."
- "Make sure the modeling of evolving data, how documents fit the schema, and
  how conflicting data is reconciled are all accounted for; do a security
  review; and make sure it actually reduces manual work."
- "Make any data-structure changes needed to support the new pipeline —
  scalable but simple enough to be useful."

All design and implementation choices were reviewed by the author with an
emphasis on keeping the prototype narrow, auditable, and provenance-first.
