"""LLM-driven planning for the deal research agent.

The agent's *tools* are deterministic and produce cited, confidence-scored
facts. The *planner* is what decides which tool to run next, in what order,
and when to stop -- reasoning over the current deal state, coverage gaps, and
the source-reliability signal from the audit log.

Two planners implement the same `decide(context) -> Decision` contract:

- `LLMReasoningPlanner` asks Gemini to choose the next action. This is the
  genuinely agentic path: the model sees what has been done and what is still
  missing, and picks the next tool (or finishes).
- `FixedPlanner` replays a scripted action list. It is used by tests and as a
  deterministic stand-in, so the loop itself can be exercised without a model.

The LLM never invents facts here -- it only selects among deterministic tools.
That keeps the reasoning adaptive while every resulting fact stays auditable.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import urllib.error
import urllib.request

from src.config import load_env_file

# The tool catalog is also the LLM's menu: name -> when to use it.
TOOL_CATALOG: dict[str, str] = {
    "process_documents": (
        "Extract cited facts from the deal's attached diligence documents. "
        "Prefer this first when documents are available -- they are the most "
        "trustworthy source for financials and terms."
    ),
    "enrich_company": (
        "Fetch a company profile (sector, geography, summary, market position) "
        "from the company data provider. Use when the company profile is missing."
    ),
    "web_research": (
        "Search public web sources for missing or stale external fields such as "
        "investors, latest round, founders, or headquarters. Use only after "
        "documents, when important fields are still missing."
    ),
    "detect_conflicts": (
        "Compare numeric facts for the same field and flag material "
        "disagreements for human review. Run after new facts are added."
    ),
    "compute_metrics": (
        "Compute derived metrics (valuation multiple, burn as a percent of ARR) "
        "from the latest observations. Run once the input metrics exist."
    ),
    "check_staleness": (
        "Flag metric observations older than six months so they can be refreshed."
    ),
    "finish": (
        "Stop. Use when required coverage is satisfied or no remaining tool would "
        "add value."
    ),
}

TOOL_NAMES = frozenset(TOOL_CATALOG)


@dataclass(frozen=True)
class Decision:
    action: str
    rationale: str


class FixedPlanner:
    """Replays a scripted list of actions; finishes when exhausted.

    Used by tests and as a deterministic driver for the reasoning loop so the
    loop can run with no model and no network.
    """

    def __init__(self, actions: list[str]):
        self._actions = list(actions)

    def decide(self, context: dict) -> Decision:
        if not self._actions:
            return Decision("finish", "No further scripted actions.")
        return Decision(self._actions.pop(0), "Scripted action.")


class LLMReasoningPlanner:
    """Asks Gemini to choose the next tool given the current run context."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        load_env_file()
        self.api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY")
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def decide(self, context: dict) -> Decision:
        prompt = _build_planner_prompt(context)
        try:
            text = self._call_gemini(prompt)
        except RuntimeError:
            # If the model is unreachable mid-run, stop cleanly rather than
            # looping; the deterministic fallback path remains available for
            # whole runs without a key.
            return Decision("finish", "Planner unavailable; stopping.")
        payload = _parse_json(text)
        action = payload.get("action", "finish")
        if action not in TOOL_NAMES:
            action = "finish"
        return Decision(action, str(payload.get("rationale", "")).strip())

    def _call_gemini(self, prompt: str) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Gemini planning call failed: {exc}") from exc
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Gemini planning response was malformed: {data}") from exc


def _build_planner_prompt(context: dict) -> str:
    tools = "\n".join(f"- {name}: {description}" for name, description in TOOL_CATALOG.items())
    return f"""
You are the planner for an investment associate's deal-research agent. You do
NOT extract or invent any data yourself. You only choose the single next tool
to run, then you will be called again with the updated state.

Objective: {context.get('objective', '')}

Deal state:
- Company: {context.get('company')}
- Stage: {context.get('stage')}
- Documents available: {context.get('documents_available')}
- Distrusted providers (a human corrected them before; their facts must be
  re-verified): {context.get('distrusted_providers')}

Coverage gaps still open (field, status, priority, where it should come from):
{json.dumps(context.get('coverage_gaps', []), indent=2)}

Actions already taken this run, in order:
{json.dumps(context.get('actions_taken', []), indent=2)}

Most recent tool observations:
{json.dumps(context.get('last_observations', []), indent=2)}

Available tools:
{tools}

Choose the next action that most advances the objective. Prefer trustworthy
sources first (documents over enrichment over web). Do not repeat an action
that already ran and produced nothing new. When the open gaps can no longer be
improved by any tool, choose "finish".

Return JSON only:
{{"action": "<one tool name>", "rationale": "<one sentence on why>"}}
""".strip()


def _parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {"action": "finish", "rationale": "Unparseable planner response."}
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {"action": "finish", "rationale": "Unparseable planner response."}
