from datetime import date

from sqlalchemy.orm import Session

from src.database.models import Fact, FactSource, MetricObservation, ReviewItem
from src.parsers.document_parser import ExtractedFact
from src.utils.ids import new_id

METRIC_FIELDS = {
    "arr",
    "monthly_burn",
    "pre_money_valuation",
    "post_money_valuation",
    "investment_amount",
    "target_raise",
    "headcount",
    "revenue_growth_pct",
    "gross_margin_pct",
    "runway_months",
}

REVIEW_FIRST_METHODS = {"gemini_flash_fallback", "gemini_flash_vision", "mock_web_search"}


class FactService:
    def __init__(self, db: Session, confidence_threshold: float = 0.80):
        self.db = db
        self.confidence_threshold = confidence_threshold

    def create_fact_from_extraction(
        self,
        company_id: str,
        deal_id: str,
        extracted: ExtractedFact,
        source_type: str,
        source_label: str,
        document_id: str | None = None,
        chunk_id: str | None = None,
        provider: str | None = None,
        url: str | None = None,
        force_review: bool = False,
        review_reason_override: str | None = None,
    ) -> Fact:
        review_status = "accepted" if extracted.confidence_score >= self.confidence_threshold else "review_required"
        if extracted.extraction_method in REVIEW_FIRST_METHODS:
            review_status = "review_required"
        staleness_status = self.staleness_status(extracted.as_of_date)
        if staleness_status == "stale":
            review_status = "review_required"
        if force_review:
            review_status = "review_required"

        fact = Fact(
            fact_id=new_id("fact"),
            company_id=company_id,
            deal_id=deal_id,
            field_name=extracted.field_name,
            value_text=extracted.value_text,
            value_numeric=extracted.value_numeric,
            unit=extracted.unit,
            currency=extracted.currency,
            as_of_date=extracted.as_of_date,
            extraction_method=extracted.extraction_method,
            confidence_score=extracted.confidence_score,
            review_status=review_status,
            staleness_status=staleness_status,
        )
        self.db.add(fact)
        self.db.flush()

        source = FactSource(
            source_id=new_id("src"),
            fact_id=fact.fact_id,
            source_type=source_type,
            document_id=document_id,
            chunk_id=chunk_id,
            source_label=source_label,
            quoted_evidence=extracted.evidence,
            provider=provider,
            url=url,
        )
        self.db.add(source)
        self.db.flush()

        if extracted.field_name in METRIC_FIELDS:
            self.db.add(
                MetricObservation(
                    metric_observation_id=new_id("obs"),
                    company_id=company_id,
                    deal_id=deal_id,
                    metric_name=extracted.field_name,
                    value_numeric=extracted.value_numeric,
                    value_text=extracted.value_text,
                    unit=extracted.unit,
                    currency=extracted.currency,
                    as_of_date=extracted.as_of_date,
                    source_id=source.source_id,
                    confidence_score=extracted.confidence_score,
                    review_status=review_status,
                    staleness_status=staleness_status,
                )
            )

        if review_status == "review_required":
            self.db.add(
                ReviewItem(
                    review_id=new_id("review"),
                    deal_id=deal_id,
                    field_name=extracted.field_name,
                    reason=review_reason_override or _review_reason(extracted, staleness_status),
                    candidate_fact_ids=fact.fact_id,
                    priority="Medium",
                )
            )

        return fact

    @staticmethod
    def staleness_status(as_of_date: date | None, today: date | None = None) -> str:
        if as_of_date is None:
            return "unknown"
        today = today or date.today()
        return "stale" if (today - as_of_date).days > 183 else "current"


def _review_reason(extracted: ExtractedFact, staleness_status: str) -> str:
    if staleness_status == "stale":
        return f"{extracted.field_name} is stale based on as_of_date {extracted.as_of_date}."
    if extracted.extraction_method in REVIEW_FIRST_METHODS:
        return f"{extracted.field_name} came from {extracted.extraction_method}; verify before using as canonical diligence data."
    if extracted.confidence_score < 0.80:
        return f"{extracted.field_name} extraction was ambiguous or below the auto-accept threshold."
    return f"{extracted.field_name} requires review."
