from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.database.models import DealEvent


@dataclass(frozen=True)
class SourceReliabilityContext:
    corrected_providers: set[str]
    corrected_source_labels: set[str]
    notes: list[dict]


class SourceReliabilityService:
    def __init__(self, db: Session):
        self.db = db

    def context_for_deal(self, deal_id: str) -> SourceReliabilityContext:
        events = (
            self.db.query(DealEvent)
            .filter(
                DealEvent.deal_id == deal_id,
                DealEvent.event_type == "review_resolution",
                DealEvent.reason.like("%agent_suggestion_corrected%"),
            )
            .all()
        )
        corrected_providers = {event.provider for event in events if event.provider}
        corrected_source_labels = {event.source_label for event in events if event.source_label}
        notes = [
            {
                "field_name": event.field_name,
                "source_label": event.source_label,
                "provider": event.provider,
                "old_value": event.old_value,
                "new_value": event.new_value,
                "reason": event.reason,
            }
            for event in events
        ]
        return SourceReliabilityContext(
            corrected_providers=corrected_providers,
            corrected_source_labels=corrected_source_labels,
            notes=notes,
        )

    @staticmethod
    def should_force_review(
        context: SourceReliabilityContext,
        provider: str | None,
        source_label: str | None,
    ) -> bool:
        return bool(
            (provider and provider in context.corrected_providers)
            or (source_label and source_label in context.corrected_source_labels)
        )
