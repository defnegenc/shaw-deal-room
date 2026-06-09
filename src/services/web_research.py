from dataclasses import dataclass
from datetime import date
from urllib.parse import urlparse
import json
import os
import re
import urllib.error
import urllib.request

from src.config import load_env_file
from src.parsers.document_parser import ExtractedFact
from src.services.llm_extraction import LLMExtractionService


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
        self._llm = LLMExtractionService()

    def research_company(
        self,
        company_name: str,
        website: str | None,
        reason: str,
        target_fields: list[str] | None = None,
    ) -> WebResearchResult:
        query = _build_query(company_name, website, reason, target_fields or [])
        if self.serper_api_key:
            facts, source_count_by_field, questions = self._search_serper(query, company_name, website, target_fields or [])
            if facts:
                return WebResearchResult(
                    query=query,
                    facts=facts,
                    used_live_search=True,
                    source_count_by_field=source_count_by_field,
                    clarification_questions=questions,
                )

        mock_facts = MOCK_WEB_RESULTS.get(company_name, [])
        # No Serper key and no mock data: return empty without a disambiguation
        # question — the issue is missing config, not company ambiguity.
        return WebResearchResult(
            query=query,
            facts=mock_facts,
            used_live_search=False,
            source_count_by_field=_mock_source_counts(mock_facts),
            clarification_questions=[],
        )

    def _search_serper(
        self, query: str, company_name: str, website: str | None, target_fields: list[str]
    ) -> tuple[list[ExtractedFact], dict[str, int], list[dict]]:
        snippets = self._serper_snippets(query)
        # If site-restricted query returned nothing, retry without the site: filter
        if not snippets and website and "site:" in query:
            broad_query = _build_query(company_name, None, "", [])
            snippets = self._serper_snippets(broad_query)
        if not snippets:
            return [], {}, [_disambiguation_question(company_name)]
        facts = self._extract_facts(snippets, company_name)
        found = {fact.field_name for fact in facts}

        # Refine the search for specific high-value fields still missing -- like a
        # human Googling "<company> founders" directly instead of one broad query.
        for focused_query in _targeted_queries(company_name, target_fields, found):
            extra = self._serper_snippets(focused_query)
            if extra:
                facts.extend(self._extract_facts(extra, company_name))
                found = {fact.field_name for fact in facts}

        facts = _dedupe_web_facts(facts)
        source_counts = {fact.field_name: 1 for fact in facts}
        questions = _clarification_questions(company_name, website, snippets, facts)
        return facts, source_counts, questions

    def _serper_snippets(self, query: str) -> list[dict]:
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
            return []
        organic = payload.get("organic") or []
        return [
            {"title": r.get("title", ""), "snippet": r.get("snippet", ""), "link": r.get("link", "")}
            for r in organic[:5]
            if r.get("snippet")
        ]

    def _extract_facts(self, snippets: list[dict], company_name: str) -> list[ExtractedFact]:
        facts: list[ExtractedFact] = []
        if self._llm.enabled:
            try:
                facts = self._llm.extract_web_snippet_facts(snippets, company_name) or []
            except RuntimeError:
                facts = []

        if not facts:
            # Regex fallback: only funding round (general-purpose pattern)
            combined = "\n".join(f"{item['title']}: {item['snippet']}" for item in snippets)
            round_fact = _latest_round_from_text(combined)
            if round_fact:
                facts.append(
                    _web_fact(
                        "latest_round",
                        round_fact["text"],
                        round_fact["evidence"],
                        _score_for_sources(round_fact["source_mentions"]),
                        value_numeric=round_fact["amount"],
                        currency="USD",
                    )
                )

        # The homepage is in the result links, not stated in snippet text, so the
        # LLM won't reliably emit it -- derive it deterministically instead.
        if not any(fact.field_name == "website" for fact in facts):
            website_fact = _website_from_snippets(snippets, company_name)
            if website_fact:
                facts.append(website_fact)

        if not facts:
            combined = "\n".join(f"{item['title']}: {item['snippet']}" for item in snippets)
            facts.append(_web_fact("external_company_research", combined[:1200], combined[:500], 0.55))
        return facts


_NON_HOMEPAGE_DOMAINS = {
    "linkedin.com", "twitter.com", "x.com", "facebook.com", "instagram.com",
    "youtube.com", "crunchbase.com", "wikipedia.org", "github.com", "pitchbook.com",
    "bloomberg.com", "techcrunch.com", "forbes.com", "medium.com", "reddit.com",
    "glassdoor.com", "tracxn.com", "ycombinator.com", "cbinsights.com", "owler.com",
}


def _website_from_snippets(snippets: list[dict], company_name: str) -> ExtractedFact | None:
    """Pick the company's own homepage from the result links.

    The highest-ranked organic result whose domain matches the company name and
    is not a directory/social/news site is almost always the official site."""
    name_token = re.sub(r"[^a-z0-9]", "", company_name.lower())
    if not name_token:
        return None
    for item in snippets:
        link = item.get("link", "")
        if not link.startswith("http"):
            continue
        host = urlparse(link).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if any(host == domain or host.endswith("." + domain) for domain in _NON_HOMEPAGE_DOMAINS):
            continue
        root = host.split(".")[0]
        if root and (root in name_token or name_token in root or name_token.startswith(root) or root.startswith(name_token)):
            return _web_fact("website", f"https://{host}", f"Official site identified from search result: {link}", 0.82)
    return None


def _build_query(company_name: str, website: str | None, reason: str, target_fields: list[str]) -> str:
    # A focused profile query returns the company's own pages and reporting,
    # rather than a keyword soup that surfaces unrelated results.
    website_part = f" site:{website.replace('https://', '').replace('http://', '')}" if website else ""
    return f"{company_name} company funding investors founders headquarters{website_part}".strip()


def _targeted_queries(company_name: str, target_fields: list[str], found: set[str]) -> list[str]:
    """Per-field follow-up searches for high-value fields the broad query missed."""
    wanted = set(target_fields or [])
    queries: list[str] = []
    if (not wanted or "founders" in wanted) and "founders" not in found:
        queries.append(f"{company_name} founders co-founders CEO")
    if (not wanted or "website" in wanted) and "website" not in found:
        queries.append(f"{company_name} official website")
    return queries


def _dedupe_web_facts(facts: list[ExtractedFact]) -> list[ExtractedFact]:
    best: dict[str, ExtractedFact] = {}
    for fact in facts:
        current = best.get(fact.field_name)
        if current is None or fact.confidence_score > current.confidence_score:
            best[fact.field_name] = fact
    return list(best.values())


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


def _latest_round_from_text(text: str) -> dict | None:
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


def _evidence_for(text: str, needle: str) -> str:
    lines = [line.strip() for line in text.splitlines() if needle.lower() in line.lower()]
    return lines[0][:500] if lines else text[:500]


def _score_for_sources(source_count: int) -> float:
    if source_count >= 3:
        return 0.90
    if source_count == 2:
        return 0.84
    return 0.72


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
