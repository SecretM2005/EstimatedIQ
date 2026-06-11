"""
EstimateIQ FastAPI – zweistufige Kostenschätzungs-Pipeline.

Endpoint: POST /api/estimate
  Body:     { beschreibung: str, region: str }
  Response: { dauer_tage, personalkosten, kosten_min/expected/max,
              overhead_faktor, confidence_score, top_risks, similar_projects }
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_PATH = Path("data/processed/notices.parquet")

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class EstimateRequest(BaseModel):
    beschreibung: Annotated[str, Field(min_length=10, max_length=10_000,
                                       description="Projektbeschreibung")]
    region: str = Field(default="DE", description="ISO 3166-2 Region (z.B. DE-BY, AT, CH)")


class SimilarProject(BaseModel):
    titel:      str
    budget_eur: float
    dauer_tage: float | None = None


class EstimateResponse(BaseModel):
    dauer_tage:        float
    personalkosten:    float
    kosten_min:        float
    kosten_expected:   float
    kosten_max:        float
    overhead_faktor:   float
    confidence_score:  float
    top_risks:         list[str]
    similar_projects:  list[SimilarProject]


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
        from estimateiq.models.estimate_pipeline import _lade_duration_modell, _lade_overhead_modell
        _lade_duration_modell()
        _lade_overhead_modell()
        logger.info("Pipeline-Modelle geladen.")
    except FileNotFoundError as exc:
        logger.warning("Modelle noch nicht trainiert: %s", exc)
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
    from estimateiq.models.overhead_model import MODELL_PKL as OH_PKL
    pipeline_ok = DUR_PKL.exists() and OH_PKL.exists()
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
            beschreibung = req.beschreibung,
            land         = land,
            region       = req.region,
            datenquelle  = "ted",
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
    )
