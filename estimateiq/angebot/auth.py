"""
Tenant-Auflösung aus dem Supabase-JWT.

Jeder Request an /api/v2 muss einen Tenant ergeben – die Dependency
get_tenant_id() ist die EINZIGE Quelle dafür und wird von jedem
Endpunkt verwendet. Ohne gültigen Tenant gibt es keine Daten.

Modi (siehe config.py):
  1. AUTH_DISABLED=true      → fester Dev-Tenant (nur lokale Entwicklung!)
  2. SUPABASE_JWT_SECRET     → HS256-Verifikation (Legacy Shared Secret)
  3. SUPABASE_URL            → JWKS-Verifikation (neue Supabase-Projekte)
"""

from __future__ import annotations

import logging

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from estimateiq.angebot import config
from estimateiq.angebot.database import get_db
from estimateiq.angebot.models import TenantUser

logger = logging.getLogger(__name__)

_jwks_client: "jwt.PyJWKClient | None" = None

# user_id → tenant_id (die Zuordnung ändert sich praktisch nie)
_tenant_cache: dict[str, str] = {}


def _decode_token(token: str) -> dict:
    if config.SUPABASE_JWT_SECRET:
        return jwt.decode(
            token,
            config.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
    if config.SUPABASE_URL:
        global _jwks_client
        if _jwks_client is None:
            _jwks_client = jwt.PyJWKClient(
                f"{config.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
            )
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
        )
    raise HTTPException(
        503,
        "Auth nicht konfiguriert: SUPABASE_JWT_SECRET oder SUPABASE_URL setzen "
        "(oder lokal AUTH_DISABLED=true).",
    )


def get_tenant_id(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> str:
    if config.AUTH_DISABLED:
        return config.DEV_TENANT_ID

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Nicht angemeldet (Authorization-Header fehlt).")

    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = _decode_token(token)
    except HTTPException:
        raise
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"Ungültiges oder abgelaufenes Token: {exc}")
    except Exception as exc:  # z.B. JWKS nicht erreichbar
        logger.exception("Token-Verifikation fehlgeschlagen: %s", exc)
        raise HTTPException(503, "Token-Verifikation derzeit nicht möglich.")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(401, "Token enthält keine Benutzer-ID (sub).")

    if user_id in _tenant_cache:
        return _tenant_cache[user_id]

    zuordnung = db.get(TenantUser, user_id)
    if zuordnung is None:
        raise HTTPException(
            403, "Benutzer ist keinem Tenant zugeordnet. Bitte Administrator kontaktieren."
        )

    _tenant_cache[user_id] = zuordnung.tenant_id
    return zuordnung.tenant_id
