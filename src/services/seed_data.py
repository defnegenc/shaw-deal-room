from pathlib import Path
import csv

from sqlalchemy.orm import Session

from src.database.models import Company, Deal


def seed_if_empty(db: Session) -> bool:
    if db.query(Deal).first():
        return False

    seed_path = Path("data/seed_deals.csv")
    with seed_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            company = Company(
                company_id=row["company_id"],
                name=row["company_name"],
                website=row["website"],
            )
            deal = Deal(
                deal_id=row["deal_id"],
                company_id=row["company_id"],
                stage=row["stage"],
                owner=row["owner"],
                source=row["source"],
                priority=row["priority"],
                status=row["status"],
                initial_contact=row["initial_contact"],
            )
            db.add(company)
            db.add(deal)
    db.commit()
    return True
