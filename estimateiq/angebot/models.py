"""
SQLAlchemy ORM-Modelle für Angebotskalkulation MVP.

Multi-Tenancy: Alle Geschäftstabellen tragen eine tenant_id (Pflicht).
Embeddings: In Postgres als pgvector-Spalte `embedding vector(384)`,
in SQLite als JSON-Text in der Spalte `embedding_json`. Der Zugriff
läuft immer über get_embedding()/set_embedding().
"""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String, Float, Text, DateTime, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from estimateiq.angebot.config import IS_POSTGRES
from estimateiq.angebot.database import Base

if IS_POSTGRES:
    from pgvector.sqlalchemy import Vector

    _EMBEDDING_TYPE = Vector(384)
    _EMBEDDING_COL = "embedding"
else:
    _EMBEDDING_TYPE = Text
    _EMBEDDING_COL = "embedding_json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _neue_uuid() -> str:
    return str(uuid.uuid4())


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_neue_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TenantUser(Base):
    """Zuordnung Supabase-Auth-User (auth.users.id) → Tenant."""

    __tablename__ = "tenant_users"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, index=True
    )
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    teamrolle_id: Mapped[int] = mapped_column(ForeignKey("teamrollen.id"), nullable=False)
    # 'aktiv' | 'eingeladen' (Einladungs-Flow ist Phase 1b, aktuell immer 'aktiv')
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="aktiv")
    # LEGACY (Phase 1): wird ab sofort nirgends mehr gelesen, nur noch physisch
    # vorhanden für die Backfill-Migration. Wird in Migration 004 gedroppt.
    rolle: Mapped[str] = mapped_column(String(20), nullable=False, default="mitglied")

    teamrolle: Mapped["Teamrolle"] = relationship()


class Rolle(Base):
    __tablename__ = "rollen"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_rollen_tenant_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    stundensatz_eur: Mapped[float] = mapped_column(Float, nullable=False)
    gueltig_ab: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    positionen: Mapped[list["Leistungsposition"]] = relationship(back_populates="rolle")


class _EmbeddingMixin:
    """Einheitlicher Zugriff auf das Embedding, unabhängig vom DB-Backend."""

    def get_embedding(self) -> list[float] | None:
        raw = self.embedding
        if raw is None:
            return None
        if isinstance(raw, str):
            return json.loads(raw)
        return list(raw)

    def set_embedding(self, vec: list[float]) -> None:
        self.embedding = vec if IS_POSTGRES else json.dumps(vec)


class Projekt(Base, _EmbeddingMixin):
    __tablename__ = "projekte"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    beschreibung: Mapped[str] = mapped_column(Text, nullable=False, default="")
    kunde: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(50), default="entwurf")
    ist_referenz: Mapped[bool] = mapped_column(Boolean, default=False)
    # Ersteller (Supabase user_id). NULL = firmenweit / kein Owner (nur Admin editierbar).
    ersteller_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    embedding = mapped_column(_EMBEDDING_COL, _EMBEDDING_TYPE, nullable=True)
    ablehnungsgrund: Mapped[str | None] = mapped_column(Text, nullable=True)
    leitung: Mapped[str | None] = mapped_column(String(200), nullable=True)
    auftragswert: Mapped[float | None] = mapped_column(Float, nullable=True)
    abrechnung_typ: Mapped[str | None] = mapped_column(String(50), nullable=True)
    laufzeit_start: Mapped[str | None] = mapped_column(String(20), nullable=True)
    laufzeit_end: Mapped[str | None] = mapped_column(String(20), nullable=True)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    positionen: Mapped[list["Leistungsposition"]] = relationship(
        back_populates="projekt", cascade="all, delete-orphan"
    )
    angebote: Mapped[list["Angebot"]] = relationship(
        back_populates="projekt", cascade="all, delete-orphan"
    )


class Leistungsposition(Base, _EmbeddingMixin):
    __tablename__ = "leistungspositionen"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, index=True
    )
    projekt_id: Mapped[int] = mapped_column(ForeignKey("projekte.id"), nullable=False)
    rolle_id: Mapped[int | None] = mapped_column(ForeignKey("rollen.id"), nullable=True)
    beschreibung_text: Mapped[str] = mapped_column(Text, nullable=False)
    soll_stunden: Mapped[float] = mapped_column(Float, nullable=False)
    ist_stunden: Mapped[float | None] = mapped_column(Float, nullable=True)
    stundensatz_snapshot: Mapped[float | None] = mapped_column(Float, nullable=True)
    phase: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding = mapped_column(_EMBEDDING_COL, _EMBEDDING_TYPE, nullable=True)
    ist_historisch: Mapped[bool] = mapped_column(Boolean, default=False)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    projekt: Mapped["Projekt"] = relationship(back_populates="positionen")
    rolle: Mapped["Rolle | None"] = relationship(back_populates="positionen")


class Angebot(Base):
    __tablename__ = "angebote"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, index=True
    )
    projekt_id: Mapped[int] = mapped_column(ForeignKey("projekte.id"), nullable=False)
    titel: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(50), default="entwurf")
    pdf_pfad: Mapped[str | None] = mapped_column(String(500), nullable=True)
    versendet_am: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    projekt: Mapped["Projekt"] = relationship(back_populates="angebote")


# ── Teamrollen & Permissions (RBAC Phase 1) ───────────────────────────────────
# Bewusst "Teamrolle" statt "Rolle" genannt: "Rolle" ist bereits die
# Stundensatz-Rolle oben (z. B. "Senior Developer") und bleibt unangetastet.

class Teamrolle(Base):
    __tablename__ = "teamrollen"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_teamrollen_tenant_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Systemrollen (Owner/Admin/Mitarbeiter/Nur-Lesen): Name + Löschen gesperrt.
    # Owner zusätzlich komplett read-only (auch Permissions), das wird im
    # Router erzwungen, nicht hier im Modell.
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    beschreibung: Mapped[str | None] = mapped_column(Text, nullable=True)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Permission(Base):
    """Globaler Permission-Katalog – kein tenant_id, wird per Migration gepflegt."""
    __tablename__ = "permissions"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    bereich: Mapped[str] = mapped_column(String(50), nullable=False)
    beschreibung: Mapped[str] = mapped_column(Text, nullable=False)


class TeamrollePermission(Base):
    __tablename__ = "teamrolle_permissions"

    teamrolle_id: Mapped[int] = mapped_column(ForeignKey("teamrollen.id"), primary_key=True)
    permission_key: Mapped[str] = mapped_column(ForeignKey("permissions.key"), primary_key=True)


class AuditLogEintrag(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, index=True
    )
    actor_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    aktion: Mapped[str] = mapped_column(String(100), nullable=False)
    ziel_typ: Mapped[str] = mapped_column(String(50), nullable=False)
    ziel_id: Mapped[str] = mapped_column(String(100), nullable=False)
    vorher: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON-Text
    nachher: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON-Text
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ── KPIs & Dashboard-Layout (RBAC Phase 2/3) ──────────────────────────────────

class KpiDefinition(Base):
    """
    Eine Kennzahl: entweder System-KPI (is_system=True, Wert über einen fest
    programmierten Resolver in kpi_registry.SYSTEM_KPI_RESOLVER berechnet)
    oder Custom-KPI (generischer Builder: quelle/feld/aggregation/filters
    gegen kpi_registry.REGISTRY validiert).
    """
    __tablename__ = "kpi_definitions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_kpi_definitions_tenant_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    beschreibung: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Nur für Custom-KPIs (is_system=False) gesetzt.
    quelle: Mapped[str | None] = mapped_column(String(50), nullable=True)
    feld: Mapped[str | None] = mapped_column(String(100), nullable=True)
    aggregation: Mapped[str | None] = mapped_column(String(20), nullable=True)
    filters_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    zeitraum_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    darstellungstyp: Mapped[str] = mapped_column(String(20), nullable=False, default="zahl")
    format: Mapped[str | None] = mapped_column(String(20), nullable=True)  # eur|stunden|prozent|anzahl
    # Ohne diese Permission ist der berechnete Wert serverseitig nicht Teil
    # der Response (siehe Phase-1-Prinzip bei Marge-Feldern).
    required_permission: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    def get_filters(self) -> list[dict]:
        return json.loads(self.filters_json) if self.filters_json else []

    def set_filters(self, filters: list[dict]) -> None:
        self.filters_json = json.dumps(filters) if filters else None

    def get_zeitraum(self) -> dict | None:
        return json.loads(self.zeitraum_json) if self.zeitraum_json else None

    def set_zeitraum(self, zeitraum: dict | None) -> None:
        self.zeitraum_json = json.dumps(zeitraum) if zeitraum else None


class DashboardLayout(Base):
    """
    Layout pro Scope. scope_ref_id ist NIE NULL (Sentinel '' für
    'tenant_default'), da NULL in einem Unique-Constraint auf Postgres/SQLite
    nicht als Duplikat erkannt würde – mit '' funktioniert die Eindeutigkeit
    (tenant_id, scope, scope_ref_id) echt.

    Auflösungsreihenfolge beim Laden: user > role > tenant_default > Code-
    seitiger Systemdefault (siehe router._standard_layout).
    """
    __tablename__ = "dashboard_layouts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "scope", "scope_ref_id", name="uq_dashboard_layouts_scope"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, index=True
    )
    scope: Mapped[str] = mapped_column(String(20), nullable=False)  # 'tenant_default' | 'role' | 'user'
    scope_ref_id: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    layout_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(36), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    def get_layout(self) -> list[dict]:
        return json.loads(self.layout_json)

    def set_layout(self, layout: list[dict]) -> None:
        self.layout_json = json.dumps(layout)
