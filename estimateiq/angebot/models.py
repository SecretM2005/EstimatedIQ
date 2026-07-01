"""
SQLAlchemy ORM-Modelle für Angebotskalkulation MVP.
"""

import json
from datetime import datetime, timezone
from sqlalchemy import ForeignKey, String, Float, Text, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from estimateiq.angebot.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Rolle(Base):
    __tablename__ = "rollen"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    stundensatz_eur: Mapped[float] = mapped_column(Float, nullable=False)
    gueltig_ab: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    positionen: Mapped[list["Leistungsposition"]] = relationship(back_populates="rolle")


class Projekt(Base):
    __tablename__ = "projekte"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kunde: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(50), default="entwurf")
    ist_referenz: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    def get_embedding(self) -> list[float] | None:
        if not self.embedding_json:
            return None
        return json.loads(self.embedding_json)

    def set_embedding(self, vec: list[float]) -> None:
        self.embedding_json = json.dumps(vec)

    positionen: Mapped[list["Leistungsposition"]] = relationship(
        back_populates="projekt", cascade="all, delete-orphan"
    )
    angebote: Mapped[list["Angebot"]] = relationship(
        back_populates="projekt", cascade="all, delete-orphan"
    )


class Leistungsposition(Base):
    __tablename__ = "leistungspositionen"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    projekt_id: Mapped[int] = mapped_column(ForeignKey("projekte.id"), nullable=False)
    rolle_id: Mapped[int | None] = mapped_column(ForeignKey("rollen.id"), nullable=True)
    beschreibung_text: Mapped[str] = mapped_column(Text, nullable=False)
    soll_stunden: Mapped[float] = mapped_column(Float, nullable=False)
    ist_stunden: Mapped[float | None] = mapped_column(Float, nullable=True)
    stundensatz_snapshot: Mapped[float | None] = mapped_column(Float, nullable=True)
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    ist_historisch: Mapped[bool] = mapped_column(Boolean, default=False)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    projekt: Mapped["Projekt"] = relationship(back_populates="positionen")
    rolle: Mapped["Rolle | None"] = relationship(back_populates="positionen")

    def get_embedding(self) -> list[float] | None:
        if not self.embedding_json:
            return None
        return json.loads(self.embedding_json)

    def set_embedding(self, vec: list[float]) -> None:
        self.embedding_json = json.dumps(vec)


class Angebot(Base):
    __tablename__ = "angebote"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    projekt_id: Mapped[int] = mapped_column(ForeignKey("projekte.id"), nullable=False)
    titel: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(50), default="entwurf")
    pdf_pfad: Mapped[str | None] = mapped_column(String(500), nullable=True)
    versendet_am: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    projekt: Mapped["Projekt"] = relationship(back_populates="angebote")
