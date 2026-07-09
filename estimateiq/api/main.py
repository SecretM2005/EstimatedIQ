"""
EstimateIQ API – Angebots- und Projektkalkulation für IT-Dienstleister.

Schlanke FastAPI-App für den MVP:
  - Angebot-Router unter /api/v2/*  (Rollen, Projekte, Positionen,
    Ähnlichkeitssuche, Import, Angebote/PDF)
  - GET /health  – Health-Check für Deployment (Railway/Render)

Auth & Multi-Tenancy siehe estimateiq/angebot/auth.py.
"""

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from estimateiq.angebot import config as angebot_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Datenbank initialisieren (SQLite-Schema anlegen bzw. Supabase-Schema prüfen)
    try:
        from estimateiq.angebot.database import init_db
        init_db()
        logger.info("Datenbank initialisiert.")
    except Exception as exc:
        logger.warning("DB-Init fehlgeschlagen: %s", exc)

    # Embedding-Modell im Hintergrund vorladen, damit der erste echte Request
    # (Import / Ähnlichkeitssuche) nicht auf den Kaltstart wartet. Der Server
    # ist sofort ansprechbar; das Modell lädt parallel.
    def _warmup_embeddings():
        try:
            from estimateiq.angebot.embeddings import embed
            embed("Warmup")
            logger.info("Embedding-Modell vorgeladen (warmup).")
        except Exception as exc:
            logger.warning("Embedding-Warmup fehlgeschlagen: %s", exc)

    threading.Thread(target=_warmup_embeddings, daemon=True).start()
    yield


app = FastAPI(
    title="EstimateIQ API",
    description="Angebots- und Projektkalkulation für IT-Dienstleister im DACH-Raum",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=angebot_config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

from estimateiq.angebot.router import router as angebot_router  # noqa: E402
app.include_router(angebot_router)


@app.get("/health", tags=["System"])
async def health_check():
    """Health-Check für Deployment-Plattformen."""
    return {
        "status": "ok",
        "datenbank": "postgres" if angebot_config.IS_POSTGRES else "sqlite",
        "auth": "disabled" if angebot_config.AUTH_DISABLED else "supabase",
    }
