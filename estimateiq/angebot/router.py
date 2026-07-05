"""
FastAPI-Router für Angebotskalkulation MVP.
Alle Endpunkte unter /api/v2/
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from estimateiq.angebot.database import get_db
from estimateiq.angebot.models import Rolle, Projekt, Leistungsposition, Angebot
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

class ProjektUpdate(BaseModel):
    name: str | None = None
    beschreibung: str | None = None
    kunde: str | None = None
    status: str | None = None

class ProjektOut(BaseModel):
    id: int
    name: str
    beschreibung: str
    kunde: str
    status: str
    ablehnungsgrund: str | None = None
    erstellt_am: datetime
    model_config = {"from_attributes": True}


class StatusUpdate(BaseModel):
    status: str
    ablehnungsgrund: str | None = None


class PositionCreate(BaseModel):
    beschreibung_text: str
    soll_stunden: float
    rolle_id: int | None = None
    stundensatz_eur: float | None = None  # überschreibt den Rollensatz

class PositionIstUpdate(BaseModel):
    ist_stunden: float

class PositionOut(BaseModel):
    id: int
    projekt_id: int
    beschreibung_text: str
    soll_stunden: float
    ist_stunden: float | None
    stundensatz_snapshot: float | None
    rolle_id: int | None
    rolle_name: str | None = None
    ist_historisch: bool
    erstellt_am: datetime
    model_config = {"from_attributes": True}


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


# ── Rollen ────────────────────────────────────────────────────────────────────

@router.get("/rollen", response_model=list[RolleOut])
def liste_rollen(db: Session = Depends(get_db)):
    return db.query(Rolle).order_by(Rolle.name).all()


@router.post("/rollen", response_model=RolleOut, status_code=201)
def erstelle_rolle(body: RolleCreate, db: Session = Depends(get_db)):
    if db.query(Rolle).filter(Rolle.name == body.name).first():
        raise HTTPException(409, f"Rolle '{body.name}' existiert bereits.")
    rolle = Rolle(name=body.name, stundensatz_eur=body.stundensatz_eur)
    db.add(rolle)
    db.commit()
    db.refresh(rolle)
    return rolle


@router.put("/rollen/{rolle_id}", response_model=RolleOut)
def aktualisiere_rolle(rolle_id: int, body: RolleUpdate, db: Session = Depends(get_db)):
    rolle = db.get(Rolle, rolle_id)
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
def loesche_rolle(rolle_id: int, db: Session = Depends(get_db)):
    rolle = db.get(Rolle, rolle_id)
    if not rolle:
        raise HTTPException(404, "Rolle nicht gefunden.")
    db.delete(rolle)
    db.commit()


# ── Projekte ──────────────────────────────────────────────────────────────────

@router.get("/projekte", response_model=list[ProjektOut])
def liste_projekte(db: Session = Depends(get_db)):
    return db.query(Projekt).order_by(Projekt.erstellt_am.desc()).all()


@router.post("/projekte", response_model=ProjektOut, status_code=201)
def erstelle_projekt(body: ProjektCreate, db: Session = Depends(get_db)):
    projekt = Projekt(name=body.name, beschreibung=body.beschreibung, kunde=body.kunde)
    db.add(projekt)
    db.commit()
    db.refresh(projekt)
    return projekt


@router.get("/projekte/{projekt_id}", response_model=ProjektOut)
def hole_projekt(projekt_id: int, db: Session = Depends(get_db)):
    projekt = db.get(Projekt, projekt_id)
    if not projekt:
        raise HTTPException(404, "Projekt nicht gefunden.")
    return projekt


@router.patch("/projekte/{projekt_id}", response_model=ProjektOut)
def aktualisiere_projekt(projekt_id: int, body: ProjektUpdate, db: Session = Depends(get_db)):
    projekt = db.get(Projekt, projekt_id)
    if not projekt:
        raise HTTPException(404, "Projekt nicht gefunden.")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(projekt, field, val)
    db.commit()
    db.refresh(projekt)
    return projekt


@router.delete("/projekte/{projekt_id}", status_code=204)
def loesche_projekt(projekt_id: int, db: Session = Depends(get_db)):
    projekt = db.get(Projekt, projekt_id)
    if not projekt:
        raise HTTPException(404, "Projekt nicht gefunden.")
    db.delete(projekt)
    db.commit()


@router.patch("/projekte/{projekt_id}/status", response_model=ProjektOut)
def setze_projekt_status(projekt_id: int, body: StatusUpdate, db: Session = Depends(get_db)):
    VALID = {"entwurf", "angeboten", "beauftragt", "abgeschlossen", "abgelehnt"}
    if body.status not in VALID:
        raise HTTPException(400, f"Ungültiger Status: {body.status}")
    p = db.get(Projekt, projekt_id)
    if not p:
        raise HTTPException(404, "Projekt nicht gefunden.")
    p.status = body.status
    if body.ablehnungsgrund is not None:
        p.ablehnungsgrund = body.ablehnungsgrund
    db.commit()
    db.refresh(p)
    return p


@router.get("/dashboard/stats")
def dashboard_stats(db: Session = Depends(get_db)):
    """Aggregierte Kennzahlen für das Dashboard."""
    sichtbar = [
        p for p in db.query(Projekt).all()
        if p.name != "__historisch__" and not p.ist_referenz
    ]

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

    wert_offen = sum(projekt_wert(p) for p in sichtbar if p.status in ("entwurf", "angeboten"))
    wert_beauftragt = sum(projekt_wert(p) for p in sichtbar if p.status in ("beauftragt", "abgeschlossen"))

    recent = sorted(sichtbar, key=lambda p: p.erstellt_am, reverse=True)[:8]

    return {
        "counts": counts,
        "n_offen": counts.get("entwurf", 0) + counts.get("angeboten", 0),
        "n_beauftragt": counts.get("beauftragt", 0),
        "n_abgeschlossen": counts.get("abgeschlossen", 0),
        "n_abgelehnt": counts.get("abgelehnt", 0),
        "gewinnrate": gewonnen / total_entschieden if total_entschieden > 0 else None,
        "wert_offen": wert_offen,
        "wert_beauftragt": wert_beauftragt,
        "recent": [
            {
                "id": p.id,
                "name": p.name,
                "status": p.status,
                "kunde": p.kunde or "–",
                "wert": projekt_wert(p),
                "erstellt_am": p.erstellt_am.isoformat(),
            }
            for p in recent
        ],
    }


# ── Leistungspositionen ───────────────────────────────────────────────────────

@router.get("/projekte/{projekt_id}/positionen", response_model=list[PositionOut])
def liste_positionen(projekt_id: int, db: Session = Depends(get_db)):
    positionen = (
        db.query(Leistungsposition)
        .filter(Leistungsposition.projekt_id == projekt_id)
        .order_by(Leistungsposition.erstellt_am)
        .all()
    )
    result = []
    for p in positionen:
        out = PositionOut.model_validate(p)
        out.rolle_name = p.rolle.name if p.rolle else None
        result.append(out)
    return result


@router.post("/projekte/{projekt_id}/positionen", response_model=PositionOut, status_code=201)
def erstelle_position(projekt_id: int, body: PositionCreate, db: Session = Depends(get_db)):
    if not db.get(Projekt, projekt_id):
        raise HTTPException(404, "Projekt nicht gefunden.")

    rolle = db.get(Rolle, body.rolle_id) if body.rolle_id else None
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
        projekt_id=projekt_id,
        rolle_id=body.rolle_id,
        beschreibung_text=body.beschreibung_text,
        soll_stunden=body.soll_stunden,
        stundensatz_snapshot=stundensatz_snapshot,
    )
    if vec:
        pos.set_embedding(vec)

    db.add(pos)
    db.commit()
    db.refresh(pos)

    out = PositionOut.model_validate(pos)
    out.rolle_name = rolle.name if rolle else None
    return out


@router.patch("/positionen/{position_id}/ist-stunden", response_model=PositionOut)
def trage_ist_stunden_nach(position_id: int, body: PositionIstUpdate, db: Session = Depends(get_db)):
    pos = db.get(Leistungsposition, position_id)
    if not pos:
        raise HTTPException(404, "Position nicht gefunden.")
    pos.ist_stunden = body.ist_stunden
    db.commit()
    db.refresh(pos)
    out = PositionOut.model_validate(pos)
    out.rolle_name = pos.rolle.name if pos.rolle else None
    return out


@router.delete("/positionen/{position_id}", status_code=204)
def loesche_position(position_id: int, db: Session = Depends(get_db)):
    pos = db.get(Leistungsposition, position_id)
    if not pos:
        raise HTTPException(404, "Position nicht gefunden.")
    db.delete(pos)
    db.commit()


# ── Ähnlichkeitssuche ─────────────────────────────────────────────────────────

@router.post("/positionen/suche")
def suche_positionen(body: SucheRequest, db: Session = Depends(get_db)):
    try:
        from estimateiq.angebot.embeddings import embed
        vec = embed(body.beschreibung_text)
    except Exception as e:
        raise HTTPException(503, f"Embedding-Modell nicht verfügbar: {e}")

    return suche_aehnliche(
        query_vec=vec,
        db=db,
        k=body.k,
        nur_historisch=body.nur_historisch,
        exclude_projekt_id=body.exclude_projekt_id,
    )


# ── CSV/Excel-Import ──────────────────────────────────────────────────────────

@router.post("/import/positionen")
async def importiere_positionen(
    file: UploadFile = File(...),
    db:   Session    = Depends(get_db),
):
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
            rolle = db.query(Rolle).filter(Rolle.name == name).first()
            if not rolle:
                rolle = Rolle(name=name, stundensatz_eur=0.0)
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
                Projekt.name == proj_name,
                Projekt.ist_referenz == True,  # noqa: E712
            ).first()
            if not ref_projekt:
                ref_projekt = Projekt(
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
        hist_projekt = db.query(Projekt).filter(Projekt.name == HIST_NAME).first()
        if not hist_projekt:
            hist_projekt = Projekt(name=HIST_NAME, kunde="Import", status="abgeschlossen")
            db.add(hist_projekt)
            db.flush()

        for i, p_data in enumerate(einzelpositionen):
            pos = Leistungsposition(
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

class ReferenzSucheRequest(BaseModel):
    beschreibung: str        # Projektbeschreibung (primär)
    name: str = ""           # Projektname (wird angehängt)
    k: int = 3
    exclude_projekt_id: int | None = None


@router.post("/referenzprojekte/suche")
def suche_referenzprojekte(body: ReferenzSucheRequest, db: Session = Depends(get_db)):
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
        k=body.k,
        exclude_projekt_id=body.exclude_projekt_id,
    )


# ── Vorlage übernehmen ────────────────────────────────────────────────────────

@router.post("/projekte/{projekt_id}/positionen/aus-referenz/{referenz_id}", status_code=201)
def vorlage_uebernehmen(
    projekt_id:   int,
    referenz_id:  int,
    db:           Session = Depends(get_db),
):
    """Kopiert alle Positionen eines Referenzprojekts in das Zielprojekt."""
    if not db.get(Projekt, projekt_id):
        raise HTTPException(404, "Zielprojekt nicht gefunden.")
    ref = db.get(Projekt, referenz_id)
    if not ref or not ref.ist_referenz:
        raise HTTPException(404, "Referenzprojekt nicht gefunden.")

    quell_positionen = (
        db.query(Leistungsposition)
        .filter(Leistungsposition.projekt_id == referenz_id)
        .order_by(Leistungsposition.erstellt_am)
        .all()
    )

    kopiert = 0
    for src in quell_positionen:
        neu = Leistungsposition(
            projekt_id=projekt_id,
            rolle_id=src.rolle_id,
            beschreibung_text=src.beschreibung_text,
            soll_stunden=src.soll_stunden,
            stundensatz_snapshot=src.stundensatz_snapshot,
            embedding_json=src.embedding_json,
            ist_historisch=False,
        )
        db.add(neu)
        kopiert += 1

    db.commit()
    return {"kopiert": kopiert, "aus_projekt": ref.name}


# ── Angebote ──────────────────────────────────────────────────────────────────

@router.post("/projekte/{projekt_id}/angebote", response_model=AngebotOut, status_code=201)
def erstelle_angebot(projekt_id: int, body: AngebotCreate, db: Session = Depends(get_db)):
    projekt = db.get(Projekt, projekt_id)
    if not projekt:
        raise HTTPException(404, "Projekt nicht gefunden.")
    angebot = Angebot(
        projekt_id=projekt_id,
        titel=body.titel or f"Angebot {projekt.name}",
    )
    db.add(angebot)
    db.commit()
    db.refresh(angebot)
    return angebot


@router.get("/angebote/{angebot_id}/pdf")
def exportiere_pdf(angebot_id: int, db: Session = Depends(get_db)):
    angebot = db.get(Angebot, angebot_id)
    if not angebot:
        raise HTTPException(404, "Angebot nicht gefunden.")

    projekt = angebot.projekt
    positionen_db = (
        db.query(Leistungsposition)
        .filter(
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

    pdf_bytes = erstelle_angebots_pdf(
        angebot_nr=f"A-{angebot.id:04d}",
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
