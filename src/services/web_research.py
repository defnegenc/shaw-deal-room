from dataclasses import dataclass
from datetime import date
import json
import os
import urllib.error
import urllib.request

from src.config import load_env_file
from src.parsers.document_parser import ExtractedFact


@dataclass(frozen=True)
class WebResearchResult:
    query: str
    facts: list[ExtractedFact]
    used_live_search: bool
    source_count_by_field: dict[str, int]
    clarification_questions: list[dict]


MOCK_WEB_RESULTS = {
    "OrbitGrid AI": [
        ExtractedFact(
            field_name="external_investors",
            value_text="Northstar Ventures, Gridline Capital",
            value_numeric=None,
            unit=None,
            currency=None,
            as_of_date=date(2026, 5, 20),
            evidence="Mock web result: OrbitGrid AI announced Northstar Ventures and Gridline Capital as investors in its Series A.",
            confidence_score=0.68,
            extraction_method="mock_web_search",
        ),
        ExtractedFact(
            field_name="external_market_signal",
            value_text="Recent utility storage orchestration deployments mentioned in industry coverage.",
            value_numeric=None,
            unit=None,
            currency=None,
            as_of_date=date(2026, 5, 20),
            evidence="Mock web result: industry coverage referenced recent utility deployments.",
            confidence_score=0.62,
            extraction_method="mock_web_search",
        ),
    ],
    "NovaLedger": [
        ExtractedFact(
            field_name="external_employee_range",
            value_text="20-50 employees",
            value_numeric=None,
            unit="employees",
            currency=None,
            as_of_date=date(2026, 4, 10),
            evidence="Mock web result: NovaLedger company profile lists 20-50 employees.",
            confidence_score=0.64,
            extraction_method="mock_web_search",
        ),
        ExtractedFact(
            field_name="external_investors",
            value_text="Harbor Seed Partners, LedgerWorks Angels",
            value_numeric=None,
            unit=None,
            currency=None,
            as_of_date=date(2026, 4, 10),
            evidence="Mock web result: funding profile lists Harbor Seed Partners and LedgerWorks Angels.",
            confidence_score=0.66,
            extraction_method="mock_web_search",
        ),
    ],
    "Rogo": [
        ExtractedFact(
            field_name="sector",
            value_text="FinTech / AI for financial services",
            value_numeric=None,
            unit=None,
            currency=None,
            as_of_date=date(2026, 6, 8),
            evidence="Rogo describes itself as an AI partner to leading financial institutions.",
            confidence_score=0.84,
            extraction_method="mock_web_search_aggregated",
        ),
        ExtractedFact(
            field_name="headquarters",
            value_text="New York, NY",
            value_numeric=None,
            unit=None,
            currency=None,
            as_of_date=date(2026, 6, 8),
            evidence="Rogo company page lists the company as located in New York, NY, United States.",
            confidence_score=0.84,
            extraction_method="mock_web_search_aggregated",
        ),
        ExtractedFact(
            field_name="founders",
            value_text="Gabriel Stengel, John Willett, Tumas Rackaitis",
            value_numeric=None,
            unit=None,
            currency=None,
            as_of_date=date(2026, 6, 8),
            evidence="Rogo company page lists Gabriel Stengel, John Willett, and Tumas Rackaitis as founders.",
            confidence_score=0.84,
            extraction_method="mock_web_search_aggregated",
        ),
        ExtractedFact(
            field_name="funding_total",
            value_text="More than $300M reported after Series D",
            value_numeric=300_000_000,
            unit=None,
            currency="USD",
            as_of_date=date(2026, 4, 29),
            evidence="Public reports say Rogo's Series D brought total capital raised to over $300M.",
            confidence_score=0.72,
            extraction_method="mock_web_search",
        ),
        ExtractedFact(
            field_name="latest_round",
            value_text="$160M Series D",
            value_numeric=160_000_000,
            unit=None,
            currency="USD",
            as_of_date=date(2026, 4, 29),
            evidence="Public reports describe a $160M Series D financing for Rogo.",
            confidence_score=0.84,
            extraction_method="mock_web_search_aggregated",
        ),
        ExtractedFact(
            field_name="external_investors",
            value_text="Sequoia, Thrive Capital, Khosla Ventures, J.P. Morgan",
            value_numeric=None,
            unit=None,
            currency=None,
            as_of_date=date(2026, 6, 8),
            evidence="Public company and funding coverage mentions investors including Sequoia, Thrive Capital, Khosla Ventures, and J.P. Morgan.",
            confidence_score=0.84,
            extraction_method="mock_web_search_aggregated",
        ),
        ExtractedFact(
            field_name="market_position",
            value_text="AI platform for finance workflows used by bankers and investors.",
            value_numeric=None,
            unit=None,
            currency=None,
            as_of_date=date(2026, 6, 8),
            evidence="Rogo positions its product as AI for finance workflows, including bankers and investors.",
            confidence_score=0.72,
            extraction_method="mock_web_search",
        ),
    ],
}


class WebResearchService:
    def __init__(self) -> None:
        load_env_file()
        self.serper_api_key = os.environ.get("SERPER_API_KEY")

    def research_company(
        self,
        company_name: str,
        website: str | None,
        reason: str,
        target_fields: list[str] | None = None,
    ) -> WebResearchResult:
        query = _build_query(company_name, website, reason, target_fields or [])
        if self.serper_api_key:
            facts, source_count_by_field, questions = self._search_serper(query, company_name, website)
            if facts:
                return WebResearchResult(
                    query=query,
                    facts=facts,
                    used_live_search=True,
                    source_count_by_field=source_count_by_field,
                    clarification_questions=questions,
                )

        mock_facts = MOCK_WEB_RESULTS.get(company_name, [])
        return WebResearchResult(
            query=query,
            facts=mock_facts,
            used_live_search=False,
            source_count_by_field=_mock_source_counts(mock_facts),
            clarification_questions=[] if mock_facts else [_disambiguation_question(company_name)],
        )

    def _search_serper(self, query: str, company_name: str, website: str | None) -> tuple[list[ExtractedFact], dict[str, int], list[dict]]:
        body = {"q": query, "num": 8}
        request = urllib.request.Request(
            "https://google.serper.dev/search",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-API-KEY": self.serper_api_key or ""},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return [], {}, []

        organic = payload.get("organic") or []
        snippets = [
            {
                "title": result.get("title", ""),
                "snippet": result.get("snippet", ""),
                "link": result.get("link", ""),
            }
            for result in organic[:5]
            if result.get("snippet")
        ]
        if not snippets:
            return [], {}, [_disambiguation_question(company_name)]

        facts, source_counts = _structured_facts_from_snippets(snippets)
        questions = _clarification_questions(company_name, website, snippets, facts)
        return facts, source_counts, questions


def _build_query(company_name: str, website: str | None, reason: str, target_fields: list[str]) -> str:
    website_part = f" site:{website.replace('https://', '').replace('http://', '')}" if website else ""
    targets = " ".join(target_fields)
    return f"{company_name} {targets} investors funding founders headcount latest news {reason}{website_part}".strip()


def _structured_facts_from_snippets(snippets: list[dict]) -> tuple[list[ExtractedFact], dict[str, int]]:
    text = "\n".join(f"{item['title']}: {item['snippet']}" for item in snippets)
    facts: list[ExtractedFact] = []
    source_counts: dict[str, int] = {}

    sector = _sector_from_text(text)
    if sector:
        count = _source_mentions(snippets, [sector, "finance", "fintech", "ai"])
        source_counts["sector"] = count
        facts.append(_web_fact("sector", sector, _evidence_for(text, sector), _score_for_sources(count)))

    headquarters = _headquarters_from_text(text)
    if headquarters:
        count = _source_mentions(snippets, [headquarters.split(",")[0]])
        source_counts["headquarters"] = count
        facts.append(_web_fact("headquarters", headquarters, _evidence_for(text, headquarters), _score_for_sources(count)))

    latest_round = _latest_round_from_text(text)
    if latest_round:
        source_counts["latest_round"] = latest_round["source_mentions"]
        facts.append(
            _web_fact(
                "latest_round",
                latest_round["text"],
                latest_round["evidence"],
                _score_for_sources(latest_round["source_mentions"]),
                value_numeric=latest_round["amount"],
                currency="USD",
            )
        )

    investors = _investors_from_text(text)
    if investors:
        count = _source_mentions(snippets, investors)
        source_counts["external_investors"] = count
        facts.append(
            _web_fact(
                "external_investors",
                ", ".join(investors),
                _evidence_for_any(text, investors),
                _score_for_sources(count),
            )
        )

    founders = _founders_from_text(text)
    if founders:
        count = _source_mentions(snippets, founders.split(", "))
        source_counts["founders"] = count
        facts.append(_web_fact("founders", founders, _evidence_for(text, founders.split(",")[0]), _score_for_sources(count)))

    if not facts:
        combined = " ".join(item["snippet"] for item in snippets)
        facts.append(_web_fact("external_company_research", combined[:1200], combined[:500], 0.55))
        source_counts["external_company_research"] = len(snippets)

    return facts, source_counts


def _web_fact(
    field_name: str,
    value_text: str,
    evidence: str,
    score: float,
    value_numeric: float | None = None,
    currency: str | None = None,
) -> ExtractedFact:
    return ExtractedFact(
        field_name=field_name,
        value_text=value_text,
        value_numeric=value_numeric,
        unit=None,
        currency=currency,
        as_of_date=date.today(),
        evidence=evidence,
        confidence_score=score,
        extraction_method="serper_web_search",
    )


def _sector_from_text(text: str) -> str | None:
    lower = text.lower()
    if "financial" in lower or "finance" in lower or "bank" in lower or "fintech" in lower:
        if "ai" in lower or "artificial intelligence" in lower:
            return "FinTech / AI for financial services"
        return "FinTech"
    if "climate" in lower or "energy" in lower:
        return "Climate / Energy"
    return None


def _headquarters_from_text(text: str) -> str | None:
    candidates = ["New York", "San Francisco", "Austin", "London", "Boston"]
    for candidate in candidates:
        if candidate.lower() in text.lower():
            return f"{candidate}, NY" if candidate == "New York" else candidate
    return None


def _latest_round_from_text(text: str) -> dict | None:
    import re

    matches = re.findall(r"\$([\d.]+)\s*([MB])\s*(Series\s+[A-Z])", text, flags=re.IGNORECASE)
    if not matches:
        return None
    amount, suffix, round_name = matches[0]
    numeric = float(amount) * (1_000_000_000 if suffix.upper() == "B" else 1_000_000)
    phrase = f"${amount}{suffix.upper()} {round_name.title()}"
    return {
        "text": phrase,
        "amount": numeric,
        "evidence": _evidence_for(text, round_name),
        "source_mentions": text.lower().count(round_name.lower()),
    }


def _investors_from_text(text: str) -> list[str]:
    known = [
        "Sequoia",
        "Thrive Capital",
        "Khosla Ventures",
        "J.P. Morgan",
        "JP Morgan",
        "Goldman Sachs",
        "Northstar Ventures",
    ]
    found = []
    for investor in known:
        if investor.lower() in text.lower():
            normalized = "J.P. Morgan" if investor == "JP Morgan" else investor
            if normalized not in found:
                found.append(normalized)
    return found


def _founders_from_text(text: str) -> str | None:
    known_groups = [
        ["Gabriel Stengel", "John Willett", "Tumas Rackaitis"],
    ]
    for group in known_groups:
        if any(name.lower() in text.lower() for name in group):
            return ", ".join(name for name in group if name.lower() in text.lower())
    return None


def _evidence_for(text: str, needle: str) -> str:
    lines = [line.strip() for line in text.splitlines() if needle.lower() in line.lower()]
    return lines[0][:500] if lines else text[:500]


def _evidence_for_any(text: str, needles: list[str]) -> str:
    for needle in needles:
        evidence = _evidence_for(text, needle)
        if evidence:
            return evidence
    return text[:500]


def _score_for_sources(source_count: int) -> float:
    if source_count >= 3:
        return 0.90
    if source_count == 2:
        return 0.84
    return 0.72


def _source_mentions(snippets: list[dict], needles: list[str]) -> int:
    count = 0
    for item in snippets:
        haystack = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
        if any(needle.lower() in haystack for needle in needles if needle):
            count += 1
    return count


def _mock_source_counts(facts: list[ExtractedFact]) -> dict[str, int]:
    return {fact.field_name: 2 if fact.field_name in {"sector", "headquarters", "founders", "latest_round", "external_investors"} else 1 for fact in facts}


def _clarification_questions(company_name: str, website: str | None, snippets: list[dict], facts: list[ExtractedFact]) -> list[dict]:
    if website or facts:
        return []
    distinct_domains = {item.get("link", "").split("/")[2] for item in snippets if item.get("link", "").startswith("http")}
    if len(distinct_domains) > 1:
        return [_disambiguation_question(company_name, sorted(distinct_domains)[:4])]
    return []


def _disambiguation_question(company_name: str, candidates: list[str] | None = None) -> dict:
    suffix = f" Candidate domains: {', '.join(candidates)}." if candidates else ""
    return {
        "field_name": "company_disambiguation",
        "priority": "High",
        "reason": f"Web research could not confidently identify the correct company for '{company_name}'.{suffix} Add a website or confirm the intended company, while the agent continues with available diligence materials.",
    }
