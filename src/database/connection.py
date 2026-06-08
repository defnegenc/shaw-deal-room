from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL = "sqlite:///./deal_room.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from src.database.models import Base

    Base.metadata.create_all(bind=engine)
    _apply_sqlite_compat_migrations()


def reset_db() -> None:
    """Drop every table and recreate the schema — a clean slate for the demo."""
    from src.database.models import Base

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    _apply_sqlite_compat_migrations()


def _apply_sqlite_compat_migrations() -> None:
    with engine.begin() as connection:
        review_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(review_items)").fetchall()}
        review_migrations = {
            "resolution_outcome": "ALTER TABLE review_items ADD COLUMN resolution_outcome VARCHAR",
            "resolved_fact_id": "ALTER TABLE review_items ADD COLUMN resolved_fact_id VARCHAR",
            "resolved_at": "ALTER TABLE review_items ADD COLUMN resolved_at DATETIME",
        }
        for column, statement in review_migrations.items():
            if column not in review_columns:
                connection.exec_driver_sql(statement)

        event_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(deal_events)").fetchall()}
        event_migrations = {
            "event_type": "ALTER TABLE deal_events ADD COLUMN event_type VARCHAR DEFAULT 'field_change'",
            "fact_id": "ALTER TABLE deal_events ADD COLUMN fact_id VARCHAR",
            "source_id": "ALTER TABLE deal_events ADD COLUMN source_id VARCHAR",
            "source_label": "ALTER TABLE deal_events ADD COLUMN source_label VARCHAR",
            "provider": "ALTER TABLE deal_events ADD COLUMN provider VARCHAR",
        }
        for column, statement in event_migrations.items():
            if column not in event_columns:
                connection.exec_driver_sql(statement)

        # `locked` marks human-authored, canonical data that must survive agent
        # re-runs. Added after the initial schema, so back-fill on existing DBs.
        fact_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(facts)").fetchall()}
        if "locked" not in fact_columns:
            connection.exec_driver_sql("ALTER TABLE facts ADD COLUMN locked BOOLEAN DEFAULT 0 NOT NULL")
        observation_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(metric_observations)").fetchall()}
        if "locked" not in observation_columns:
            connection.exec_driver_sql("ALTER TABLE metric_observations ADD COLUMN locked BOOLEAN DEFAULT 0 NOT NULL")
