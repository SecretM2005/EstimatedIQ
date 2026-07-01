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


def init_db():
    from estimateiq.angebot import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
