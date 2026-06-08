from dataclasses import dataclass


@dataclass(frozen=True)
class EnrichedCompany:
    sector: str
    geography: str
    summary: str
    facts: dict[str, str]


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
    def enrich(self, company_name: str) -> EnrichedCompany | None:
        return MOCK_COMPANIES.get(company_name)
