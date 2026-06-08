from src.database.connection import SessionLocal, engine, init_db
from src.database.models import Base
from src.services.seed_data import seed_if_empty


def build_db() -> None:
    Base.metadata.drop_all(bind=engine)
    init_db()

    with SessionLocal() as db:
        seed_if_empty(db)


if __name__ == "__main__":
    build_db()
    print("Built deal_room.db from seed data")
