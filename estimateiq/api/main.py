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
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
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


class SensitivitaetItem(BaseModel):
    label:          str
    kosten_neu:     float
    delta_eur:      float
    delta_prozent:  float
    richtung:       str   # "teurer" | "günstiger" | "gleich"


class SensitivitaetResponse(BaseModel):
    basis:            float
    sensitivitaeten:  list[SensitivitaetItem]


class EstimateResponse(BaseModel):
    dauer_tage:           float
    personalkosten:       float
    kosten_min:           float
    kosten_expected:      float
    kosten_max:           float
    overhead_faktor:      float
    confidence_score:     float
    top_risks:            list[str]
    similar_projects:     list[SimilarProject]
    projekt_groesse:      str   = "mittel"
    groesse_konfidenz:    float = 0.0
    groesse_auto_erkannt: bool  = False
    teamgroesse:          float = 2.0
    teamgroesse_modell:   float = 2.0
    team_assessment:      str | None = None
    rollen:               list[dict] = []
    komposition_typ:      str = ""


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
        logger.info("IT-Modell geladen.")
    except FileNotFoundError as exc:
        logger.warning("IT-Modell noch nicht trainiert: %s", exc)
    except Exception as exc:
        logger.warning("IT-Modell-Vorlade fehlgeschlagen: %s", exc)
    try:
        _lade_bau_bert()
    except Exception as exc:
        logger.warning("Bau-BERT Vorlade fehlgeschlagen: %s", exc)
    try:
        from estimateiq.angebot.database import init_db
        init_db()
        logger.info("Angebot-Datenbank initialisiert.")
    except Exception as exc:
        logger.warning("Angebot-DB Init fehlgeschlagen: %s", exc)
    yield


app = FastAPI(
    title="EstimateIQ API",
    description="ML-basierte Projektkostenschätzung für IT-Dienstleister im DACH-Raum",
    version="2.0.0",
    lifespan=lifespan,
)

from estimateiq.angebot import config as angebot_config  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=angebot_config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

from estimateiq.angebot.router import router as angebot_router  # noqa: E402
app.include_router(angebot_router)

_STATIC_DIR = Path(__file__).parent / "static"

@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(_STATIC_DIR / "index.html")


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
        dauer_tage            = round(ergebnis.dauer_tage, 1),
        personalkosten        = round(ergebnis.personalkosten, 2),
        kosten_min            = round(ergebnis.kosten_min, 2),
        kosten_expected       = round(ergebnis.kosten_expected, 2),
        kosten_max            = round(ergebnis.kosten_max, 2),
        overhead_faktor       = round(ergebnis.overhead_faktor_p50, 3),
        confidence_score      = round(konfidenz, 3),
        top_risks             = risiken,
        similar_projects      = [SimilarProject(**p) for p in aehnliche],
        projekt_groesse       = ergebnis.projekt_groesse,
        groesse_konfidenz     = round(ergebnis.groesse_konfidenz, 3),
        groesse_auto_erkannt  = ergebnis.groesse_auto_erkannt,
        teamgroesse           = round(ergebnis.teamgroesse, 1),
        teamgroesse_modell    = round(ergebnis.teamgroesse_modell or ergebnis.teamgroesse, 1),
        team_assessment       = ergebnis.team_assessment,
        rollen                = ergebnis.rollen,
        komposition_typ       = ergebnis.komposition_typ,
    )


# ---------------------------------------------------------------------------
# Sensitivity-Endpoint
# ---------------------------------------------------------------------------

@app.post("/api/estimate/sensitivity", response_model=SensitivitaetResponse, tags=["Schätzung"])
async def estimate_sensitivity(req: EstimateRequest):
    """
    Berechnet 4 Preisvariationen für die Sensitivitätsanalyse.
    Ruft intern estimate_pipeline mit leicht veränderten Parametern auf.
    """
    try:
        from estimateiq.models.estimate_pipeline import estimate as pipeline_estimate
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Pipeline nicht verfügbar: {exc}")

    land = req.region[:2].upper() if req.region else "DE"

    def _call(**kwargs):
        return pipeline_estimate(
            beschreibung    = kwargs.get("beschreibung", req.beschreibung),
            land            = kwargs.get("land", land),
            region          = kwargs.get("region", req.region),
            projekt_groesse = req.projekt_groesse,
            teamgroesse_override = kwargs.get("teamgroesse_override", req.verfuegbare_teamgroesse),
        )

    try:
        basis = _call()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=f"Pipeline-Modell nicht trainiert: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Basis-Schätzung fehlgeschlagen: {exc}")

    basis_kosten = basis.kosten_expected
    basis_team   = round(basis.teamgroesse)

    def _item(label: str, kosten_neu: float) -> SensitivitaetItem:
        delta_eur = kosten_neu - basis_kosten
        delta_pct = round(delta_eur / max(1.0, basis_kosten) * 100)
        richtung  = "teurer" if delta_eur > 500 else "günstiger" if delta_eur < -500 else "gleich"
        return SensitivitaetItem(
            label         = label,
            kosten_neu    = round(kosten_neu),
            delta_eur     = round(delta_eur),
            delta_prozent = delta_pct,
            richtung      = richtung,
        )

    variationen: list[SensitivitaetItem] = []

    # Variation 1: Teamgröße +1 Person
    try:
        v = _call(teamgroesse_override=basis_team + 1)
        variationen.append(_item("Teamgröße +1 Person", v.kosten_expected))
    except Exception:
        pass

    # Variation 2: Standort Schweiz (höhere Stundensätze)
    try:
        v = _call(land="CH", region="CH")
        variationen.append(_item("Standort Schweiz", v.kosten_expected))
    except Exception:
        pass

    # Variation 3: Technologie SAP (overhead_faktor 1.8 × statt ~1.3)
    try:
        v = _call(beschreibung=f"SAP {req.beschreibung}")
        variationen.append(_item("Technologie SAP", v.kosten_expected))
    except Exception:
        pass

    # Variation 4: Projekt 2 Jahre früher (IT-Gehälter ~10 % niedriger)
    kosten_historisch = basis_kosten * 0.90
    variationen.append(_item("Projekt 2 Jahre früher", kosten_historisch))

    return SensitivitaetResponse(basis=round(basis_kosten), sensitivitaeten=variationen)


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


# ===========================================================================
# Bau-Modul – Kostenschätzung für Bauprojekte (TED-Datenbasis)
# ===========================================================================

import threading as _threading

_BAU_BERT_LOCK                          = _threading.Lock()
_bau_bert: dict                         = {"tokenizer": None, "model": None, "bereit": False}
_BAU_GEWERK_ZAEHLER: dict[str, int] | None = None

BBSR_INDEX_BUNDESLAND: dict[str, float] = {
    "Baden-Württemberg":      108.0,
    "Bayern":                 118.5,
    "Berlin":                 105.8,
    "Brandenburg":             94.0,
    "Bremen":                 102.0,
    "Hamburg":                110.0,
    "Hessen":                 105.0,
    "Mecklenburg-Vorpommern":  92.0,
    "Niedersachsen":           98.0,
    "Nordrhein-Westfalen":    101.2,
    "Rheinland-Pfalz":         98.5,
    "Saarland":                97.0,
    "Sachsen":                 92.1,
    "Sachsen-Anhalt":          91.0,
    "Schleswig-Holstein":      99.0,
    "Thüringen":               91.5,
}
_BAU_LAND_MEDIAN_BBSR: dict[str, float] = {"DE": 100.0, "AT": 108.0, "CH": 125.0}
BAU_MODELL_VERSION = "bau-v1-bert"

_GEWERK_KEYWORDS: list[tuple[list[str], str]] = [
    # Spezifischste zuerst → verhindert False Matches durch Nebenbegriffe
    (["straße", "tiefbau", "kanalisation", "pflaster", "asphalt", "gehweg"],   "Tief-/Straßenbau"),
    (["neubau", "rohbau", "beton", "maurer", "fundament", "stahlbeton"],      "Hochbau/Neubau"),
    (["ausbau", "umbau", "sanierung", "renovation", "trockenbau"],            "Ausbau/Umbau"),
    (["holz", "dach", "zimmer", "carport", "pergola", "dachstuhl"],           "Zimmerer"),
    (["fliesen", "belag", "estrich", "parkett"],                              "Fliesen/Boden"),
    (["maler", "anstrich", "tapez", "farbe", "putz"],                         "Maler"),
    (["elektr", "strom", "kabel", "schalt", "leuch"],                         "Elektro"),
    (["sanitär", "heizung", "wasser", "rohr", " bad", "shk", "wärme", "lüftung", "klima"], "Sanitär/HLK"),
    (["tga", "gebäudetechnik", "haustechnik", "msr", "bms"],                  "TGA"),
]

_PROJEKTTYP_KEYWORDS: list[tuple[list[str], str]] = [
    (["neubau", "rohbau", "errichtung", "erstellung"],   "Neubau"),
    (["sanierung", "generalsanierung", "kernsanierung"], "Sanierung"),
    (["ausbau", "umbau", "erweiterung", "anbau"],        "Ausbau"),
    (["renovierung", "instandsetzung", "erneuerung"],    "Renovierung"),
]


def _lade_bau_bert() -> None:
    global _bau_bert
    with _BAU_BERT_LOCK:
        if _bau_bert["bereit"]:
            return
        try:
            from transformers import AutoTokenizer, AutoModel
            logger.info("[Bau] Lade DistilBERT für Inference...")
            _bau_bert["tokenizer"] = AutoTokenizer.from_pretrained("distilbert-base-german-cased")
            model = AutoModel.from_pretrained("distilbert-base-german-cased")
            model.eval()
            _bau_bert["model"] = model
            logger.info("[Bau] DistilBERT vorgeladen.")
        except Exception as exc:
            logger.warning("[Bau] DistilBERT nicht verfügbar: %s – Endpoint läuft ohne Embeddings.", exc)
        finally:
            _bau_bert["bereit"] = True


def _erkenne_gewerk_bau(beschreibung: str, gewerk_param: str) -> str:
    if gewerk_param != "auto":
        return gewerk_param
    text = beschreibung.lower()
    for keywords, name in _GEWERK_KEYWORDS:
        if any(kw in text for kw in keywords):
            return name
    return "Allgemein"


def _erkenne_projekttyp_bau(beschreibung: str, projekttyp_param: str) -> str:
    if projekttyp_param != "auto":
        return projekttyp_param
    text = beschreibung.lower()
    for keywords, name in _PROJEKTTYP_KEYWORDS:
        if any(kw in text for kw in keywords):
            return name
    return "Allgemein"


def _bbsr_index_bau(bundesland: str | None, land: str) -> float:
    if bundesland:
        bl = bundesland.lower()
        # Exakter Match zuerst (verhindert "Sachsen" → "Niedersachsen")
        for key, val in BBSR_INDEX_BUNDESLAND.items():
            if bl == key.lower():
                return val
        # Teilstring-Fallback (z.B. "Freistaat Sachsen" → "Sachsen")
        for key, val in BBSR_INDEX_BUNDESLAND.items():
            if key.lower() in bl:
                return val
    return _BAU_LAND_MEDIAN_BBSR.get(land.upper(), 100.0)


def _confidence_bau(
    gewerk: str, projekttyp: str, geo_ok: bool, kosten: float, beschreibung: str
) -> tuple[str, str]:
    if len(beschreibung) < 50:
        return "niedrig", "Beschreibung zu kurz – mehr Details verbessern die Genauigkeit."
    if kosten > 10_000_000:
        return "niedrig", f"Kostenschätzung ({kosten / 1e6:.1f} Mio €) liegt über dem verlässlichen Modellbereich (< 10 Mio €)."
    if gewerk == "Allgemein":
        return "niedrig", "Gewerk konnte nicht aus der Beschreibung erkannt werden."
    if 50_000 <= kosten <= 2_000_000 and projekttyp != "Allgemein" and geo_ok:
        return "hoch", "Gewerk, Projekttyp und Standort eindeutig erkannt – Schätzung im Normalbereich."
    if 2_000_000 < kosten <= 10_000_000:
        return "mittel", "Kostenschätzung über 2 Mio € – Modell neigt bei Großprojekten zur Unterschätzung."
    return "mittel", "Gewerk erkannt, Projekttyp oder Standort nicht vollständig spezifiziert."


def _schwaechen_bau(gewerk: str, kosten: float, confidence: str) -> list[str]:
    schwaechen: list[str] = []
    if kosten > 2_000_000:
        schwaechen.append(
            "Großprojekte über 2 Mio € werden vom Modell tendenziell zur Mitte gezogen. "
            "Reale Kosten können deutlich höher liegen."
        )
    if gewerk in ("Elektro", "Sanitär/HLK", "TGA"):
        schwaechen.append(
            "Laufzeiten für TGA-Gewerke (Elektro, Heizung, Sanitär) werden aktuell überschätzt. "
            "Typisch sind 60–180 Tage, nicht 250–368 Tage."
        )
    if confidence == "niedrig":
        schwaechen.append(
            "Projektbeschreibung enthält wenig spezifische Details. "
            "Mehr Kontext verbessert die Genauigkeit."
        )
    return schwaechen


def _zaehle_referenzprojekte_bau(gewerk: str) -> int:
    global _BAU_GEWERK_ZAEHLER
    if _BAU_GEWERK_ZAEHLER is None:
        bau_parquet = Path("data/processed/notices_bau.parquet")
        if bau_parquet.exists():
            try:
                df = pd.read_parquet(bau_parquet, columns=["gewerk", "budget_eur"])
                zaehler: dict[str, int] = {}
                for g, gruppe in df.groupby("gewerk"):
                    zaehler[str(g)] = int(gruppe["budget_eur"].notna().sum())
                zaehler["_gesamt"] = int(df["budget_eur"].notna().sum())
                _BAU_GEWERK_ZAEHLER = zaehler
            except Exception:
                _BAU_GEWERK_ZAEHLER = {}
        else:
            _BAU_GEWERK_ZAEHLER = {}
    if gewerk == "Allgemein":
        return _BAU_GEWERK_ZAEHLER.get("_gesamt", 0)
    return int(_BAU_GEWERK_ZAEHLER.get(gewerk, _BAU_GEWERK_ZAEHLER.get("_gesamt", 0)))


# ── Bau Schemas ───────────────────────────────────────────────────────────────

class BauEstimateRequest(BaseModel):
    beschreibung: Annotated[str, Field(min_length=30, max_length=10_000)]
    stadt:        str
    land:         str = "DE"
    gewerk:       str = "auto"
    projekttyp:   str = "auto"


class BauEstimateResponse(BaseModel):
    kosten_min:           float
    kosten_expected:      float
    kosten_max:           float
    dauer_min_tage:       int
    dauer_expected_tage:  int
    dauer_max_tage:       int
    gewerk_erkannt:       str
    projekttyp_erkannt:   str
    stadt_normalisiert:   str
    bbsr_index:           float
    confidence:           str
    confidence_grund:     str
    modell_version:       str
    n_referenzprojekte:   int
    bekannte_schwaechen:  list[str]


# ── Bau Endpoints ─────────────────────────────────────────────────────────────

@app.post("/api/bau/estimate", response_model=BauEstimateResponse, tags=["Bau"])
async def bau_estimate(req: BauEstimateRequest):
    """Schätzt Kosten und Laufzeit für Bauprojekte (Datenbasis: TED EU-Ausschreibungen)."""
    import re

    land = req.land.upper()
    if land not in ("DE", "AT", "CH"):
        raise HTTPException(status_code=400, detail="Land muss DE, AT oder CH sein.")

    gewerk     = _erkenne_gewerk_bau(req.beschreibung, req.gewerk)
    projekttyp = _erkenne_projekttyp_bau(req.beschreibung, req.projekttyp)

    # Geocoding (blockierend → Executor)
    loop = asyncio.get_event_loop()
    try:
        from estimateiq.data.geo_features import geocode as _geocode_fn
        geo    = await loop.run_in_executor(None, lambda: _geocode_fn(req.stadt, land=land))
        geo_ok = geo.get("lat") is not None
    except Exception:
        geo    = {"lat": None, "lon": None, "bundesland": None,
                  "ist_metropole": False, "ist_grossstadt": False}
        geo_ok = False

    bbsr       = _bbsr_index_bau(geo.get("bundesland"), land)
    bundesland = geo.get("bundesland") or land

    # Regex-Features aus Beschreibungstext
    def _regex_zahl(text: str, pattern: str, mult: float = 1.0,
                    lo: float = 0, hi: float = 1e9) -> float:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                v = float(m.group(1).replace(".", "").replace(",", ".")) * mult
                if lo <= v <= hi:
                    return v
            except ValueError:
                pass
        return 0.0

    flaeche   = _regex_zahl(req.beschreibung,
                    r"(\d[\d.]*)\s*(?:m\s*[²2]|qm|Quadratmeter)", lo=10, hi=500_000)
    einheiten = _regex_zahl(req.beschreibung,
                    r"(\d+)\s*(?:Wohneinheit|Wohnung|WE\b)", lo=1, hi=10_000)
    laenge    = _regex_zahl(req.beschreibung,
                    r"(\d+(?:[,.]\d+)?)\s*km", mult=1000, lo=50, hi=200_000)

    import math as _math
    _bbsr_val = bbsr
    _log_fl   = _math.log1p(flaeche)
    df_input = pd.DataFrame([{
        "beschreibung":               req.beschreibung,
        "gewerk":                     gewerk,
        "projekttyp":                 projekttyp,
        "land":                       land,
        "bundesland":                 bundesland,
        "latitude":                   float(geo.get("lat") or 51.16),
        "longitude":                  float(geo.get("lon") or 10.45),
        "bbsr_index":                 _bbsr_val,
        "ist_metropole":              bool(geo.get("ist_metropole", False)),
        "ist_grossstadt":             bool(geo.get("ist_grossstadt", False)),
        "jahr":                       2024,
        "flaeche_m2":                 flaeche,
        "einheiten":                  einheiten,
        "laenge_m":                   laenge,
        "hat_flaeche":                float(flaeche > 0),
        "beschreibung_laenge":        float(len(req.beschreibung)),
        "log_flaeche":                _log_fl,
        "flaeche_je_m2_budget_proxy": _log_fl * _bbsr_val / 100.0,
    }])

    # BERT Embeddings (lazy load, dann gecacht)
    if not _bau_bert["bereit"]:
        await loop.run_in_executor(None, _lade_bau_bert)

    embeddings = None
    if _bau_bert["tokenizer"] is not None:
        try:
            import torch
            with torch.inference_mode():
                encoded = _bau_bert["tokenizer"](
                    [req.beschreibung],
                    padding=True, truncation=True,
                    max_length=128, return_tensors="pt",
                )
                out = _bau_bert["model"](**encoded)
            embeddings = out.last_hidden_state[:, 0, :].numpy()
        except Exception as exc:
            logger.warning("[Bau] BERT-Inference fehlgeschlagen: %s", exc)

    # XGBoost-Vorhersage
    try:
        from estimateiq.models.cost_model_bau     import predict as _predict_kosten
        from estimateiq.models.duration_model_bau import predict as _predict_dauer
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Bau-Modelle nicht trainiert. Bitte zuerst train_bau.py ausführen. ({exc})"
        ) from exc

    try:
        kosten_raw = float(_predict_kosten(df_input, embeddings=embeddings)[0])
        dauer_raw  = float(_predict_dauer(df_input,  embeddings=embeddings)[0])
    except Exception as exc:
        logger.exception("[Bau] Vorhersagefehler: %s", exc)
        raise HTTPException(status_code=500, detail=f"Vorhersagefehler: {exc}") from exc

    # Unsicherheitsbänder (MdAPE-basiert: Kosten 61%, Dauer 30%)
    kosten_min = round(kosten_raw * 0.40, 0)
    kosten_max = round(kosten_raw * 2.50, 0)
    dauer_min  = max(1, int(dauer_raw * 0.60))
    dauer_max  = int(dauer_raw * 1.60)

    confidence, confidence_grund = _confidence_bau(
        gewerk, projekttyp, geo_ok, kosten_raw, req.beschreibung
    )

    return BauEstimateResponse(
        kosten_min          = kosten_min,
        kosten_expected     = round(kosten_raw, 0),
        kosten_max          = kosten_max,
        dauer_min_tage      = dauer_min,
        dauer_expected_tage = int(dauer_raw),
        dauer_max_tage      = dauer_max,
        gewerk_erkannt      = gewerk,
        projekttyp_erkannt  = projekttyp,
        stadt_normalisiert  = req.stadt.strip().title(),
        bbsr_index          = bbsr,
        confidence          = confidence,
        confidence_grund    = confidence_grund,
        modell_version      = BAU_MODELL_VERSION,
        n_referenzprojekte  = _zaehle_referenzprojekte_bau(gewerk),
        bekannte_schwaechen = _schwaechen_bau(gewerk, kosten_raw, confidence),
    )


@app.get("/api/bau/health", tags=["Bau"])
async def bau_health():
    """Status und Metadaten des Bau-Schätzmodells."""
    from estimateiq.models.cost_model_bau     import MODELL_PKL as KOSTEN_PKL
    from estimateiq.models.duration_model_bau import MODELL_PKL as DAUER_PKL

    kosten_ok = KOSTEN_PKL.exists()
    dauer_ok  = DAUER_PKL.exists()
    trainiert_am = None
    if kosten_ok:
        import datetime as _dt
        trainiert_am = _dt.datetime.fromtimestamp(
            KOSTEN_PKL.stat().st_mtime
        ).strftime("%Y-%m-%d")

    return {
        "status":           "ok" if (kosten_ok and dauer_ok) else "modell_fehlt",
        "modell_version":   BAU_MODELL_VERSION,
        "trainiert_am":     trainiert_am,
        "n_trainingsdaten": 19_818,
        "kosten_mdape":     0.648,
        "dauer_mdape":      0.342,
        "bekannte_schwaechen": [
            "Großprojekte > 2 Mio € werden unterschätzt (Regression zur Mitte)",
            "Kosten: R²=0.20 – 80 % der Varianz durch unbeobachtete Faktoren erklärt",
        ],
    }
