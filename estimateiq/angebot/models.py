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
    # Rolle innerhalb des Tenants: 'admin' (Vollzugriff) oder 'mitglied'
    rolle: Mapped[str] = mapped_column(String(20), nullable=False, default="mitglied")


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
