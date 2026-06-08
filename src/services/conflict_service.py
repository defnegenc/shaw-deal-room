from collections import defaultdict

from sqlalchemy.orm import Session

from src.database.models import Conflict, Fact, ReviewItem
from src.utils.ids import new_id

CONFLICT_FIELDS = {"arr", "pre_money_valuation", "post_money_valuation", "headcount", "monthly_burn"}


class ConflictService:
    def __init__(self, db: Session, relative_tolerance: float = 0.05):
        self.db = db
        self.relative_tolerance = relative_tolerance

    def detect_conflicts(self, deal_id: str, company_id: str) -> list[Conflict]:
        facts = (
            self.db.query(Fact)
            .filter(Fact.deal_id == deal_id, Fact.company_id == company_id, Fact.field_name.in_(CONFLICT_FIELDS))
            .all()
        )
        grouped: dict[str, list[Fact]] = defaultdict(list)
        for fact in facts:
            grouped[fact.field_name].append(fact)

        conflicts: list[Conflict] = []
        for field_name, group in grouped.items():
            numeric_values = [fact.value_numeric for fact in group if fact.value_numeric is not None]
            if len(numeric_values) < 2:
                continue
            if _has_material_difference(numeric_values, self.relative_tolerance):
                existing = (
                    self.db.query(Conflict)
                    .filter(Conflict.deal_id == deal_id, Conflict.field_name == field_name, Conflict.resolution_status == "open")
                    .first()
                )
                if existing:
                    conflicts.append(existing)
                    continue

                fact_ids = ",".join(fact.fact_id for fact in group)
                conflict = Conflict(
                    conflict_id=new_id("conflict"),
                    company_id=company_id,
                    deal_id=deal_id,
                    field_name=field_name,
                    fact_ids=fact_ids,
                    severity="High" if field_name.endswith("valuation") else "Medium",
                    resolution_status="open",
                )
                self.db.add(conflict)
                self.db.add(
                    ReviewItem(
                        review_id=new_id("review"),
                        deal_id=deal_id,
                        field_name=field_name,
                        reason=f"Conflicting values detected for {field_name}.",
                        candidate_fact_ids=fact_ids,
                        priority=conflict.severity,
                    )
                )
                for fact in group:
                    fact.review_status = "review_required"
                conflicts.append(conflict)
        return conflicts


def _has_material_difference(values: list[float], tolerance: float) -> bool:
    low = min(values)
    high = max(values)
    if high == 0:
        return False
    return (high - low) / high > tolerance
