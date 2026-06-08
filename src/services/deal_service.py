from pathlib import Path

from sqlalchemy.orm import Session

from src.database.models import (
    AgentRun,
    Company,
    ComputedMetric,
    Conflict,
    Deal,
    Document,
    DocumentChunk,
    Fact,
    FactSource,
    MetricObservation,
    ReviewItem,
    DealEvent,
)


class DealService:
    def __init__(self, db: Session):
        self.db = db

    def get_deal(self, deal_id: str) -> Deal | None:
        return self.db.query(Deal).filter(Deal.deal_id == deal_id).first()

    def get_or_create_deal(
        self,
        company_name: str,
        website: str | None = None,
        owner: str = "Associate",
    ) -> Deal:
        company = self.db.query(Company).filter(Company.name == company_name).first()
        if not company:
            company = Company(
                company_id=_slug_id("co", company_name),
                name=company_name,
                website=website,
            )
            self.db.add(company)
            self.db.flush()

        deal = self.db.query(Deal).filter(Deal.company_id == company.company_id).first()
        if deal:
            return deal

        deal = Deal(
            deal_id=_slug_id("d", company_name),
            company_id=company.company_id,
            stage="Sourced",
            owner=owner,
            source="Manual",
            priority="Medium",
            status="Active",
        )
        self.db.add(deal)
        self.db.flush()
        return deal

    def current_metric_status(self, deal_id: str, company_id: str) -> list[dict]:
        observations = (
            self.db.query(MetricObservation)
            .filter(MetricObservation.deal_id == deal_id, MetricObservation.company_id == company_id)
            .order_by(MetricObservation.metric_name, MetricObservation.as_of_date.desc().nullslast())
            .all()
        )
        latest: dict[str, MetricObservation] = {}
        for observation in observations:
            latest.setdefault(observation.metric_name, observation)
        return [
            {
                "metric_name": metric.metric_name,
                "value": metric.value_numeric if metric.value_numeric is not None else metric.value_text,
                "as_of_date": metric.as_of_date.isoformat() if metric.as_of_date else None,
                "confidence_score": metric.confidence_score,
                "review_status": metric.review_status,
                "staleness_status": metric.staleness_status,
            }
            for metric in latest.values()
        ]

    def create_staleness_review_items(self, deal_id: str, company_id: str) -> list[ReviewItem]:
        stale_metrics = (
            self.db.query(MetricObservation)
            .filter(
                MetricObservation.deal_id == deal_id,
                MetricObservation.company_id == company_id,
                MetricObservation.staleness_status == "stale",
            )
            .all()
        )
        created: list[ReviewItem] = []
        for metric in stale_metrics:
            exists = (
                self.db.query(ReviewItem)
                .filter(
                    ReviewItem.deal_id == deal_id,
                    ReviewItem.field_name == metric.metric_name,
                    ReviewItem.reason.like("%stale%"),
                    ReviewItem.status == "open",
                )
                .first()
            )
            if exists:
                continue
            item = ReviewItem(
                review_id=f"review_stale_{metric.metric_observation_id}",
                deal_id=deal_id,
                field_name=metric.metric_name,
                reason=f"{metric.metric_name} is stale based on as_of_date {metric.as_of_date}.",
                candidate_fact_ids=None,
                priority="Medium",
            )
            self.db.add(item)
            created.append(item)
        return created

    def clear_generated_intelligence(self, deal_id: str) -> None:
        document_ids = [row[0] for row in self.db.query(Document.document_id).filter(Document.deal_id == deal_id).all()]
        fact_ids = [row[0] for row in self.db.query(Fact.fact_id).filter(Fact.deal_id == deal_id).all()]

        self.db.query(AgentRun).filter(AgentRun.deal_id == deal_id).delete(synchronize_session=False)
        self.db.query(ComputedMetric).filter(ComputedMetric.deal_id == deal_id).delete(synchronize_session=False)
        self.db.query(Conflict).filter(Conflict.deal_id == deal_id).delete(synchronize_session=False)
        self.db.query(ReviewItem).filter(ReviewItem.deal_id == deal_id).delete(synchronize_session=False)
        self.db.query(MetricObservation).filter(MetricObservation.deal_id == deal_id).delete(synchronize_session=False)
        if fact_ids:
            self.db.query(FactSource).filter(FactSource.fact_id.in_(fact_ids)).delete(synchronize_session=False)
        self.db.query(Fact).filter(Fact.deal_id == deal_id).delete(synchronize_session=False)
        if document_ids:
            self.db.query(DocumentChunk).filter(DocumentChunk.document_id.in_(document_ids)).delete(synchronize_session=False)
        self.db.query(Document).filter(Document.deal_id == deal_id).delete(synchronize_session=False)
        self.db.flush()


def infer_doc_paths_for_deal(deal: Deal) -> list[str]:
    docs_dir = Path("data/documents")
    hints = {
        deal.company.name.split()[0].lower(),
        deal.company_id.replace("co_", "").lower(),
        deal.deal_id.replace("d_", "").lower(),
        deal.deal_id.lower(),
    }
    matches = []
    for path in docs_dir.iterdir():
        if not path.is_file() or path.suffix.lower() not in {".txt", ".md", ".pdf", ".xlsx", ".xlsm", ".csv", ".png", ".jpg", ".jpeg", ".webp", ".heic"}:
            continue
        name = path.name.lower()
        if any(name.startswith(hint) for hint in hints):
            matches.append(str(path))
    return sorted(matches)


def _slug_id(prefix: str, text: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "_" for char in text).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return f"{prefix}_{slug}"


def log_deal_event(
    db: Session,
    deal_id: str,
    field_name: str,
    old_value: object,
    new_value: object,
    reason: str | None = None,
    event_type: str = "field_change",
    fact_id: str | None = None,
    source_id: str | None = None,
    source_label: str | None = None,
    provider: str | None = None,
) -> None:
    if str(old_value) == str(new_value):
        return
    db.add(
        DealEvent(
            event_id=new_id("event"),
            deal_id=deal_id,
            field_name=field_name,
            old_value=None if old_value is None else str(old_value),
            new_value=None if new_value is None else str(new_value),
            event_type=event_type,
            fact_id=fact_id,
            source_id=source_id,
            source_label=source_label,
            provider=provider,
            reason=reason,
        )
    )
