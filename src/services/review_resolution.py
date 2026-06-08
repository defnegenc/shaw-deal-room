from datetime import date, datetime
import re

from sqlalchemy.orm import Session

from src.database.models import Deal, Fact, FactSource, ReviewItem
from src.parsers.document_parser import ExtractedFact
from src.services.deal_service import log_deal_event
from src.services.fact_service import FactService
from src.services.metric_service import MetricService


class ReviewResolutionService:
    def __init__(self, db: Session):
        self.db = db
        self.fact_service = FactService(db)
        self.metric_service = MetricService(db)

    def resolve_review_item(self, review_id: str, raw_value: str, as_of_text: str | None = None) -> dict:
        review = self.db.query(ReviewItem).filter(ReviewItem.review_id == review_id).first()
        if not review:
            raise ValueError("Review item not found")
        deal = self.db.query(Deal).filter(Deal.deal_id == review.deal_id).first()
        if not deal:
            raise ValueError("Deal not found")

        parsed = parse_associate_input(review.field_name, raw_value, as_of_text)
        extracted = ExtractedFact(
            field_name=review.field_name,
            value_text=parsed["value_text"],
            value_numeric=parsed["value_numeric"],
            unit=parsed["unit"],
            currency=parsed["currency"],
            as_of_date=parsed["as_of_date"],
            evidence=f"Associate correction: {raw_value}",
            confidence_score=1.0,
            extraction_method="associate_correction",
        )
        fact = self.fact_service.create_fact_from_extraction(
            company_id=deal.company_id,
            deal_id=deal.deal_id,
            extracted=extracted,
            source_type="manual_review",
            source_label="associate_review",
        )
        fact.review_status = "accepted"
        review.status = "resolved"
        review.resolution_outcome = _resolution_outcome(review, fact)
        review.resolved_fact_id = fact.fact_id
        review.resolved_at = datetime.utcnow()
        source = _candidate_source(self.db, review)
        log_deal_event(
            self.db,
            deal.deal_id,
            review.field_name,
            _candidate_value(self.db, review),
            raw_value,
            reason=f"Review resolved as {review.resolution_outcome}.",
            event_type="review_resolution",
            fact_id=source.fact_id if source else None,
            source_id=source.source_id if source else None,
            source_label=source.source_label if source else None,
            provider=source.provider if source else None,
        )
        self.metric_service.compute_for_deal(deal.deal_id, deal.company_id)
        self.db.commit()

        return {
            "review_id": review.review_id,
            "status": review.status,
            "resolution_outcome": review.resolution_outcome,
            "fact": {
                "fact_id": fact.fact_id,
                "field_name": fact.field_name,
                "value_text": fact.value_text,
                "value_numeric": fact.value_numeric,
                "currency": fact.currency,
                "unit": fact.unit,
                "as_of_date": fact.as_of_date.isoformat() if fact.as_of_date else None,
            },
        }


def parse_associate_input(field_name: str, raw_value: str, as_of_text: str | None = None) -> dict:
    raw = raw_value.strip()
    combined = f"{raw} {as_of_text or ''}".strip()
    parsed_date = _parse_date(combined)
    numeric = _parse_number(raw)

    currency = "USD" if "$" in raw or field_name in {"arr", "pre_money_valuation", "post_money_valuation", "monthly_burn", "funding_total", "latest_round"} else None
    unit = _unit_for_field(field_name)

    return {
        "value_text": raw,
        "value_numeric": numeric,
        "currency": currency,
        "unit": unit,
        "as_of_date": parsed_date,
    }


def _parse_number(value: str) -> float | None:
    cleaned = value.replace(",", "").replace("$", "").strip()
    match = re.search(r"([\d.]+)\s*([kKmMbB])?", cleaned)
    if not match:
        return None
    number = float(match.group(1))
    suffix = match.group(2)
    if suffix:
        multiplier = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[suffix.lower()]
        number *= multiplier
    return number


def _parse_date(text: str) -> date | None:
    iso = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text)
    if iso:
        return date.fromisoformat(iso.group(0))

    q_match = re.search(r"\bQ([1-4])\s*(20\d{2})\b", text, flags=re.IGNORECASE)
    if q_match:
        quarter = int(q_match.group(1))
        year = int(q_match.group(2))
        month_day = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}[quarter]
        return date(year, month_day[0], month_day[1])

    year = re.search(r"\b(20\d{2})\b", text)
    if year:
        return date(int(year.group(1)), 12, 31)

    return None


def _unit_for_field(field_name: str) -> str | None:
    return {
        "headcount": "employees",
        "revenue_growth_pct": "percent",
        "gross_margin_pct": "percent",
        "runway_months": "months",
    }.get(field_name)


def _resolution_outcome(review: ReviewItem, fact: Fact) -> str:
    candidate_ids = [value.strip() for value in (review.candidate_fact_ids or "").split(",") if value.strip()]
    if not candidate_ids:
        return "human_supplied_missing_value"
    candidate = review.candidate_fact_ids and review.candidate_fact_ids.split(",")[0].strip()
    if candidate and candidate == fact.fact_id:
        return "agent_suggestion_accepted"
    return "agent_suggestion_corrected"


def _candidate_source(db: Session, review: ReviewItem) -> FactSource | None:
    candidate_ids = [value.strip() for value in (review.candidate_fact_ids or "").split(",") if value.strip()]
    if not candidate_ids:
        return None
    return db.query(FactSource).filter(FactSource.fact_id == candidate_ids[0]).first()


def _candidate_value(db: Session, review: ReviewItem) -> str | None:
    candidate_ids = [value.strip() for value in (review.candidate_fact_ids or "").split(",") if value.strip()]
    if not candidate_ids:
        return None
    fact = db.query(Fact).filter(Fact.fact_id == candidate_ids[0]).first()
    if not fact:
        return None
    value = fact.value_numeric if fact.value_numeric is not None else fact.value_text
    return None if value is None else str(value)
