import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from src.config import load_env_file


@dataclass(frozen=True)
class EnrichedCompany:
    sector: str
    geography: str
    summary: str
    facts: dict[str, str]
    source: str = "mock_company_provider"


MOCK_COMPANIES = {
    "OrbitGrid AI": EnrichedCompany(
        sector="Climate / Energy Software",
        geography="United States",
        summary="AI orchestration software for distributed energy storage operators.",
        facts={
            "founding_year": "2022",
            "market_position": "Early commercial traction with utility and battery fleet customers.",
        },
    ),
    "NovaLedger": EnrichedCompany(
        sector="Fintech / Compliance Automation",
        geography="United States",
        summary="Compliance automation for fintech treasury teams.",
        facts={
            "founding_year": "2021",
            "market_position": "Vertical SaaS provider serving treasury and compliance teams.",
        },
    ),
}


class CompanyEnrichmentService:
    def __init__(self) -> None:
        load_env_file()
        self._api_key = os.environ.get("GEMINI_API_KEY")
        self._model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    def enrich(self, company_name: str) -> EnrichedCompany | None:
        if company_name in MOCK_COMPANIES:
            return MOCK_COMPANIES[company_name]
        if self._api_key:
            return self._enrich_with_gemini(company_name)
        return None

    def _enrich_with_gemini(self, company_name: str) -> EnrichedCompany | None:
        prompt = f"""You are a company research assistant for a venture capital firm.
Return a JSON object with basic public information about "{company_name}".

Use this exact shape:
{{
  "sector": "brief sector or category, e.g. FinTech / AI",
  "geography": "primary country or city/country",
  "summary": "one sentence describing what the company does",
  "founding_year": "YYYY or null",
  "market_position": "one sentence about their market position or null"
}}

Only include information you are confident about from public sources.
Use null for any field you are uncertain about.
Do not fabricate facts."""

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:generateContent"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self._api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            payload = json.loads(text)
        except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError):
            return None

        sector = payload.get("sector") or ""
        geography = payload.get("geography") or ""
        summary = payload.get("summary") or ""
        if not any([sector, geography, summary]):
            return None

        facts: dict[str, str] = {}
        if payload.get("founding_year"):
            facts["founding_year"] = str(payload["founding_year"])
        if payload.get("market_position"):
            facts["market_position"] = str(payload["market_position"])

        return EnrichedCompany(sector=sector, geography=geography, summary=summary, facts=facts, source="gemini_enrichment")
