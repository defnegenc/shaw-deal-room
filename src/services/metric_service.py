import json

from sqlalchemy.orm import Session

from src.database.models import ComputedMetric, MetricObservation
from src.utils.ids import new_id


class MetricService:
    def __init__(self, db: Session):
        self.db = db

    def compute_for_deal(self, deal_id: str, company_id: str) -> list[ComputedMetric]:
        latest = self._latest_observations(deal_id, company_id)
        computed: list[ComputedMetric] = []

        arr = latest.get("arr")
        valuation = latest.get("pre_money_valuation")
        burn = latest.get("monthly_burn")

        if arr and valuation and arr.value_numeric and valuation.value_numeric:
            quality = _quality_from_inputs([valuation, arr])
            computed.append(
                self._upsert_metric(
                    deal_id=deal_id,
                    company_id=company_id,
                    metric_name="arr_valuation_multiple",
                    value=valuation.value_numeric / arr.value_numeric,
                    formula="pre_money_valuation / ARR",
                    input_ids=[valuation.metric_observation_id, arr.metric_observation_id],
                    confidence=min(valuation.confidence_score, arr.confidence_score),
                    review_status=quality["review_status"],
                    staleness_status=quality["staleness_status"],
                    quality_flags=quality["quality_flags"],
                )
            )

        if burn and arr and burn.value_numeric and arr.value_numeric:
            quality = _quality_from_inputs([burn, arr])
            computed.append(
                self._upsert_metric(
                    deal_id=deal_id,
                    company_id=company_id,
                    metric_name="annual_burn_pct_of_arr",
                    value=(burn.value_numeric * 12) / arr.value_numeric,
                    formula="monthly_burn * 12 / ARR",
                    input_ids=[burn.metric_observation_id, arr.metric_observation_id],
                    confidence=min(burn.confidence_score, arr.confidence_score),
                    review_status=quality["review_status"],
                    staleness_status=quality["staleness_status"],
                    quality_flags=quality["quality_flags"],
                )
            )

        return computed

    def _latest_observations(self, deal_id: str, company_id: str) -> dict[str, MetricObservation]:
        observations = (
            self.db.query(MetricObservation)
            .filter(MetricObservation.deal_id == deal_id, MetricObservation.company_id == company_id)
            .order_by(MetricObservation.as_of_date.desc().nullslast(), MetricObservation.created_at.desc())
            .all()
        )
        latest: dict[str, MetricObservation] = {}
        for observation in observations:
            latest.setdefault(observation.metric_name, observation)
        return latest

    def _upsert_metric(
        self,
        deal_id: str,
        company_id: str,
        metric_name: str,
        value: float,
        formula: str,
        input_ids: list[str],
        confidence: float,
        review_status: str,
        staleness_status: str,
        quality_flags: list[str],
    ) -> ComputedMetric:
        existing = (
            self.db.query(ComputedMetric)
            .filter(ComputedMetric.deal_id == deal_id, ComputedMetric.metric_name == metric_name)
            .first()
        )
        if existing:
            existing.value_numeric = value
            existing.formula = formula
            existing.input_fact_ids = json.dumps(input_ids)
            existing.confidence_score = confidence
            existing.review_status = review_status
            existing.staleness_status = staleness_status
            existing.quality_flags = json.dumps(quality_flags)
            return existing

        metric = ComputedMetric(
            metric_id=new_id("metric"),
            company_id=company_id,
            deal_id=deal_id,
            metric_name=metric_name,
            value_numeric=value,
            formula=formula,
            input_fact_ids=json.dumps(input_ids),
            confidence_score=confidence,
            review_status=review_status,
            staleness_status=staleness_status,
            quality_flags=json.dumps(quality_flags),
        )
        self.db.add(metric)
        return metric


def _quality_from_inputs(inputs: list[MetricObservation]) -> dict:
    flags: list[str] = []
    if any(item.staleness_status == "stale" for item in inputs):
        flags.append("stale_inputs")
    if any(item.review_status == "review_required" for item in inputs):
        flags.append("review_required_inputs")
    if any(item.confidence_score < 0.80 for item in inputs):
        flags.append("low_confidence_inputs")

    return {
        "review_status": "review_required" if flags else "accepted",
        "staleness_status": "stale" if "stale_inputs" in flags else "current",
        "quality_flags": flags,
    }
