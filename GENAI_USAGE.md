# GenAI Usage Disclosure

This document discloses how generative AI was used to build the AI Deal Room,
the representative prompts used, and the general prompting approach. It covers
two distinct kinds of usage: **AI as a development tool** (helping write the
code) and **AI inside the product at runtime** (the agent itself).

## Tools used

| Tool | Role | Where |
|---|---|---|
| **ChatGPT / Codex** (OpenAI) | Initial architecture planning, scaffolding of the data model and services, and a first draft of the deterministic pipeline. | Development |
| **Claude Code** (Anthropic — Claude Opus 4.x and Sonnet) | The full audit of the inherited pipeline, all subsequent fixes, the agentic reasoning loop, the data-model changes, security hardening, the UI, the web-research rebuild, persistence, and the iterative bug-driven debugging. The majority of the engineering in this repo. | Development |
| **Google Gemini** (`gemini-2.5-flash`) | Runs *inside the product*: the reasoning planner that chooses which tool to run next, plus structured extraction from documents/images, web-search snippets, and company enrichment. | Runtime (product dependency) |
| **Serper** (Google Search API) | Runtime web search the agent calls before extraction. Not an LLM, but part of the AI pipeline. | Runtime (product dependency) |

All design and implementation decisions were reviewed and directed by the
author. AI was used to accelerate and pressure-test the work, not to make
final calls unsupervised.

## What the LLMs were used for

### As a development tool
- Architecture and data-model design (provenance-first schema, temporal metrics).
- Scaffolding services, parsers, and the FastAPI app.
- A full audit of the inherited "agent" and a fix for every issue found
  (human corrections being wiped, dead source-reliability loop, non-atomic
  runs, duplicate facts, unpersisted computed metrics, empty re-runs).
- Building the genuine LLM reasoning loop and its deterministic fallback.
- Test-driven development: a failing test written first for each behavioral fix.
- Security review (keys moved to headers, error messages sanitized, path-traversal
  allowlist) and documentation.

### Inside the product at runtime
The product is deliberately a **hybrid**: the model owns *control flow*, while
deterministic tools own *fact production*. Specifically, Gemini is used for:
- **Planning** — choosing the next tool from a catalog based on live coverage
  gaps, what's already been tried, and which sources a human previously corrected.
- **Extraction** — pulling structured, cited facts from messy documents, image
  uploads, and web-search snippets that regex can't generalize over.
- **Enrichment** — a company-profile fallback for companies outside the demo set.

Every model-produced fact carries a source citation, a confidence score, and a
review status; low-confidence or conflicting values are routed to a human. The
model never decides what is *true*, only what to *do next*.

## Representative prompts

These are real prompts from the build, lightly cleaned. They are representative
of an iterative, conversational session rather than a single specification.

**Direction / architecture**
- "Create a Git repo for this and do a whole audit of the agentic pipeline in
  line with these instructions — tell me where it could be way better, then fix
  what you find and document the fixes."
- "Why doesn't it have an agentic reasoning loop? It should reason through which
  tools to use instead of just having deterministic rules."
- "Make any changes to how the data is structured and stored so it supports the
  new agent pipeline — scalable, but simple enough to actually be useful."
- "Make sure evolving data, how documents fit the schema, and how conflicting
  data is reconciled are all handled; do a security review; and make sure it
  actually reduces manual validation work."

**Auditing / verifying (the largest share of prompts)**
- "Get rid of anything that's hard-coded. Is there anything that still hard-codes
  regex? Did we completely get rid of regex?"
- "Is the agent actually functioning like we claim? Is everything actually being
  written into a SQLite database? What is the data structure? Is it fixed, or are
  we changing it with what we find?"
- "Is it agentic beyond doing one thing if it finds documents and another if it
  doesn't? Is it actually going back and revising, or just checking for
  documents? Is the agent stupid?"

**Bug-driven (reported from the running app)**
- "There are two different market positions and two latest rounds in the accepted
  facts — why are there duplicates? It keeps finding the same things."
- "When I do research and refresh the page, it disappears. Why is that not writing
  to the database?"
- "It couldn't find the Cognition website — it's very clear which company I mean."
- "It couldn't find founders, but when I Google 'cognition founders' it comes up —
  can it not edit its Google searches?"
- "Computed metrics isn't actionable — I don't understand what 'no computed
  metrics' means or how to make it compute them."

**UX**
- "Make the Run Agent button full width; hide everything under it until I run the
  agent; while it's running, show the steps it's going through."
- "Move Run Agent to the top bar next to Add Company, but don't make it clickable
  until I select a company."
- "For the editable fields, add a little edit affordance you click — otherwise it
  looks like I have to fill them in."

## How I prompted, in general

- **Iterative and incremental.** Small steps, each prompt reacting to the running
  application rather than one big up-front spec.
- **Verification-first and skeptical.** Repeatedly asked "is this actually true /
  actually working?" and required claims to be checked against the live database
  and real runs — not asserted. This surfaced real bugs (computed metrics never
  persisted; low-stage re-runs returning empty).
- **Bug-driven from real use.** Drove fixes by reporting concrete failures
  observed in the UI (duplicates, disappearing data, missing website/founders).
- **Adversarial about authenticity.** Pushed hard on whether the system was
  *genuinely* agentic and whether data was *genuinely* persisted, and asked for
  honest limitations rather than a polished story.
- **Product- and UX-minded.** Specified concrete interaction details and flows,
  not just functionality.
- **Scoped and pragmatic.** Asked for trade-offs and disclaimers, capped scope
  ("do it if it's easy"), and preferred small, reviewable changes.
- **Honesty over polish.** Asked for the docs to be made fully reflective of the
  code and for mismatches to be flagged rather than hidden.

The methodology was test-first where behavior changed; see `AUDIT_AND_FIXES.md`
for the per-change record mapped to commits, and `ARCHITECTURE.md` for the design.
