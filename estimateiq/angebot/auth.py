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
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from estimateiq.angebot import config
from estimateiq.angebot.database import get_db
from estimateiq.angebot.models import TenantUser

logger = logging.getLogger(__name__)

_jwks_client: "jwt.PyJWKClient | None" = None


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


@dataclass
class CurrentUser:
    """Aufgelöster Request-Kontext: Wer stellt die Anfrage, in welchem Tenant, mit welcher Rolle."""
    user_id: str
    tenant_id: str
    rolle: str          # 'admin' | 'mitglied'
    email: str | None = None

    @property
    def ist_admin(self) -> bool:
        return self.rolle == "admin"


# Fester Kontext für die lokale Entwicklung ohne Login (immer Admin).
_DEV_USER_ID = "dev-user"


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> CurrentUser:
    if config.AUTH_DISABLED:
        return CurrentUser(
            user_id=_DEV_USER_ID,
            tenant_id=config.DEV_TENANT_ID,
            rolle="admin",
            email="dev@local",
        )

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

    # Zuordnung wird pro Request frisch gelesen (Rollen können sich ändern);
    # ein PK-Lookup ist günstig.
    zuordnung = db.get(TenantUser, user_id)
    if zuordnung is None:
        raise HTTPException(
            403, "Benutzer ist keinem Tenant zugeordnet. Bitte Administrator kontaktieren."
        )

    return CurrentUser(
        user_id=user_id,
        tenant_id=zuordnung.tenant_id,
        rolle=zuordnung.rolle or "mitglied",
        email=zuordnung.email or payload.get("email"),
    )


def get_tenant_id(current: CurrentUser = Depends(get_current_user)) -> str:
    """Rückwärtskompatibel: liefert nur die tenant_id des aktuellen Users."""
    return current.tenant_id
