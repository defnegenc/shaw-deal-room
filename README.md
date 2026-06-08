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

If `SERPER_API_KEY` is not set, the agent uses mocked web-search results for repeatable demos. The agent chooses web research only after it sees stale metrics, missing important fields, or conflicting sources.

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
4. Enrich company profile from a mocked provider.
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
GEMINI_MODEL=gemini-2.0-flash
SERPER_API_KEY=...
```

The deployed app will be available at:

```text
https://your-railway-domain/ui
```

Important caveat: the MVP uses SQLite on the app filesystem. That is fine for a take-home demo, and the app seeds sample deals if the DB is empty. For production, use Postgres so created deals and review decisions persist across deploys and restarts.

## GenAI Usage Disclosure

> Please confirm/adjust this section so it reflects your own process before submitting.

Two GenAI tools were used:

- **ChatGPT / Codex** — initial architecture planning, scaffolding, and a first
  draft of the implementation.
- **Claude Code (Claude Opus / Sonnet)** — a full audit of the agent pipeline
  and the subsequent fixes: preserving human-authored facts across runs, wiring
  the source-reliability feedback loop, run atomicity, and the LLM reasoning
  loop (the agentic core). See `AUDIT_AND_FIXES.md` for the per-change record.

Main prompts were, in effect: "audit the agentic pipeline, surface where it
falls short of the brief, and fix it" and "make it a genuine reasoning loop, not
hardcoded rules." All design and implementation choices were reviewed with an
emphasis on keeping the prototype narrow, auditable, and provenance-first.
