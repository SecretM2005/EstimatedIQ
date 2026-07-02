"""
SQLite-Datenbank für Angebotskalkulation MVP.
Datei: data/estimateiq_angebot.db
"""

from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "estimateiq_angebot.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_db() -> None:
    """ALTER TABLE für Spalten, die nach der ersten Erstellung hinzugekommen sind."""
    migrations = [
        ("projekte",            "beschreibung",  "TEXT NOT NULL DEFAULT ''"),
        ("projekte",            "kunde",         "TEXT NOT NULL DEFAULT ''"),
        ("projekte",            "ist_referenz",  "BOOLEAN NOT NULL DEFAULT 0"),
        ("projekte",            "embedding_json","TEXT"),
        ("leistungspositionen", "stundensatz_snapshot", "REAL"),
        ("leistungspositionen", "embedding_json","TEXT"),
        ("leistungspositionen", "ist_historisch","BOOLEAN NOT NULL DEFAULT 0"),
    ]
    with engine.connect() as conn:
        for table, column, definition in migrations:
            existing = [
                row[1]
                for row in conn.execute(
                    __import__("sqlalchemy").text(f"PRAGMA table_info({table})")
                )
            ]
            if column not in existing:
                conn.execute(
                    __import__("sqlalchemy").text(
                        f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                    )
                )
        conn.commit()


def init_db():
    from estimateiq.angebot import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _migrate_db()
