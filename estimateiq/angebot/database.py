"""
Datenbank-Anbindung für die Angebotskalkulation.

Zwei Betriebsmodi (gesteuert über DATABASE_URL, siehe config.py):
  - Supabase Postgres + pgvector  (Demo/Produktion)
  - SQLite                        (lokale Entwicklung, Fallback)

Für Postgres wird das Schema NICHT automatisch erstellt –
dafür gibt es migrations/001_supabase_schema.sql.
"""

import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from estimateiq.angebot import config

logger = logging.getLogger(__name__)

if config.IS_POSTGRES:
    _url = config.DATABASE_URL
    # Heroku-/Supabase-Kurzform auf SQLAlchemy-Dialekt normalisieren
    if _url.startswith("postgres://"):
        _url = _url.replace("postgres://", "postgresql://", 1)
    engine = create_engine(
        _url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_recycle=1800,
    )
    logger.info("Datenbank-Modus: Supabase Postgres (pgvector)")
else:
    config.SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{config.SQLITE_PATH}",
        connect_args={"check_same_thread": False},
    )
    logger.info("Datenbank-Modus: SQLite (%s)", config.SQLITE_PATH)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_sqlite() -> None:
    """ALTER TABLE für Spalten, die nach der ersten Erstellung hinzugekommen sind (nur SQLite)."""
    dev_tenant = config.DEV_TENANT_ID
    migrations = [
        ("projekte",            "beschreibung",  "TEXT NOT NULL DEFAULT ''"),
        ("projekte",            "kunde",         "TEXT NOT NULL DEFAULT ''"),
        ("projekte",            "ist_referenz",  "BOOLEAN NOT NULL DEFAULT 0"),
        ("projekte",            "embedding_json","TEXT"),
        ("projekte",            "ablehnungsgrund", "TEXT"),
        ("projekte",            "leitung",         "TEXT"),
        ("projekte",            "auftragswert",    "REAL"),
        ("projekte",            "abrechnung_typ",  "TEXT"),
        ("projekte",            "laufzeit_start",  "TEXT"),
        ("projekte",            "laufzeit_end",    "TEXT"),
        ("projekte",            "tenant_id",       f"TEXT NOT NULL DEFAULT '{dev_tenant}'"),
        ("projekte",            "ersteller_id",    "TEXT"),
        ("leistungspositionen", "stundensatz_snapshot", "REAL"),
        ("leistungspositionen", "embedding_json","TEXT"),
        ("leistungspositionen", "ist_historisch","BOOLEAN NOT NULL DEFAULT 0"),
        ("leistungspositionen", "phase",           "TEXT"),
        ("leistungspositionen", "tenant_id",       f"TEXT NOT NULL DEFAULT '{dev_tenant}'"),
        ("rollen",              "tenant_id",       f"TEXT NOT NULL DEFAULT '{dev_tenant}'"),
        ("angebote",            "tenant_id",       f"TEXT NOT NULL DEFAULT '{dev_tenant}'"),
        ("tenant_users",        "rolle",           "TEXT NOT NULL DEFAULT 'mitglied'"),
    ]
    with engine.connect() as conn:
        for table, column, definition in migrations:
            existing = [
                row[1]
                for row in conn.execute(text(f"PRAGMA table_info({table})"))
            ]
            if column not in existing:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                )
        conn.commit()


def _ensure_dev_tenant() -> None:
    """Legt im Dev-Modus (AUTH_DISABLED) den festen Dev-Tenant an."""
    from estimateiq.angebot.models import Tenant

    db = SessionLocal()
    try:
        if db.get(Tenant, config.DEV_TENANT_ID) is None:
            db.add(Tenant(id=config.DEV_TENANT_ID, name=config.DEV_TENANT_NAME))
            db.commit()
            logger.info("Dev-Tenant angelegt: %s", config.DEV_TENANT_ID)
    finally:
        db.close()


def init_db():
    from estimateiq.angebot import models  # noqa: F401

    if config.IS_POSTGRES:
        # Schema kommt aus migrations/001_supabase_schema.sql – hier nur prüfen.
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1 FROM tenants LIMIT 1"))
        except Exception as exc:
            logger.error(
                "Supabase-Schema fehlt oder ist nicht erreichbar. "
                "Bitte migrations/001_supabase_schema.sql ausführen. (%s)", exc
            )
            raise
    else:
        Base.metadata.create_all(bind=engine)
        _migrate_sqlite()

    if config.AUTH_DISABLED:
        _ensure_dev_tenant()
