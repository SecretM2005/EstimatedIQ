"""
FastAPI-Router für Angebotskalkulation MVP.
Alle Endpunkte unter /api/v2/

Multi-Tenancy: Jeder Endpunkt löst über get_current_user() den Tenant aus dem
Supabase-JWT auf und filtert JEDE Query darauf. Objekte fremder Tenants
verhalten sich wie nicht existent (404).

RBAC (Phase 1): zwei orthogonale Ebenen.
  1. Permissions (require_permission): darf diese Art von Aktion überhaupt.
  2. Ownership (_darf_bearbeiten/_ist_sichtbar): darf er DIESES Objekt.
projekte.alle_ansehen hebt die Ownership-Einschränkung sowohl beim Lesen als
auch beim Schreiben auf. projekte.marge_einsehen steuert, ob interne
Kosten-/Stundensatz-Felder überhaupt in der Response landen (separates
Response-Schema, kein Entfernen von Dict-Keys nach der Serialisierung).
"""

from __future__ import annotations
import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from estimateiq.angebot.auth import CurrentUser, get_current_user, get_tenant_id, require_permission
from estimateiq.angebot.database import get_db
from estimateiq.angebot.models import (
    AuditLogEintrag, Permission, Rolle, Projekt, Leistungsposition, Angebot,
    Tenant, TenantUser, Teamrolle, TeamrollePermission,
)
from estimateiq.angebot.permissions import GUELTIGE_KEYS
from estimateiq.angebot.similarity import suche_aehnliche, suche_aehnliche_projekte
from estimateiq.angebot.csv_import import parse_upload
from estimateiq.angebot.pdf_export import erstelle_angebots_pdf

logger  = logging.getLogger(__name__)
router  = APIRouter(prefix="/api/v2", tags=["angebotskalkulation"])

PDF_DIR = Path(__file__).resolve().parents[2] / "data" / "angebote_pdf"
PDF_DIR.mkdir(parents=True, exist_ok=True)


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class RolleCreate(BaseModel):
    name: str
    stundensatz_eur: float

class RolleUpdate(BaseModel):
    name: str | None = None
    stundensatz_eur: float | None = None

class RolleOut(BaseModel):
    id: int
    name: str
    stundensatz_eur: float
    gueltig_ab: datetime
    model_config = {"from_attributes": True}


class ProjektCreate(BaseModel):
    name: str
    beschreibung: str = ""
    kunde: str = ""
    leitung: str = ""
    auftragswert: float | None = None
    abrechnung_typ: str = ""
    laufzeit_start: str = ""
    laufzeit_end: str = ""

class ProjektUpdate(BaseModel):
    name: str | None = None
    beschreibung: str | None = None
    kunde: str | None = None
    status: str | None = None
    leitung: str | None = None
    auftragswert: float | None = None
    abrechnung_typ: str | None = None
    laufzeit_start: str | None = None
    laufzeit_end: str | None = None

class ProjektBasisOut(BaseModel):
    """Ohne interne Kosten/Marge – Standard ohne projekte.marge_einsehen."""
    id: int
    name: str
    beschreibung: str
    kunde: str
    status: str
    ist_referenz: bool = False
    ersteller_id: str | None = None
    darf_bearbeiten: bool = True
    ablehnungsgrund: str | None = None
    leitung: str | None = None
    auftragswert: float | None = None
    abrechnung_typ: str | None = None
    laufzeit_start: str | None = None
    laufzeit_end: str | None = None
    erstellt_am: datetime
    soll_stunden_gesamt: float = 0.0
    ist_stunden_gesamt: float = 0.0
    model_config = {"from_attributes": True}

class ProjektMitMargeOut(ProjektBasisOut):
    """Zusätzlich interne Kosten – nur mit projekte.marge_einsehen."""
    soll_kosten: float = 0.0
    ist_kosten: float = 0.0


class StatusUpdate(BaseModel):
    status: str
    ablehnungsgrund: str | None = None


class PositionCreate(BaseModel):
    beschreibung_text: str
    soll_stunden: float
    rolle_id: int | None = None
    stundensatz_eur: float | None = None  # überschreibt den Rollensatz
    phase: str = ""

class PositionIstUpdate(BaseModel):
    ist_stunden: float

class PositionBasisOut(BaseModel):
    """Ohne Stundensatz – Standard ohne projekte.marge_einsehen."""
    id: int
    projekt_id: int
    beschreibung_text: str
    soll_stunden: float
    ist_stunden: float | None
    phase: str | None = None
    rolle_id: int | None
    rolle_name: str | None = None
    ist_historisch: bool
    erstellt_am: datetime
    model_config = {"from_attributes": True}

class PositionMitMargeOut(PositionBasisOut):
    """Zusätzlich Stundensatz – nur mit projekte.marge_einsehen."""
    stundensatz_snapshot: float | None = None


class SucheRequest(BaseModel):
    beschreibung_text: str
    k: int = 5
    nur_historisch: bool = False
    exclude_projekt_id: int | None = None


class AngebotCreate(BaseModel):
    titel: str = ""

class AngebotOut(BaseModel):
    id: int
    projekt_id: int
    titel: str
    status: str
    pdf_pfad: str | None
    erstellt_am: datetime
    model_config = {"from_attributes": True}


# ── Hilfsfunktionen: Sichtbarkeit, Ownership, Marge-Schema ───────────────────

def _ist_sichtbar(projekt: Projekt, user: CurrentUser) -> bool:
    """
    Lese-Sichtbarkeit: mit projekte.alle_ansehen alles; sonst eigene Projekte
    plus firmenweite (ersteller_id=NULL, z. B. importierte Referenzdaten).
    """
    if user.hat_permission("projekte.alle_ansehen"):
        return True
    if projekt.ersteller_id is None:
        return True
    return projekt.ersteller_id == user.user_id


def _darf_bearbeiten(projekt: Projekt, user: CurrentUser) -> bool:
    """
    Schreibrecht: mit projekte.alle_ansehen alles; sonst nur eigene Projekte.
    Firmenweite Projekte (ersteller_id=NULL) sind sichtbar, aber NICHT von
    jedem editierbar – nur von wer alle_ansehen hat.
    """
    if user.hat_permission("projekte.alle_ansehen"):
        return True
    return projekt.ersteller_id is not None and projekt.ersteller_id == user.user_id


def _projekt_out(p: Projekt, user: CurrentUser) -> ProjektBasisOut:
    """Erstellt das passende Schema (mit/ohne Marge) inkl. Aggregaten."""
    hat_marge = user.hat_permission("projekte.marge_einsehen")
    schema = ProjektMitMargeOut if hat_marge else ProjektBasisOut
    out = schema.model_validate(p)

    aktiv = [pos for pos in p.positionen if not pos.ist_historisch]
    out.soll_stunden_gesamt = sum(pos.soll_stunden for pos in aktiv)
    out.ist_stunden_gesamt  = sum(pos.ist_stunden or 0.0 for pos in aktiv)
    if hat_marge:
        out.soll_kosten = sum(pos.soll_stunden * (pos.stundensatz_snapshot or 0.0) for pos in aktiv)
        out.ist_kosten  = sum((pos.ist_stunden or 0.0) * (pos.stundensatz_snapshot or 0.0) for pos in aktiv)
    out.darf_bearbeiten = _darf_bearbeiten(p, user)
    return out


def _position_out(pos: Leistungsposition, user: CurrentUser, rolle_name: str | None = None) -> PositionBasisOut:
    hat_marge = user.hat_permission("projekte.marge_einsehen")
    schema = PositionMitMargeOut if hat_marge else PositionBasisOut
    out = schema.model_validate(pos)
    out.rolle_name = rolle_name if rolle_name is not None else (pos.rolle.name if pos.rolle else None)
    return out


def _hole_projekt(db: Session, user: CurrentUser, projekt_id: int) -> Projekt:
    """Lädt ein Projekt tenant- und sichtbarkeitssicher oder wirft 404."""
    projekt = (
        db.query(Projekt)
        .filter(Projekt.id == projekt_id, Projekt.tenant_id == user.tenant_id)
        .first()
    )
    if not projekt or not _ist_sichtbar(projekt, user):
        raise HTTPException(404, "Projekt nicht gefunden.")
    return projekt


def _hole_position(db: Session, user: CurrentUser, position_id: int) -> Leistungsposition:
    """Lädt eine Position tenant- und sichtbarkeitssicher (über das Projekt) oder wirft 404."""
    pos = (
        db.query(Leistungsposition)
        .filter(
            Leistungsposition.id == position_id,
            Leistungsposition.tenant_id == user.tenant_id,
        )
        .first()
    )
    if not pos or not _ist_sichtbar(pos.projekt, user):
        raise HTTPException(404, "Position nicht gefunden.")
    return pos


def _log_audit(
    db: Session, user: CurrentUser, aktion: str, ziel_typ: str, ziel_id: str,
    vorher: dict | None = None, nachher: dict | None = None,
) -> None:
    db.add(AuditLogEintrag(
        tenant_id=user.tenant_id,
        actor_user_id=user.user_id,
        aktion=aktion,
        ziel_typ=ziel_typ,
        ziel_id=str(ziel_id),
        vorher=json.dumps(vorher, default=str) if vorher is not None else None,
        nachher=json.dumps(nachher, default=str) if nachher is not None else None,
    ))


# ── Rollen (Stundensatz-Rollen – NICHT die RBAC-Teamrollen weiter unten) ─────

@router.get("/rollen", response_model=list[RolleOut])
def liste_rollen(
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
):
    return (
        db.query(Rolle)
        .filter(Rolle.tenant_id == tenant_id)
        .order_by(Rolle.name)
        .all()
    )


@router.post("/rollen", response_model=RolleOut, status_code=201)
def erstelle_rolle(
    body: RolleCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("rollen.verwalten")),
):
    existiert = (
        db.query(Rolle)
        .filter(Rolle.tenant_id == user.tenant_id, Rolle.name == body.name)
        .first()
    )
    if existiert:
        raise HTTPException(409, f"Rolle '{body.name}' existiert bereits.")
    rolle = Rolle(tenant_id=user.tenant_id, name=body.name, stundensatz_eur=body.stundensatz_eur)
    db.add(rolle)
    db.commit()
    db.refresh(rolle)
    return rolle


@router.put("/rollen/{rolle_id}", response_model=RolleOut)
def aktualisiere_rolle(
    rolle_id: int,
    body: RolleUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("rollen.verwalten")),
):
    rolle = (
        db.query(Rolle)
        .filter(Rolle.id == rolle_id, Rolle.tenant_id == user.tenant_id)
        .first()
    )
    if not rolle:
        raise HTTPException(404, "Rolle nicht gefunden.")
    if body.name is not None:
        rolle.name = body.name
    if body.stundensatz_eur is not None:
        rolle.stundensatz_eur = body.stundensatz_eur
    db.commit()
    db.refresh(rolle)
    return rolle


@router.delete("/rollen/{rolle_id}", status_code=204)
def loesche_rolle(
    rolle_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("rollen.verwalten")),
):
    rolle = (
        db.query(Rolle)
        .filter(Rolle.id == rolle_id, Rolle.tenant_id == user.tenant_id)
        .first()
    )
    if not rolle:
        raise HTTPException(404, "Rolle nicht gefunden.")
    # Referenzen lösen, damit das Löschen auch mit FK-Constraints (Postgres) klappt
    (
        db.query(Leistungsposition)
        .filter(
            Leistungsposition.tenant_id == user.tenant_id,
            Leistungsposition.rolle_id == rolle_id,
        )
        .update({Leistungsposition.rolle_id: None})
    )
    db.delete(rolle)
    db.commit()


# ── Projekte ──────────────────────────────────────────────────────────────────

@router.get("/projekte")
def liste_projekte(
    nur_meine: bool = False,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Kein Permission-Gate hier – Lesen ist grundsätzlich erlaubt, das ERGEBNIS
    wird gefiltert: ohne projekte.alle_ansehen nur eigene + firmenweite
    Projekte (siehe _ist_sichtbar).
    """
    q = db.query(Projekt).filter(Projekt.tenant_id == user.tenant_id)
    if not user.hat_permission("projekte.alle_ansehen"):
        q = q.filter(or_(Projekt.ersteller_id == user.user_id, Projekt.ersteller_id.is_(None)))
    if nur_meine:
        q = q.filter(Projekt.ersteller_id == user.user_id)
    projekte = q.order_by(Projekt.erstellt_am.desc()).all()
    return [_projekt_out(p, user) for p in projekte]


@router.post("/projekte", status_code=201)
def erstelle_projekt(
    body: ProjektCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("projekte.erstellen")),
):
    projekt = Projekt(
        tenant_id=user.tenant_id,
        ersteller_id=user.user_id,
        name=body.name, beschreibung=body.beschreibung, kunde=body.kunde,
        leitung=body.leitung or None, auftragswert=body.auftragswert,
        abrechnung_typ=body.abrechnung_typ or None,
        laufzeit_start=body.laufzeit_start or None,
        laufzeit_end=body.laufzeit_end or None,
    )
    db.add(projekt)
    db.commit()
    db.refresh(projekt)
    return _projekt_out(projekt, user)


@router.get("/projekte/{projekt_id}")
def hole_projekt(
    projekt_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return _projekt_out(_hole_projekt(db, user, projekt_id), user)


@router.patch("/projekte/{projekt_id}")
def aktualisiere_projekt(
    projekt_id: int,
    body: ProjektUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("projekte.bearbeiten")),
):
    projekt = _hole_projekt(db, user, projekt_id)
    if not _darf_bearbeiten(projekt, user):
        raise HTTPException(403, "Keine Berechtigung, dieses Projekt zu bearbeiten.")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(projekt, field, val)
    db.commit()
    db.refresh(projekt)
    return _projekt_out(projekt, user)


@router.delete("/projekte/{projekt_id}", status_code=204)
def loesche_projekt(
    projekt_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("projekte.loeschen")),
):
    projekt = _hole_projekt(db, user, projekt_id)
    if not _darf_bearbeiten(projekt, user):
        raise HTTPException(403, "Keine Berechtigung, dieses Projekt zu löschen.")
    db.delete(projekt)
    db.commit()


@router.patch("/projekte/{projekt_id}/status")
def setze_projekt_status(
    projekt_id: int,
    body: StatusUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("projekte.status_aendern")),
):
    VALID = {"entwurf", "angeboten", "beauftragt", "abgeschlossen", "abgelehnt"}
    if body.status not in VALID:
        raise HTTPException(400, f"Ungültiger Status: {body.status}")
    p = _hole_projekt(db, user, projekt_id)
    if not _darf_bearbeiten(p, user):
        raise HTTPException(403, "Keine Berechtigung, den Status dieses Projekts zu ändern.")
    p.status = body.status
    if body.ablehnungsgrund is not None:
        p.ablehnungsgrund = body.ablehnungsgrund
    db.commit()
    db.refresh(p)
    return _projekt_out(p, user)


@router.get("/dashboard/stats")
def dashboard_stats(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("dashboard.view")),
):
    """
    Aggregierte Kennzahlen für das Dashboard. Ohne projekte.alle_ansehen nur
    über eigene + firmenweite Projekte aggregiert; ohne projekte.marge_einsehen
    fehlen die €-Felder komplett (nicht nur 0).

    Bekannte Einschränkung Phase 1: Das bestehende Dashboard.jsx zeigt Pipeline-
    Werte auch direkt aus GET /projekte (p.soll_kosten) – für Mitarbeiter ohne
    marge_einsehen fehlen diese Werte dort ebenfalls und die entsprechenden
    Kacheln zeigen aktuell keine sinnvollen Zahlen. Eine bedingte Darstellung
    im Dashboard ist für Phase 2 (Dashboard-Layout) vorgesehen.
    """
    hat_marge = user.hat_permission("projekte.marge_einsehen")
    hat_alle  = user.hat_permission("projekte.alle_ansehen")

    q = db.query(Projekt).filter(Projekt.tenant_id == user.tenant_id)
    if not hat_alle:
        q = q.filter(or_(Projekt.ersteller_id == user.user_id, Projekt.ersteller_id.is_(None)))
    sichtbar = [p for p in q.all() if p.name != "__historisch__" and not p.ist_referenz]

    counts: dict[str, int] = {}
    for p in sichtbar:
        counts[p.status] = counts.get(p.status, 0) + 1

    def projekt_wert(p: Projekt) -> float:
        return sum(
            pos.soll_stunden * (pos.stundensatz_snapshot or 0.0)
            for pos in p.positionen
            if not pos.ist_historisch
        )

    gewonnen = counts.get("beauftragt", 0) + counts.get("abgeschlossen", 0)
    verloren = counts.get("abgelehnt", 0)
    total_entschieden = gewonnen + verloren

    recent = sorted(sichtbar, key=lambda p: p.erstellt_am, reverse=True)[:8]
    recent_out = []
    for p in recent:
        eintrag = {
            "id": p.id, "name": p.name, "status": p.status,
            "kunde": p.kunde or "–", "erstellt_am": p.erstellt_am.isoformat(),
        }
        if hat_marge:
            eintrag["wert"] = projekt_wert(p)
        recent_out.append(eintrag)

    ergebnis = {
        "counts": counts,
        "n_offen": counts.get("entwurf", 0) + counts.get("angeboten", 0),
        "n_beauftragt": counts.get("beauftragt", 0),
        "n_abgeschlossen": counts.get("abgeschlossen", 0),
        "n_abgelehnt": counts.get("abgelehnt", 0),
        "gewinnrate": gewonnen / total_entschieden if total_entschieden > 0 else None,
        "recent": recent_out,
    }
    if hat_marge:
        ergebnis["wert_offen"] = sum(projekt_wert(p) for p in sichtbar if p.status in ("entwurf", "angeboten"))
        ergebnis["wert_beauftragt"] = sum(projekt_wert(p) for p in sichtbar if p.status in ("beauftragt", "abgeschlossen"))
    return ergebnis


# ── Leistungspositionen ───────────────────────────────────────────────────────

@router.get("/projekte/{projekt_id}/positionen")
def liste_positionen(
    projekt_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    _hole_projekt(db, user, projekt_id)  # Sichtbarkeit prüfen, wirft 404
    positionen = (
        db.query(Leistungsposition)
        .filter(
            Leistungsposition.tenant_id == user.tenant_id,
            Leistungsposition.projekt_id == projekt_id,
        )
        .order_by(Leistungsposition.erstellt_am)
        .all()
    )
    return [_position_out(p, user) for p in positionen]


@router.post("/projekte/{projekt_id}/positionen", status_code=201)
def erstelle_position(
    projekt_id: int,
    body: PositionCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("positionen.bearbeiten")),
):
    projekt = _hole_projekt(db, user, projekt_id)
    if not _darf_bearbeiten(projekt, user):
        raise HTTPException(403, "Keine Berechtigung, Positionen dieses Projekts zu ändern.")

    rolle = None
    if body.rolle_id:
        rolle = (
            db.query(Rolle)
            .filter(Rolle.id == body.rolle_id, Rolle.tenant_id == user.tenant_id)
            .first()
        )
        if not rolle:
            raise HTTPException(404, "Rolle nicht gefunden.")

    # Expliziter Satz schlägt Rollensatz
    if body.stundensatz_eur is not None:
        stundensatz_snapshot = body.stundensatz_eur
    elif rolle:
        stundensatz_snapshot = rolle.stundensatz_eur
    else:
        stundensatz_snapshot = None

    try:
        from estimateiq.angebot.embeddings import embed
        vec = embed(body.beschreibung_text)
    except Exception as e:
        logger.warning("Embedding fehlgeschlagen: %s", e)
        vec = None

    pos = Leistungsposition(
        tenant_id=user.tenant_id,
        projekt_id=projekt_id,
        rolle_id=body.rolle_id,
        beschreibung_text=body.beschreibung_text,
        soll_stunden=body.soll_stunden,
        stundensatz_snapshot=stundensatz_snapshot,
        phase=body.phase or None,
    )
    if vec:
        pos.set_embedding(vec)

    db.add(pos)
    db.commit()
    db.refresh(pos)

    return _position_out(pos, user, rolle_name=rolle.name if rolle else None)


@router.patch("/positionen/{position_id}/ist-stunden")
def trage_ist_stunden_nach(
    position_id: int,
    body: PositionIstUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("positionen.bearbeiten")),
):
    pos = _hole_position(db, user, position_id)
    if not _darf_bearbeiten(pos.projekt, user):
        raise HTTPException(403, "Keine Berechtigung, dieses Projekt zu bearbeiten.")
    pos.ist_stunden = body.ist_stunden
    db.commit()
    db.refresh(pos)
    return _position_out(pos, user)


@router.delete("/positionen/{position_id}", status_code=204)
def loesche_position(
    position_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("positionen.bearbeiten")),
):
    pos = _hole_position(db, user, position_id)
    if not _darf_bearbeiten(pos.projekt, user):
        raise HTTPException(403, "Keine Berechtigung, Positionen dieses Projekts zu ändern.")
    db.delete(pos)
    db.commit()


# ── Ähnlichkeitssuche ─────────────────────────────────────────────────────────
# Bewusst OHNE Permission-Gate und ohne alle_ansehen-Filterung: liefert nur
# Textfragmente + Stunden (keine Kunden-/Ersteller-Zuordnung), ist eine
# Wissensbasis-Abfrage über historische Arbeit, kein "fremdes Projekt ansehen".

@router.post("/positionen/suche")
def suche_positionen(
    body: SucheRequest,
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
):
    try:
        from estimateiq.angebot.embeddings import embed
        vec = embed(body.beschreibung_text)
    except Exception as e:
        raise HTTPException(503, f"Embedding-Modell nicht verfügbar: {e}")

    return suche_aehnliche(
        query_vec=vec,
        db=db,
        tenant_id=tenant_id,
        k=body.k,
        nur_historisch=body.nur_historisch,
        exclude_projekt_id=body.exclude_projekt_id,
    )


# ── CSV/Excel-Import ──────────────────────────────────────────────────────────

@router.post("/import/positionen")
async def importiere_positionen(
    file: UploadFile = File(...),
    db:   Session    = Depends(get_db),
    user: CurrentUser = Depends(require_permission("import.durchfuehren")),
):
    tenant_id = user.tenant_id
    data   = await file.read()
    parsed = parse_upload(data, file.filename or "upload.csv")

    try:
        from estimateiq.angebot.embeddings import embed, embed_batch
    except Exception as e:
        logger.warning("Embedding-Modul nicht verfügbar: %s", e)
        embed = embed_batch = None  # type: ignore[assignment]

    rollen_cache: dict[str, Rolle] = {}
    importiert = 0

    def _hole_oder_erstelle_rolle(name: str) -> int | None:
        if not name:
            return None
        if name not in rollen_cache:
            rolle = (
                db.query(Rolle)
                .filter(Rolle.tenant_id == tenant_id, Rolle.name == name)
                .first()
            )
            if not rolle:
                rolle = Rolle(tenant_id=tenant_id, name=name, stundensatz_eur=0.0)
                db.add(rolle)
                db.flush()
            rollen_cache[name] = rolle
        return rollen_cache[name].id

    if parsed["hat_projekt_spalte"]:
        # ── Projektweiser Import (Referenzprojekte) ──────────────────────────
        if not parsed["projekte"]:
            return {"importiert": 0, "fehler": parsed["fehler"], "stats": parsed["stats"]}

        for proj_data in parsed["projekte"]:
            proj_name = proj_data["name"]
            positionen_data = proj_data["positionen"]

            # Bestehendes Referenzprojekt finden oder neu anlegen
            ref_projekt = db.query(Projekt).filter(
                Projekt.tenant_id == tenant_id,
                Projekt.name == proj_name,
                Projekt.ist_referenz == True,  # noqa: E712
            ).first()
            if not ref_projekt:
                ref_projekt = Projekt(
                    tenant_id=tenant_id,
                    name=proj_name, kunde="Referenz",
                    status="abgeschlossen", ist_referenz=True,
                )
                db.add(ref_projekt)
                db.flush()

            # Positionen + Embeddings
            texte = [p["beschreibung_text"] for p in positionen_data]
            vecs  = embed_batch(texte) if embed_batch else [None] * len(texte)

            for i, p_data in enumerate(positionen_data):
                pos = Leistungsposition(
                    tenant_id=tenant_id,
                    projekt_id=ref_projekt.id,
                    rolle_id=_hole_oder_erstelle_rolle(p_data.get("rolle_name") or ""),
                    beschreibung_text=p_data["beschreibung_text"],
                    soll_stunden=p_data["soll_stunden"],
                    ist_stunden=p_data.get("ist_stunden"),
                    stundensatz_snapshot=p_data.get("stundensatz_snapshot"),
                    ist_historisch=False,
                )
                if vecs and vecs[i] is not None:
                    pos.set_embedding(vecs[i])
                db.add(pos)
                importiert += 1

            db.flush()

            # Projekt-Embedding: Projektname + alle Positionstexte
            if embed:
                try:
                    kombiniert = proj_name + ". " + " | ".join(texte[:10])
                    ref_projekt.set_embedding(embed(kombiniert))
                except Exception as e:
                    logger.warning("Projekt-Embedding fehlgeschlagen (%s): %s", proj_name, e)

        db.commit()

    else:
        # ── Flat-Import (ohne Projekt-Spalte, alter Modus) ───────────────────
        einzelpositionen = parsed["einzelpositionen"]
        if not einzelpositionen:
            return {"importiert": 0, "fehler": parsed["fehler"], "stats": parsed["stats"]}

        texte = [p["beschreibung_text"] for p in einzelpositionen]
        vecs  = embed_batch(texte) if embed_batch else [None] * len(texte)

        HIST_NAME = "__historisch__"
        hist_projekt = db.query(Projekt).filter(
            Projekt.tenant_id == tenant_id,
            Projekt.name == HIST_NAME,
        ).first()
        if not hist_projekt:
            hist_projekt = Projekt(
                tenant_id=tenant_id,
                name=HIST_NAME, kunde="Import", status="abgeschlossen",
            )
            db.add(hist_projekt)
            db.flush()

        for i, p_data in enumerate(einzelpositionen):
            pos = Leistungsposition(
                tenant_id=tenant_id,
                projekt_id=hist_projekt.id,
                rolle_id=_hole_oder_erstelle_rolle(p_data.get("rolle_name") or ""),
                beschreibung_text=p_data["beschreibung_text"],
                soll_stunden=p_data["soll_stunden"],
                ist_stunden=p_data.get("ist_stunden"),
                ist_historisch=True,
            )
            if vecs and vecs[i] is not None:
                pos.set_embedding(vecs[i])
            db.add(pos)
            importiert += 1

        db.commit()

    return {"importiert": importiert, "fehler": parsed["fehler"], "stats": parsed["stats"]}


# ── Referenzprojekt-Suche ─────────────────────────────────────────────────────
# Ebenfalls ohne Permission-Gate – siehe Begründung bei /positionen/suche.
# Referenzprojekte sind grundsätzlich firmenweite Daten (ist_referenz=true,
# ersteller_id=NULL) und damit laut _ist_sichtbar ohnehin für alle sichtbar.

class ReferenzSucheRequest(BaseModel):
    beschreibung: str        # Projektbeschreibung (primär)
    name: str = ""           # Projektname (wird angehängt)
    k: int = 3
    exclude_projekt_id: int | None = None


@router.post("/referenzprojekte/suche")
def suche_referenzprojekte(
    body: ReferenzSucheRequest,
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
):
    # Beschreibung ist primär; Name wird nachgestellt für zusätzlichen Kontext
    suchtext = body.beschreibung.strip()
    if body.name.strip() and body.name.strip() not in suchtext:
        suchtext = suchtext + ". " + body.name.strip() if suchtext else body.name.strip()

    try:
        from estimateiq.angebot.embeddings import embed
        vec = embed(suchtext)
    except Exception as e:
        raise HTTPException(503, f"Embedding-Modell nicht verfügbar: {e}")

    return suche_aehnliche_projekte(
        query_vec=vec,
        db=db,
        tenant_id=tenant_id,
        k=body.k,
        exclude_projekt_id=body.exclude_projekt_id,
    )


# ── Vorlage übernehmen ────────────────────────────────────────────────────────

@router.post("/projekte/{projekt_id}/positionen/aus-referenz/{referenz_id}", status_code=201)
def vorlage_uebernehmen(
    projekt_id:   int,
    referenz_id:  int,
    db:           Session = Depends(get_db),
    user:         CurrentUser = Depends(require_permission("positionen.bearbeiten")),
):
    """Kopiert alle Positionen eines Referenzprojekts in das Zielprojekt."""
    ziel = _hole_projekt(db, user, projekt_id)
    if not _darf_bearbeiten(ziel, user):
        raise HTTPException(403, "Keine Berechtigung, dieses Projekt zu bearbeiten.")
    ref = (
        db.query(Projekt)
        .filter(Projekt.id == referenz_id, Projekt.tenant_id == user.tenant_id)
        .first()
    )
    if not ref or not ref.ist_referenz:
        raise HTTPException(404, "Referenzprojekt nicht gefunden.")

    quell_positionen = (
        db.query(Leistungsposition)
        .filter(
            Leistungsposition.tenant_id == user.tenant_id,
            Leistungsposition.projekt_id == referenz_id,
        )
        .order_by(Leistungsposition.erstellt_am)
        .all()
    )

    kopiert = 0
    for src in quell_positionen:
        neu = Leistungsposition(
            tenant_id=user.tenant_id,
            projekt_id=projekt_id,
            rolle_id=src.rolle_id,
            beschreibung_text=src.beschreibung_text,
            soll_stunden=src.soll_stunden,
            stundensatz_snapshot=src.stundensatz_snapshot,
            embedding=src.embedding,
            ist_historisch=False,
        )
        db.add(neu)
        kopiert += 1

    db.commit()
    return {"kopiert": kopiert, "aus_projekt": ref.name}


# ── Angebote ──────────────────────────────────────────────────────────────────

@router.post("/projekte/{projekt_id}/angebote", response_model=AngebotOut, status_code=201)
def erstelle_angebot(
    projekt_id: int,
    body: AngebotCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("projekte.status_aendern")),
):
    projekt = _hole_projekt(db, user, projekt_id)
    if not _darf_bearbeiten(projekt, user):
        raise HTTPException(403, "Keine Berechtigung, für dieses Projekt ein Angebot zu erstellen.")
    angebot = Angebot(
        tenant_id=user.tenant_id,
        projekt_id=projekt_id,
        titel=body.titel or f"Angebot {projekt.name}",
    )
    db.add(angebot)
    db.commit()
    db.refresh(angebot)
    return angebot


@router.get("/angebote/{angebot_id}/pdf")
def exportiere_pdf(
    angebot_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Kein marge_einsehen-Gate: Das PDF zeigt Kunden-Verkaufspreise, die der
    Kunde ohnehin erhält – wer das Projekt sehen darf, darf auch das PDF.
    """
    angebot = (
        db.query(Angebot)
        .filter(Angebot.id == angebot_id, Angebot.tenant_id == user.tenant_id)
        .first()
    )
    if not angebot:
        raise HTTPException(404, "Angebot nicht gefunden.")

    projekt = angebot.projekt
    if not _ist_sichtbar(projekt, user):
        raise HTTPException(404, "Angebot nicht gefunden.")

    positionen_db = (
        db.query(Leistungsposition)
        .filter(
            Leistungsposition.tenant_id == user.tenant_id,
            Leistungsposition.projekt_id == angebot.projekt_id,
            Leistungsposition.ist_historisch == False,  # noqa: E712
        )
        .order_by(Leistungsposition.erstellt_am)
        .all()
    )

    positionen_pdf = []
    for i, pos in enumerate(positionen_db, 1):
        satz = pos.stundensatz_snapshot or 0.0
        positionen_pdf.append({
            "nr":          i,
            "beschreibung": pos.beschreibung_text,
            "rolle":        pos.rolle.name if pos.rolle else "–",
            "stunden":      pos.soll_stunden,
            "stundensatz":  satz,
            "summe":        pos.soll_stunden * satz,
        })

    tenant = db.get(Tenant, user.tenant_id)
    firmenname = tenant.name if tenant and tenant.name else "Ihr Unternehmen"

    pdf_bytes = erstelle_angebots_pdf(
        angebot_nr=f"A-{angebot.id:04d}",
        firmenname=firmenname,
        kunde=projekt.kunde or "–",
        projekt_name=projekt.name,
        positionen=positionen_pdf,
        erstellt_am=angebot.erstellt_am,
    )

    pfad = PDF_DIR / f"angebot_{angebot.id}.pdf"
    pfad.write_bytes(pdf_bytes)
    angebot.pdf_pfad = str(pfad)
    db.commit()

    return FileResponse(
        path=str(pfad),
        media_type="application/pdf",
        filename=f"Angebot-{angebot.id:04d}.pdf",
    )


# ── Aktueller Benutzer ────────────────────────────────────────────────────────

class MeOut(BaseModel):
    user_id: str
    email: str | None = None
    teamrolle_id: int | None = None
    teamrolle_name: str
    permissions: list[str]
    tenant_id: str
    tenant_name: str | None = None


@router.get("/me", response_model=MeOut)
def hole_aktuellen_benutzer(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Kontext des angemeldeten Benutzers (für Permission-Gating im Frontend)."""
    tenant = db.get(Tenant, user.tenant_id)
    return MeOut(
        user_id=user.user_id,
        email=user.email,
        teamrolle_id=user.teamrolle_id,
        teamrolle_name=user.teamrolle_name,
        permissions=sorted(user.permissions),
        tenant_id=user.tenant_id,
        tenant_name=tenant.name if tenant else None,
    )


# ── Teamrollen ────────────────────────────────────────────────────────────────

class TeamrolleOut(BaseModel):
    id: int
    name: str
    is_system: bool
    beschreibung: str | None = None
    permissions: list[str]

class TeamrolleCreate(BaseModel):
    name: str
    beschreibung: str | None = None
    permissions: list[str] = []

class TeamrolleUpdate(BaseModel):
    name: str | None = None
    beschreibung: str | None = None
    permissions: list[str] | None = None


def _teamrolle_out(db: Session, rolle: Teamrolle) -> TeamrolleOut:
    keys = [
        k for (k,) in db.query(TeamrollePermission.permission_key)
        .filter(TeamrollePermission.teamrolle_id == rolle.id).all()
    ]
    return TeamrolleOut(
        id=rolle.id, name=rolle.name, is_system=rolle.is_system,
        beschreibung=rolle.beschreibung, permissions=sorted(keys),
    )


def _hole_teamrolle(db: Session, user: CurrentUser, teamrolle_id: int) -> Teamrolle:
    rolle = (
        db.query(Teamrolle)
        .filter(Teamrolle.id == teamrolle_id, Teamrolle.tenant_id == user.tenant_id)
        .first()
    )
    if not rolle:
        raise HTTPException(404, "Teamrolle nicht gefunden.")
    return rolle


@router.get("/teamrollen", response_model=list[TeamrolleOut])
def liste_teamrollen(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("settings.manage_users")),
):
    rollen = db.query(Teamrolle).filter(Teamrolle.tenant_id == user.tenant_id).order_by(Teamrolle.name).all()
    return [_teamrolle_out(db, r) for r in rollen]


@router.post("/teamrollen", response_model=TeamrolleOut, status_code=201)
def erstelle_teamrolle(
    body: TeamrolleCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("settings.manage_users")),
):
    unbekannt = set(body.permissions) - GUELTIGE_KEYS
    if unbekannt:
        raise HTTPException(400, f"Unbekannte Permission-Keys: {sorted(unbekannt)}")
    nicht_besessen = set(body.permissions) - user.permissions
    if nicht_besessen:
        raise HTTPException(403, f"Kann Rechte nicht vergeben, die man selbst nicht besitzt: {sorted(nicht_besessen)}")

    if db.query(Teamrolle).filter(Teamrolle.tenant_id == user.tenant_id, Teamrolle.name == body.name).first():
        raise HTTPException(409, f"Teamrolle '{body.name}' existiert bereits.")

    rolle = Teamrolle(tenant_id=user.tenant_id, name=body.name, is_system=False, beschreibung=body.beschreibung)
    db.add(rolle)
    db.flush()
    for key in body.permissions:
        db.add(TeamrollePermission(teamrolle_id=rolle.id, permission_key=key))
    db.commit()
    _log_audit(db, user, "teamrolle_angelegt", "teamrolle", rolle.id, nachher={"name": rolle.name, "permissions": body.permissions})
    db.commit()
    return _teamrolle_out(db, rolle)


@router.patch("/teamrollen/{teamrolle_id}", response_model=TeamrolleOut)
def aktualisiere_teamrolle(
    teamrolle_id: int,
    body: TeamrolleUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("settings.manage_users")),
):
    rolle = _hole_teamrolle(db, user, teamrolle_id)

    if rolle.is_system and rolle.name == "Owner":
        raise HTTPException(403, "Die Owner-Rolle ist nicht veränderbar.")
    if rolle.is_system and (body.name is not None or body.beschreibung is not None):
        raise HTTPException(403, "Name und Beschreibung von Systemrollen sind gesperrt.")

    vorher = _teamrolle_out(db, rolle).model_dump()

    if body.permissions is not None:
        unbekannt = set(body.permissions) - GUELTIGE_KEYS
        if unbekannt:
            raise HTTPException(400, f"Unbekannte Permission-Keys: {sorted(unbekannt)}")
        nicht_besessen = set(body.permissions) - user.permissions
        if nicht_besessen:
            raise HTTPException(403, f"Kann Rechte nicht vergeben, die man selbst nicht besitzt: {sorted(nicht_besessen)}")
        db.query(TeamrollePermission).filter(TeamrollePermission.teamrolle_id == rolle.id).delete()
        for key in body.permissions:
            db.add(TeamrollePermission(teamrolle_id=rolle.id, permission_key=key))

    if body.name is not None:
        rolle.name = body.name
    if body.beschreibung is not None:
        rolle.beschreibung = body.beschreibung

    db.commit()
    nachher = _teamrolle_out(db, rolle).model_dump()
    _log_audit(db, user, "teamrolle_geaendert", "teamrolle", rolle.id, vorher=vorher, nachher=nachher)
    db.commit()
    return _teamrolle_out(db, rolle)


@router.delete("/teamrollen/{teamrolle_id}", status_code=204)
def loesche_teamrolle(
    teamrolle_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("settings.manage_users")),
):
    rolle = _hole_teamrolle(db, user, teamrolle_id)
    if rolle.is_system:
        raise HTTPException(403, "Systemrollen können nicht gelöscht werden.")
    in_benutzung = db.query(TenantUser).filter(TenantUser.teamrolle_id == rolle.id).count()
    if in_benutzung:
        raise HTTPException(409, f"Rolle ist {in_benutzung} Mitglied(ern) zugewiesen und kann nicht gelöscht werden.")

    db.query(TeamrollePermission).filter(TeamrollePermission.teamrolle_id == rolle.id).delete()
    db.delete(rolle)
    _log_audit(db, user, "teamrolle_geloescht", "teamrolle", teamrolle_id)
    db.commit()


# ── Permission-Katalog (für den Rollen-Editor) ───────────────────────────────

class PermissionOut(BaseModel):
    key: str
    bereich: str
    beschreibung: str
    model_config = {"from_attributes": True}


@router.get("/permissions", response_model=list[PermissionOut])
def liste_permissions(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("settings.manage_users")),
):
    return db.query(Permission).order_by(Permission.bereich, Permission.key).all()


# ── Team ──────────────────────────────────────────────────────────────────────

class TeamMemberOut(BaseModel):
    user_id: str
    email: str | None = None
    teamrolle_id: int
    teamrolle_name: str
    status: str

class TeamMemberCreate(BaseModel):
    email: str
    passwort: str
    teamrolle_id: int

class TeamMemberRolleUpdate(BaseModel):
    teamrolle_id: int


def _team_member_out(tu: TenantUser) -> TeamMemberOut:
    return TeamMemberOut(
        user_id=tu.user_id, email=tu.email, teamrolle_id=tu.teamrolle_id,
        teamrolle_name=tu.teamrolle.name, status=tu.status,
    )


def _zahl_owner(db: Session, tenant_id: str) -> int:
    owner_rolle = db.query(Teamrolle).filter(Teamrolle.tenant_id == tenant_id, Teamrolle.name == "Owner").first()
    if not owner_rolle:
        return 0
    return db.query(TenantUser).filter(
        TenantUser.tenant_id == tenant_id, TenantUser.teamrolle_id == owner_rolle.id,
    ).count()


@router.get("/team", response_model=list[TeamMemberOut])
def liste_team(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("settings.manage_users")),
):
    mitglieder = (
        db.query(TenantUser)
        .filter(TenantUser.tenant_id == user.tenant_id)
        .order_by(TenantUser.email)
        .all()
    )
    return [_team_member_out(m) for m in mitglieder]


@router.post("/team", response_model=TeamMemberOut, status_code=201)
def erstelle_team_mitglied(
    body: TeamMemberCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("settings.manage_users")),
):
    ziel_rolle = _hole_teamrolle(db, user, body.teamrolle_id)
    if ziel_rolle.name == "Owner" and not user.ist_owner:
        raise HTTPException(403, "Nur ein Owner darf die Owner-Rolle vergeben.")

    vorhanden = (
        db.query(TenantUser)
        .filter(TenantUser.tenant_id == user.tenant_id, TenantUser.email == body.email)
        .first()
    )
    if vorhanden:
        raise HTTPException(409, f"Ein Benutzer mit E-Mail '{body.email}' existiert bereits.")

    from estimateiq.angebot import supabase_admin
    try:
        neue_user_id = supabase_admin.create_auth_user(body.email, body.passwort)
    except supabase_admin.AdminNichtKonfiguriert as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Benutzer konnte in Supabase nicht angelegt werden: {exc}")

    tu = TenantUser(
        user_id=neue_user_id, tenant_id=user.tenant_id, email=body.email,
        teamrolle_id=body.teamrolle_id, status="aktiv",
    )
    db.add(tu)
    db.commit()
    _log_audit(db, user, "team_mitglied_angelegt", "tenant_user", tu.user_id,
               nachher={"email": tu.email, "teamrolle": ziel_rolle.name})
    db.commit()
    return _team_member_out(tu)


@router.patch("/team/{user_id}", response_model=TeamMemberOut)
def aendere_team_rolle(
    user_id: str,
    body: TeamMemberRolleUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("settings.manage_users")),
):
    tu = (
        db.query(TenantUser)
        .filter(TenantUser.user_id == user_id, TenantUser.tenant_id == user.tenant_id)
        .first()
    )
    if not tu:
        raise HTTPException(404, "Benutzer nicht gefunden.")

    neue_rolle = _hole_teamrolle(db, user, body.teamrolle_id)
    alte_rolle_name = tu.teamrolle.name

    if neue_rolle.name == "Owner" and not user.ist_owner:
        raise HTTPException(403, "Nur ein Owner darf die Owner-Rolle vergeben.")
    if alte_rolle_name == "Owner" and neue_rolle.name != "Owner" and _zahl_owner(db, user.tenant_id) <= 1:
        raise HTTPException(400, "Der letzte Owner eines Tenants kann nicht degradiert werden.")

    tu.teamrolle_id = body.teamrolle_id
    db.commit()
    _log_audit(db, user, "team_rolle_geaendert", "tenant_user", user_id,
               vorher={"teamrolle": alte_rolle_name}, nachher={"teamrolle": neue_rolle.name})
    db.commit()
    return _team_member_out(tu)


@router.delete("/team/{user_id}", status_code=204)
def loesche_team_mitglied(
    user_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("settings.manage_users")),
):
    tu = (
        db.query(TenantUser)
        .filter(TenantUser.user_id == user_id, TenantUser.tenant_id == user.tenant_id)
        .first()
    )
    if not tu:
        raise HTTPException(404, "Benutzer nicht gefunden.")

    if tu.teamrolle.name == "Owner" and _zahl_owner(db, user.tenant_id) <= 1:
        raise HTTPException(400, "Der letzte Owner eines Tenants kann nicht entfernt werden.")

    from estimateiq.angebot import supabase_admin
    try:
        supabase_admin.delete_auth_user(user_id)
    except Exception as exc:
        logger.warning("Auth-User %s konnte nicht gelöscht werden: %s", user_id, exc)

    _log_audit(db, user, "team_mitglied_entfernt", "tenant_user", user_id,
               vorher={"email": tu.email, "teamrolle": tu.teamrolle.name})
    db.delete(tu)
    db.commit()


# ── Audit-Log ─────────────────────────────────────────────────────────────────

class AuditLogOut(BaseModel):
    id: int
    actor_user_id: str
    aktion: str
    ziel_typ: str
    ziel_id: str
    vorher: dict | None = None
    nachher: dict | None = None
    erstellt_am: datetime


def _audit_out(e: AuditLogEintrag) -> AuditLogOut:
    return AuditLogOut(
        id=e.id, actor_user_id=e.actor_user_id, aktion=e.aktion,
        ziel_typ=e.ziel_typ, ziel_id=e.ziel_id,
        vorher=json.loads(e.vorher) if e.vorher else None,
        nachher=json.loads(e.nachher) if e.nachher else None,
        erstellt_am=e.erstellt_am,
    )


@router.get("/audit-log", response_model=list[AuditLogOut])
def liste_audit_log(
    limit: int = 100,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("settings.manage_users")),
):
    eintraege = (
        db.query(AuditLogEintrag)
        .filter(AuditLogEintrag.tenant_id == user.tenant_id)
        .order_by(AuditLogEintrag.erstellt_am.desc())
        .limit(min(limit, 500))
        .all()
    )
    return [_audit_out(e) for e in eintraege]
