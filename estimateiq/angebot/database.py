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
        # RBAC Phase 1: teamrolle_id bleibt hier bewusst NULLABLE – SQLite kann
        # nach dem Anlegen keine NOT-NULL-Constraint mehr nachträglich setzen.
        # Die Anwendung befüllt die Spalte unten per Backfill vollständig;
        # das ORM-Modell verlangt NOT NULL (gilt strikt für neue Zeilen).
        # Auf Postgres/Supabase erzwingt migrations/003 die Constraint echt.
        ("tenant_users",        "teamrolle_id",    "INTEGER"),
        ("tenant_users",        "status",          "TEXT NOT NULL DEFAULT 'aktiv'"),
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

    _backfill_teamrollen()


def _backfill_teamrollen() -> None:
    """
    RBAC Phase 1: legt für jeden bestehenden Tenant die Systemrollen an und
    befüllt tenant_users.teamrolle_id für Zeilen, die noch keine haben –
    abgeleitet aus der alten rolle-Spalte (admin→Owner, mitglied→Mitarbeiter).
    Idempotent (WHERE teamrolle_id IS NULL), harmlos bei jedem Start.
    """
    from estimateiq.angebot.models import Tenant, TenantUser

    db = SessionLocal()
    try:
        offene = db.query(TenantUser).filter(TenantUser.teamrolle_id.is_(None)).all()
        if not offene:
            return
        tenant_ids = {u.tenant_id for u in offene}
        for tid in tenant_ids:
            if db.get(Tenant, tid) is None:
                continue
            rollen = ensure_systemrollen(db, tid)
            for u in offene:
                if u.tenant_id != tid:
                    continue
                u.teamrolle_id = rollen["Owner"] if u.rolle == "admin" else rollen["Mitarbeiter"]
        db.commit()
        logger.info("RBAC-Backfill: %d tenant_users-Zeile(n) migriert.", len(offene))
    finally:
        db.close()


def _ensure_dev_tenant() -> None:
    """Legt im Dev-Modus (AUTH_DISABLED) den festen Dev-Tenant an."""
    from estimateiq.angebot.models import Tenant

    db = SessionLocal()
    try:
        if db.get(Tenant, config.DEV_TENANT_ID) is None:
            db.add(Tenant(id=config.DEV_TENANT_ID, name=config.DEV_TENANT_NAME))
            db.commit()
            logger.info("Dev-Tenant angelegt: %s", config.DEV_TENANT_ID)
        ensure_systemrollen(db, config.DEV_TENANT_ID)
    finally:
        db.close()


def ensure_systemrollen(db, tenant_id: str) -> dict[str, int]:
    """
    Legt den globalen Permission-Katalog (falls fehlend) sowie die vier
    Systemrollen (Owner/Admin/Mitarbeiter/Nur-Lesen) für einen Tenant an.
    Idempotent (get-or-create). Einzige Stelle, die Systemrollen erzeugt –
    wird von SQLite-Migration, Seed-Skript und Test-Fixtures gleichermaßen
    genutzt, damit es hierfür nur einen Codepfad gibt.

    Gibt {Rollenname: teamrolle_id} zurück.
    """
    from estimateiq.angebot.models import Permission, Teamrolle, TeamrollePermission
    from estimateiq.angebot.permissions import KATALOG, SYSTEMROLLEN, SYSTEMROLLEN_REIHENFOLGE

    vorhandene_keys = {p.key for p in db.query(Permission).all()}
    for key, bereich, beschreibung in KATALOG:
        if key not in vorhandene_keys:
            db.add(Permission(key=key, bereich=bereich, beschreibung=beschreibung))
    db.flush()

    ergebnis: dict[str, int] = {}
    for name in SYSTEMROLLEN_REIHENFOLGE:
        rolle = (
            db.query(Teamrolle)
            .filter(Teamrolle.tenant_id == tenant_id, Teamrolle.name == name)
            .first()
        )
        if rolle is None:
            rolle = Teamrolle(tenant_id=tenant_id, name=name, is_system=True)
            db.add(rolle)
            db.flush()
            for key in SYSTEMROLLEN[name]:
                db.add(TeamrollePermission(teamrolle_id=rolle.id, permission_key=key))
        ergebnis[name] = rolle.id

    db.commit()
    return ergebnis


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
