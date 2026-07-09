"""
Zentrale Konfiguration für das Angebot-Modul.

Liest Umgebungsvariablen aus .env (python-dotenv):
  - Ohne DATABASE_URL läuft lokal SQLite (data/estimateiq_angebot.db).
  - Mit DATABASE_URL (postgresql://…) verbindet sich das Backend mit
    Supabase Postgres inkl. pgvector.

Auth-Modi (in dieser Reihenfolge aufgelöst):
  1. AUTH_DISABLED=true      → fester Dev-Tenant, KEIN Login (nur lokal!)
  2. SUPABASE_JWT_SECRET     → HS256-Verifikation (Legacy Shared Secret)
  3. SUPABASE_URL            → JWKS-Verifikation (neue Supabase-Projekte)
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_PROJEKT_ROOT = Path(__file__).resolve().parents[2]

# ── Datenbank ─────────────────────────────────────────────────────────────────
DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()
IS_POSTGRES: bool = DATABASE_URL.startswith(("postgres://", "postgresql://", "postgresql+"))

SQLITE_PATH: Path = _PROJEKT_ROOT / "data" / "estimateiq_angebot.db"

# ── Supabase Auth ─────────────────────────────────────────────────────────────
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_JWT_SECRET: str = os.getenv("SUPABASE_JWT_SECRET", "").strip()
# Nur für das Seed-Skript: erlaubt die automatische Anlage eines Login-Users
# über die Supabase-Admin-API. NIE im Frontend verwenden.
SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

AUTH_DISABLED: bool = os.getenv("AUTH_DISABLED", "").strip().lower() in ("1", "true", "yes")

# Fester Tenant für die lokale Entwicklung ohne Login
DEV_TENANT_ID: str = os.getenv("DEV_TENANT_ID", "00000000-0000-0000-0000-000000000001")
DEV_TENANT_NAME: str = "Dev-Tenant (lokal)"

# ── CORS ──────────────────────────────────────────────────────────────────────
# Kommagetrennte Liste erlaubter Origins; "*" als Fallback für lokale Entwicklung.
CORS_ORIGINS: list[str] = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()
]
