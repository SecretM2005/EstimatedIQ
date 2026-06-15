"""
EstimateIQ FastAPI – zweistufige Kostenschätzungs-Pipeline.

Endpoints:
  POST /api/estimate             – ML-Projektschätzung
  POST /api/upload-training-data – Eigene Projektdaten hochladen
  POST /api/retrain              – Modell nach Upload neu trainieren
  GET  /api/retrain/status       – Retrain-Fortschritt pollen
  GET  /api/download-template    – CSV-Vorlage herunterladen
"""

import asyncio
import io
import json
import logging
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_PATH        = Path("data/processed/notices.parquet")
USER_DATA_FILE   = Path("data/raw_user_uploads.jsonl")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
_executor        = ThreadPoolExecutor(max_workers=1)

# Retrain-Status (in-memory, genug für Single-Worker-Deployment)
_retrain_state: dict = {"status": "idle", "mdape": None, "n": None, "error": None}

# Flexible Spalten-Erkennung (case-insensitiv)
_SPALTEN_KANDIDATEN: dict[str, list[str]] = {
    "beschreibung": ["beschreibung", "description", "projekt", "projektname",
                     "title", "name", "projektbeschreibung", "aufgabe"],
    "dauer_tage":   ["dauer_tage", "duration", "laufzeit", "days", "dauer",
                     "tage", "laufzeit_tage", "projekttage"],
    "region":       ["region", "standort", "location", "ort", "bundesland", "land"],
    "technologie":  ["technologie", "technology", "stack", "tech", "sprache", "language"],
    "projekttyp":   ["projekttyp", "type", "kategorie", "typ", "art", "project_type"],
    "teamgroesse":  ["teamgroesse", "team", "mitarbeiter", "teamgröße",
                     "team_size", "team_groesse", "personen"],
    "jahr":         ["jahr", "year", "datum", "date", "abschluss"],
    "kosten":       ["kosten", "budget", "cost", "preis", "budget_eur", "preis_eur", "betrag"],
}

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class EstimateRequest(BaseModel):
    beschreibung: Annotated[str, Field(min_length=10, max_length=10_000,
                                       description="Projektbeschreibung")]
    region: str = Field(default="DE", description="ISO 3166-2 Region (z.B. DE-BY, AT, CH)")
    projekt_groesse: Literal["klein", "mittel", "gross"] = Field(
        default="mittel",
        description=(
            "Projektgröße: 'klein' (Freelancer/Solo, bis ~3 Monate), "
            "'mittel' (kleines Team, Standard), 'gross' (Enterprise/Behörde)"
        ),
    )
    verfuegbare_teamgroesse: float | None = Field(
        default=None,
        ge=1, le=200,
        description="Tatsächlich verfügbares Team in Personen (optional). "
                    "Löst Assessment 'zu_klein'/'passend'/'zu_gross' aus.",
    )


class SimilarProject(BaseModel):
    titel:      str
    budget_eur: float
    dauer_tage: float | None = None


class EstimateResponse(BaseModel):
    dauer_tage:          float
    personalkosten:      float
    kosten_min:          float
    kosten_expected:     float
    kosten_max:          float
    overhead_faktor:     float
    confidence_score:    float
    top_risks:           list[str]
    similar_projects:    list[SimilarProject]
    projekt_groesse:     str   = "mittel"
    teamgroesse:         float = 2.0
    teamgroesse_modell:  float = 2.0
    team_assessment:     str | None = None


class HealthResponse(BaseModel):
    status:        str
    pipeline_ready: bool
    data_ready:    bool


# ---------------------------------------------------------------------------
# App-Lebenszyklus
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("EstimateIQ API startet – lade Pipeline-Modelle...")
    try:
        from estimateiq.models.estimate_pipeline import _lade_duration_modell
        _lade_duration_modell()
        logger.info("Laufzeit-Modell geladen.")
    except FileNotFoundError as exc:
        logger.warning("Modell noch nicht trainiert: %s", exc)
    except Exception as exc:
        logger.warning("Modell-Vorlade fehlgeschlagen: %s", exc)
    yield


app = FastAPI(
    title="EstimateIQ API",
    description="ML-basierte Projektkostenschätzung für IT-Dienstleister im DACH-Raum",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

# Keyword → Risikotext
_KEYWORD_RISIKEN: list[tuple[list[str], str]] = [
    (["sap", "erp", "migration"],
     "SAP/ERP-Schnittstellenkomplexität kann Integrationsdauer um 30–50 % verlängern."),
    (["cloud", "aws", "azure", "kubernetes", "docker"],
     "Cloud-Kosten ohne Monitoring schnell unkontrollierbar – Budgetobergrenze früh definieren."),
    (["dsgvo", "gdpr", "datenschutz", "sicherheit", "security", "nis2"],
     "Datenschutz- und Sicherheitsanforderungen erzeugen häufig ungeplantem Mehraufwand."),
    (["legacy", "ablösung", "datenmigration", "bestandssystem"],
     "Legacy-Abhängigkeiten erhöhen das Risiko von Datenmigrationsverzögerungen erheblich."),
    (["schnittstelle", "api", "anbindung", "integration", "webhook"],
     "Externe API-Anbindungen erfordern verlässliche Dokumentation und Testumgebungen beim Drittanbieter."),
    (["mobil", "mobile", "ios", "android", "app"],
     "Mobile-Entwicklung für iOS und Android verdoppelt typischerweise Test- und Review-Aufwand."),
    (["deadline", "termin", "q1", "q2", "q3", "q4", "jahresende"],
     "Feste Deadlines erhöhen das Risiko von Scope-Creep und Qualitätseinbußen unter Zeitdruck."),
    (["ki", "ai", "ml", "machine learning", "llm", "gpt"],
     "KI-Komponenten haben hohe Evaluierungs- und Nachtrainingskosten; ROI unsicher in MVP-Projekten."),
    (["nutzer", "mitarbeiter", "200", "500", "1000", "user"],
     "Nutzerverwaltung für größere Userzahlen erfordert Skalierbarkeits- und Lastplanung."),
]

_PROJEKTTYP_FALLBACK: dict[str, str] = {
    "Softwareentwicklung":           "Anforderungsänderungen sind der häufigste Kostentreiber – agiles Vorgehen empfohlen.",
    "Datenverarbeitung & Analytics": "Datenqualität wird systematisch unterschätzt; Bereinigung kostet bis zu 30 % des Aufwands.",
    "Internet- & Cloud-Dienste":     "Vendor-Lock-in bei Cloud-Diensten kann spätere Migrationskosten massiv erhöhen.",
    "IT-Betrieb & Wartung":          "SLA-Anforderungen treiben Bereitschaftskosten; Eskalationsprozesse früh definieren.",
    "Netzwerk & Infrastruktur":      "Hardware-Lieferzeiten können Projektstart um 6–12 Wochen verzögern.",
    "IT-Beratung & Support":         "Wissenstransfer-Phasen werden häufig im Budget nicht eingeplant.",
    "IT-Hardware & Systeme":         "Kompatibilitätsrisiken mit Bestandssystemen schwer vorab quantifizierbar.",
}


def _generiere_risiken(beschreibung: str, projekttyp: str, ergebnis) -> list[str]:
    text = beschreibung.lower()
    risiken: list[str] = []

    for keywords, risikotext in _KEYWORD_RISIKEN:
        if any(kw in text for kw in keywords):
            risiken.append(risikotext)
        if len(risiken) >= 3:
            break

    if len(risiken) < 3 and projekttyp in _PROJEKTTYP_FALLBACK:
        risiken.append(_PROJEKTTYP_FALLBACK[projekttyp])

    if len(risiken) < 3:
        try:
            ratio = ergebnis.tagespreis_p90 / max(1.0, ergebnis.tagespreis_p10)
            if ratio > 8:
                risiken.append(
                    f"Hohe Kostenstreuung (Faktor {ratio:.0f}×) in vergleichbaren Projekten – "
                    "intensive Anforderungsklärung vor Angebotserstellung empfohlen."
                )
        except Exception:
            pass

    if not risiken:
        risiken.append("Allgemeines Risiko: Anforderungsänderungen können Budget und Zeitplan beeinflussen.")

    return risiken[:3]


def _finde_aehnliche_projekte(projekttyp: str, budget_target: float, n: int = 3) -> list[dict]:
    if not DATA_PATH.exists():
        return []
    try:
        df = pd.read_parquet(DATA_PATH)
        df_budget = df[df["budget_eur"].notna() & (df["budget_eur"] > 0)].copy()
        df_typ = df_budget[df_budget["projekttyp"] == projekttyp]
        # Fall back auf alle Projekte wenn zu wenig vom gleichen Typ
        if len(df_typ) < n:
            df_typ = df_budget
        df_typ = df_typ.copy()
        df_typ["_dist"] = (
            np.log1p(df_typ["budget_eur"]) - np.log1p(budget_target)
        ).abs()
        df_nahe = df_typ.nsmallest(n, "_dist")

        projekte = []
        for _, row in df_nahe.iterrows():
            text = str(row.get("beschreibung") or "")
            titel = text[:90].rsplit(" ", 1)[0] + "…" if len(text) > 90 else text
            projekte.append({
                "titel":      titel or "IT-Projekt",
                "budget_eur": float(row["budget_eur"]),
                "dauer_tage": float(row["dauer_tage"]) if pd.notna(row.get("dauer_tage")) else None,
            })
        return projekte
    except Exception as exc:
        logger.warning("Ähnliche Projekte konnten nicht geladen werden: %s", exc)
        return []


def _confidence_score(ergebnis) -> float:
    """Schmaleres Konfidenzintervall → höhere Konfidenz."""
    try:
        ratio = ergebnis.kosten_high / max(1.0, ergebnis.kosten_low)
        conf  = float(np.clip(1.0 - 0.35 * np.log(max(1.0, ratio)), 0.10, 0.92))
        return conf
    except Exception:
        return 0.5


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    from estimateiq.models.duration_model import MODELL_PKL as DUR_PKL
    pipeline_ok = DUR_PKL.exists()
    return HealthResponse(
        status="ok",
        pipeline_ready=pipeline_ok,
        data_ready=DATA_PATH.exists(),
    )


@app.post("/api/estimate", response_model=EstimateResponse, tags=["Schätzung"])
async def estimate(req: EstimateRequest):
    """
    Schätzt Projektkosten via zweistufiger ML-Pipeline.

    - **beschreibung**: Freitext-Projektbeschreibung (mind. 10 Zeichen)
    - **region**: ISO 3166-2 (DE, DE-BY, DE-BW, DE-NW, AT, CH, ...)
    """
    try:
        from estimateiq.models.estimate_pipeline import estimate as pipeline_estimate

        land = req.region[:2].upper() if req.region else "DE"
        ergebnis = pipeline_estimate(
            beschreibung          = req.beschreibung,
            land                  = land,
            region                = req.region,
            datenquelle           = "ted",
            projekt_groesse       = req.projekt_groesse,
            teamgroesse_override  = req.verfuegbare_teamgroesse,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Pipeline-Modell nicht trainiert. "
                f"Bitte zuerst ausführen: python train.py --only pipeline. ({exc})"
            ),
        ) from exc
    except Exception as exc:
        logger.exception("Pipeline-Fehler: %s", exc)
        raise HTTPException(status_code=500, detail=f"Interner Fehler: {exc}") from exc

    risiken   = _generiere_risiken(req.beschreibung, ergebnis.projekttyp, ergebnis)
    aehnliche = _finde_aehnliche_projekte(ergebnis.projekttyp, ergebnis.kosten_expected)
    konfidenz = _confidence_score(ergebnis)

    return EstimateResponse(
        dauer_tage       = round(ergebnis.dauer_tage, 1),
        personalkosten   = round(ergebnis.personalkosten, 2),
        kosten_min       = round(ergebnis.kosten_min, 2),
        kosten_expected  = round(ergebnis.kosten_expected, 2),
        kosten_max       = round(ergebnis.kosten_max, 2),
        overhead_faktor  = round(ergebnis.overhead_faktor_p50, 3),
        confidence_score = round(konfidenz, 3),
        top_risks        = risiken,
        similar_projects = [SimilarProject(**p) for p in aehnliche],
        projekt_groesse     = ergebnis.projekt_groesse,
        teamgroesse         = round(ergebnis.teamgroesse, 1),
        teamgroesse_modell  = round(ergebnis.teamgroesse_modell or ergebnis.teamgroesse, 1),
        team_assessment     = ergebnis.team_assessment,
    )


# ---------------------------------------------------------------------------
# Upload-Hilfsfunktionen
# ---------------------------------------------------------------------------

def _erkenne_spalten(df_cols: list[str]) -> tuple[dict[str, str], dict[str, str | None]]:
    """
    Mappt DataFrame-Spalten auf interne Namen.
    Gibt (erkannte_map, alle_felder_mit_quelle) zurück.
    erkannte_map: { interner_name: original_spaltenname }
    """
    cols_lower = {c.lower().strip(): c for c in df_cols}
    erkannt: dict[str, str] = {}

    for intern, kandidaten in _SPALTEN_KANDIDATEN.items():
        for kand in kandidaten:
            if kand in cols_lower:
                erkannt[intern] = cols_lower[kand]
                break

    return erkannt


def _parse_dauer(val) -> int | None:
    try:
        n = int(float(str(val).replace(",", ".")))
        return n if 7 <= n <= 730 else None
    except Exception:
        return None


def _parse_zahl(val) -> float | None:
    try:
        return float(str(val).replace(",", "."))
    except Exception:
        return None


def _zeile_zu_datensatz(
    row: pd.Series,
    spalten: dict[str, str],
    upload_id: str,
    timestamp: str,
) -> tuple[dict | None, str | None]:
    """Konvertiert eine DataFrame-Zeile zu einem JSONL-Datensatz.
    Gibt (datensatz, fehlergrund) zurück."""

    beschreibung = str(row.get(spalten["beschreibung"], "") or "").strip()
    if len(beschreibung) < 20:
        return None, "beschreibung_zu_kurz"

    dauer_raw = row.get(spalten.get("dauer_tage", ""), None) if "dauer_tage" in spalten else None
    dauer_tage = _parse_dauer(dauer_raw)
    if dauer_tage is None:
        return None, "dauer_ausserhalb_bereich"

    region = str(row.get(spalten.get("region", ""), "") or "DE").strip() or "DE"
    technologie = str(row.get(spalten.get("technologie", ""), "") or "").strip() or None
    projekttyp  = str(row.get(spalten.get("projekttyp", ""), "") or "").strip() or None
    jahr_raw    = row.get(spalten.get("jahr", ""), None) if "jahr" in spalten else None
    kosten_raw  = row.get(spalten.get("kosten", ""), None) if "kosten" in spalten else None

    jahr   = _parse_zahl(jahr_raw) if jahr_raw is not None else None
    kosten = _parse_zahl(kosten_raw) if kosten_raw is not None else None

    pub_date = f"{int(jahr)}0101" if jahr else timestamp[:8].replace("-", "")

    datensatz = {
        "document_id":       f"upload_{upload_id}_{uuid.uuid4().hex[:8]}",
        "publication_date":  pub_date,
        "title":             beschreibung[:100],
        "description":       beschreibung,
        "cpv_code":          "72200000",
        "estimated_value":   kosten,
        "currency":          "EUR",
        "country":           region[:2].upper() if region else "DE",
        "duration_end":      None,
        "dauer_tage_direkt": dauer_tage,
        "notice_type":       "user_upload",
        "datenquelle":       "user_upload",
        "technologie":       technologie,
        "upload_timestamp":  timestamp,
        "upload_id":         upload_id,
        "projekttyp_text":   projekttyp,
        "raw":               {},
    }
    return datensatz, None


# ---------------------------------------------------------------------------
# Upload-Endpoint
# ---------------------------------------------------------------------------

@app.post("/api/upload-training-data", tags=["Daten-Upload"])
async def upload_training_data(file: UploadFile = File(...)):
    """
    Lädt eigene historische Projektdaten als CSV oder Excel hoch.
    Pflichtfelder: Beschreibung + Laufzeit in Tagen.
    """
    # Dateityp prüfen
    erlaubt = {".csv", ".xlsx", ".xls"}
    suffix  = Path(file.filename or "").suffix.lower()
    if suffix not in erlaubt:
        raise HTTPException(
            status_code=400,
            detail=f"Nur CSV und Excel erlaubt. Hochgeladen: {suffix or 'unbekannt'}"
        )

    # Größe prüfen
    inhalt = await file.read()
    if len(inhalt) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Datei zu groß ({len(inhalt) // 1024 // 1024} MB). Maximum: 10 MB"
        )

    # Parsen
    try:
        if suffix == ".csv":
            df = pd.read_csv(io.BytesIO(inhalt), dtype=str)
        else:
            df = pd.read_excel(io.BytesIO(inhalt), dtype=str)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Datei konnte nicht geparst werden: {exc}")

    if df.empty:
        raise HTTPException(status_code=422, detail="Datei ist leer.")

    # Pflichtfelder prüfen
    spalten = _erkenne_spalten(list(df.columns))
    fehlend = [f for f in ("beschreibung", "dauer_tage") if f not in spalten]
    if fehlend:
        verfuegbare = ", ".join(f'"{c}"' for c in df.columns[:10])
        raise HTTPException(
            status_code=422,
            detail=(
                f"Pflichtfelder nicht gefunden: {fehlend}. "
                f"Verfügbare Spalten: {verfuegbare}. "
                "Erwartete Namen z.B.: beschreibung, dauer_tage, laufzeit, duration"
            )
        )

    # Zeilenweise verarbeiten
    upload_id  = str(uuid.uuid4())
    timestamp  = datetime.now(timezone.utc).isoformat()
    datensaetze: list[dict] = []
    verworfene_gruende: dict[str, int] = {}
    vorschau: list[dict] = []

    for _, row in df.iterrows():
        ds, grund = _zeile_zu_datensatz(row, spalten, upload_id, timestamp)
        if ds is None:
            verworfene_gruende[grund] = verworfene_gruende.get(grund, 0) + 1
        else:
            datensaetze.append(ds)
            if len(vorschau) < 3:
                vorschau.append({
                    "beschreibung": ds["description"][:80],
                    "dauer_tage":   ds["dauer_tage_direkt"],
                    "region":       ds["country"],
                })

    if not datensaetze:
        raise HTTPException(
            status_code=422,
            detail=(
                "Keine gültigen Zeilen gefunden. "
                "Prüfe: Beschreibung ≥ 20 Zeichen, Laufzeit zwischen 7 und 730 Tagen."
            )
        )

    # An JSONL anhängen
    USER_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with USER_DATA_FILE.open("a", encoding="utf-8") as f:
        for ds in datensaetze:
            f.write(json.dumps(ds, ensure_ascii=False) + "\n")

    logger.info(
        "[Upload] %d/%d Zeilen akzeptiert → %s (upload_id=%s)",
        len(datensaetze), len(df), USER_DATA_FILE, upload_id
    )

    return {
        "success":   True,
        "upload_id": upload_id,
        "stats": {
            "zeilen_gesamt":      len(df),
            "zeilen_akzeptiert":  len(datensaetze),
            "zeilen_verworfen":   len(df) - len(datensaetze),
            "spalten_erkannt":    {intern: orig for intern, orig in spalten.items()},
            "verworfene_gruende": verworfene_gruende,
        },
        "vorschau": vorschau,
    }


# ---------------------------------------------------------------------------
# Retrain-Endpoints
# ---------------------------------------------------------------------------

def _do_retrain() -> dict:
    """Läuft im ThreadPoolExecutor – blockiert den Worker-Thread."""
    import subprocess

    subprocess.run(
        [sys.executable, "-m", "estimateiq.data.preprocess"],
        check=True, timeout=180, capture_output=True,
    )
    subprocess.run(
        [sys.executable, "train.py", "--only", "duration"],
        check=True, timeout=600, capture_output=True,
    )

    # MdAPE aus evaluate.py ermitteln
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    import importlib
    evaluate_mod = importlib.import_module("evaluate")
    importlib.reload(evaluate_mod)
    metrics = evaluate_mod.evaluate()

    df  = pd.read_parquet(DATA_PATH)
    return {
        "mdape": round(metrics["mdape"] / 100, 4),
        "n":     len(df),
    }


@app.post("/api/retrain", tags=["Daten-Upload"])
async def retrain():
    """Startet Preprocessing + Duration-Modell-Training im Hintergrund."""
    global _retrain_state
    if _retrain_state["status"] == "running":
        raise HTTPException(status_code=409, detail="Retrain läuft bereits.")

    _retrain_state = {"status": "running", "mdape": None, "n": None, "error": None}

    async def _run():
        global _retrain_state
        try:
            loop   = asyncio.get_event_loop()
            result = await loop.run_in_executor(_executor, _do_retrain)
            _retrain_state = {"status": "done", "error": None, **result}
        except Exception as exc:
            logger.exception("Retrain fehlgeschlagen: %s", exc)
            _retrain_state = {"status": "error", "mdape": None, "n": None, "error": str(exc)}

    asyncio.create_task(_run())
    return {"status": "started"}


@app.get("/api/retrain/status", tags=["Daten-Upload"])
async def retrain_status():
    """Gibt den aktuellen Retrain-Status zurück (für Polling)."""
    return _retrain_state


# ---------------------------------------------------------------------------
# CSV-Vorlage
# ---------------------------------------------------------------------------

CSV_TEMPLATE = (
    "beschreibung,dauer_tage,region,technologie,teamgroesse,jahr\n"
    '"React Dashboard mit REST API und PostgreSQL-Datenbank",90,DE-BY,React,2,2024\n'
    '"iOS App für Außendienst mit Offline-Synchronisation",120,AT,Mobile,3,2023\n'
    '"WooCommerce-Shop mit Stripe-Zahlungsanbindung",45,CH,PHP,1,2024\n'
)


@app.get("/api/download-template", tags=["Daten-Upload"])
async def download_template():
    """Gibt eine CSV-Vorlage zum Ausfüllen zurück."""
    return StreamingResponse(
        io.BytesIO(CSV_TEMPLATE.encode("utf-8-sig")),  # utf-8-sig für Excel-Kompatibilität
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="estimateiq_vorlage.csv"'},
    )
