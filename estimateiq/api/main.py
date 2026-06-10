"""
EstimateIQ FastAPI – REST-Schnittstelle für Kostenschätzung und Risikoanalyse.
Hauptendpoint: POST /api/estimate
"""

import logging
from contextlib import asynccontextmanager
from typing import Annotated

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from estimateiq.models.bert_extractor import extrahiere_features
from estimateiq.models.risk_model import predict as predict_risk

# Kostenschätzung: v2 (BERT-Features) wenn trainiert, sonst v1
from estimateiq.models.cost_model_v2 import MODELL_PKL as _V2_PKL
if _V2_PKL.exists():
    from estimateiq.models.cost_model_v2 import predict as predict_cost
    _COST_MODEL_PKL = _V2_PKL
    _COST_MODEL_VERSION = "2.0"
else:
    from estimateiq.models.cost_model import predict as predict_cost
    from estimateiq.models.cost_model import MODELL_PKL as _COST_MODEL_PKL
    _COST_MODEL_VERSION = "1.0"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / Response Schemas
# ---------------------------------------------------------------------------

class EstimateRequest(BaseModel):
    """Eingabe für eine Kostenschätzung."""
    title: Annotated[str, Field(min_length=5, max_length=1000, description="Titel der Ausschreibung")]
    description: Annotated[str, Field(min_length=10, max_length=10000, description="Ausschreibungstext")]
    cpv_code: Annotated[int | None, Field(None, ge=72000000, le=72900000, description="CPV-Code (IT: 72000000–72900000)")]
    country: Annotated[str | None, Field(None, max_length=2, description="Ländercode (DE, AT, CH, ...)")]
    duration_days: Annotated[int | None, Field(None, ge=1, le=3650, description="Geplante Laufzeit in Tagen")]
    contract_type: Annotated[str | None, Field(None, description="Auftragsart (z. B. 'Dienstleistung')")]
    procedure_type: Annotated[str | None, Field(None, description="Verfahrensart")]
    authority_type: Annotated[str | None, Field(None, description="Auftraggeber-Typ")]

    @field_validator("country")
    @classmethod
    def uppercase_country(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class RiskDetail(BaseModel):
    """Risikoklassifikation mit Wahrscheinlichkeiten."""
    risk_class: int
    risk_label: str
    probability_low: float
    probability_medium: float
    probability_high: float


class EstimateResponse(BaseModel):
    """Antwort mit Kostenschätzung und Risikoanalyse."""
    model_config = {"protected_namespaces": ()}

    estimated_cost_eur: float = Field(description="Geschätzter Auftragswert in EUR")
    cost_range_low_eur: float = Field(description="Untere Schranke (–20 %)")
    cost_range_high_eur: float = Field(description="Obere Schranke (+35 %)")
    risk: RiskDetail
    cpv_category: str
    projekttyp_bert: str = Field(description="Aus Beschreibung erkannter Projekttyp")
    technologien: list[str] = Field(default_factory=list, description="Erkannte Technologien")
    komplexitaet: int = Field(description="Komplexitäts-Score 1–5")
    schnittstellen_anzahl: int = Field(description="Geschätzte Anzahl Schnittstellen")
    model_version: str = Field(default="1.0.0", description="Aktive Modellversion (1.0 = numerisch, 2.0 = BERT)")


class HealthResponse(BaseModel):
    status: str
    models_loaded: bool


# ---------------------------------------------------------------------------
# App-Initialisierung
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Modelle beim Start vorladen, um beim ersten Request keine Verzögerung zu haben."""
    logger.info("Lade Modelle beim Start (Cost Model v%s)...", _COST_MODEL_VERSION)
    try:
        predict_cost(__import__("pandas").DataFrame([{
            "titel": "test", "beschreibung": "test", "budget_eur": None,
            "dauer_tage": 30, "land": "DE", "cpv_code": "72000000", "projekttyp": "sonstiges_it",
        }]))
        logger.info("Modelle erfolgreich geladen.")
    except FileNotFoundError as exc:
        logger.warning("Modelle nicht vorhanden, werden bei Bedarf geladen: %s", exc)
    except Exception as exc:
        logger.warning("Modell-Vorlade fehlgeschlagen (wird beim ersten Request geladen): %s", exc)
    yield


app = FastAPI(
    title="EstimateIQ API",
    description="ML-basierte Kostenschätzung für IT-Ausschreibungen im DACH-Raum",
    version="1.0.0",
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

def _cpv_to_category(cpv_code: int | None) -> str:
    """Vereinfachte Zuordnung CPV → Kategoriename (ohne Import des gesamten Preprocessors)."""
    if cpv_code is None:
        return "unbekannt"
    ranges = {
        "software": (72200000, 72299999),
        "beratung": (72300000, 72399999),
        "infrastruktur": (72400000, 72499999),
        "wartung": (72500000, 72699999),
        "sicherheit": (72700000, 72799999),
    }
    for name, (lo, hi) in ranges.items():
        if lo <= cpv_code <= hi:
            return name
    return "sonstiges_it"


def _request_to_dataframe(req: EstimateRequest) -> pd.DataFrame:
    """Wandelt eine EstimateRequest in einen einzeiligen DataFrame um (passend zu preprocess.py)."""
    return pd.DataFrame([{
        "titel": req.title,
        "beschreibung": req.description,
        "budget_eur": None,
        "dauer_tage": req.duration_days,
        "land": req.country or "DE",
        "cpv_code": f"{req.cpv_code or 72000000:08d}",
        "projekttyp": _cpv_to_category(req.cpv_code),
    }])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Liefert den Betriebsstatus der API."""
    try:
        from pathlib import Path
        models_ok = _COST_MODEL_PKL.exists()
    except Exception:
        models_ok = False
    return HealthResponse(status="ok", models_loaded=models_ok)


@app.post("/api/estimate", response_model=EstimateResponse, tags=["Schätzung"])
async def estimate(req: EstimateRequest):
    """
    Schätzt Projektkosten und Risiko für eine IT-Ausschreibung.

    - **title**: Ausschreibungstitel
    - **description**: Volltext der Ausschreibung
    - **cpv_code**: CPV-Code (optional, IT-Bereich 72000000–72900000)
    - **country**: Ländercode (optional, Standard: DE)
    """
    try:
        df = _request_to_dataframe(req)

        # BERT-Features aus Beschreibung extrahieren
        bert = extrahiere_features(req.description)

        # DataFrame um Scalar-BERT-Features anreichern (v1 ignoriert diese Spalten)
        df["komplexitaet"]          = bert["komplexitaet"]
        df["schnittstellen_anzahl"] = bert["schnittstellen_anzahl"]
        df["technologien"]          = [bert["technologien"]]

        # Kostenschätzung: v2 bekommt Embedding-Vektor, v1 ignoriert ihn
        cost_predictions = predict_cost(df, embeddings=bert.get("embeddings"))
        estimated_cost = float(cost_predictions[0])

        # Risikoanalyse
        risk_result = predict_risk(df)
        risk_class = int(risk_result["risk_class"][0])
        risk_label = risk_result["risk_label"][0]
        probas = risk_result["probabilities"][0]
        while len(probas) < 3:
            probas.append(0.0)

        return EstimateResponse(
            estimated_cost_eur=round(estimated_cost, 2),
            cost_range_low_eur=round(estimated_cost * 0.80, 2),
            cost_range_high_eur=round(estimated_cost * 1.35, 2),
            risk=RiskDetail(
                risk_class=risk_class,
                risk_label=risk_label,
                probability_low=round(probas[0], 4),
                probability_medium=round(probas[1], 4),
                probability_high=round(probas[2], 4),
            ),
            cpv_category=_cpv_to_category(req.cpv_code),
            projekttyp_bert=bert["projekttyp_bert"],
            technologien=bert["technologien"],
            komplexitaet=bert["komplexitaet"],
            schnittstellen_anzahl=bert["schnittstellen_anzahl"],
            model_version=_COST_MODEL_VERSION,
        )

    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Modell nicht trainiert. Bitte zuerst Training durchführen. ({exc})",
        ) from exc
    except Exception as exc:
        logger.exception("Fehler bei Schätzung: %s", exc)
        raise HTTPException(status_code=500, detail=f"Interner Fehler: {exc}") from exc


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("estimateiq.api.main:app", host="0.0.0.0", port=8000, reload=True)
