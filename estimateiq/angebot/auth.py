"""
Tenant-Auflösung + Rechteprüfung aus dem Supabase-JWT.

Jeder Request an /api/v2 muss einen Tenant ergeben – get_current_user() ist
die EINZIGE Quelle dafür und wird von jedem Endpunkt verwendet. Ohne gültigen
Tenant gibt es keine Daten.

Zwei Berechtigungsebenen (siehe permissions.py für den Katalog):
  1. Permissions (require_permission): "darf dieser User diese Art von
     Aktion überhaupt durchführen" – global pro Endpunkt geprüft.
  2. Ownership (_darf_bearbeiten in router.py): "darf er dieses KONKRETE
     Objekt bearbeiten" – bleibt bestehen, orthogonal zu Permissions.
     projekte.alle_ansehen hebt die Ownership-Einschränkung sowohl beim
     Lesen als auch beim Schreiben auf (einheitliche Quelle der Wahrheit,
     statt eines separaten "alle bearbeiten"-Keys).

Modi (siehe config.py):
  1. AUTH_DISABLED=true      → fester Dev-Tenant, Rolle "Owner" (alle Rechte)
  2. SUPABASE_JWT_SECRET     → HS256-Verifikation (Legacy Shared Secret)
  3. SUPABASE_URL            → JWKS-Verifikation (neue Supabase-Projekte)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from estimateiq.angebot import config
from estimateiq.angebot.database import get_db
from estimateiq.angebot.models import Permission, TeamrollePermission, TenantUser

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
    """Aufgelöster Request-Kontext: Wer, in welchem Tenant, mit welchen Rechten."""
    user_id: str
    tenant_id: str
    teamrolle_id: int | None
    teamrolle_name: str
    permissions: frozenset[str] = field(default_factory=frozenset)
    email: str | None = None

    @property
    def ist_owner(self) -> bool:
        """Für die Sonderregel 'nur Owner darf die Owner-Rolle vergeben' – bewusst
        namensbasiert, nicht permissionbasiert, weil Admin dieselben Permissions
        wie Owner hat."""
        return self.teamrolle_name == "Owner"

    def hat_permission(self, key: str) -> bool:
        return key in self.permissions


# Fester Kontext für die lokale Entwicklung ohne Login (immer volle Rechte).
_DEV_USER_ID = "dev-user"


def _lade_permissions(db: Session, teamrolle_id: int) -> frozenset[str]:
    keys = (
        db.query(TeamrollePermission.permission_key)
        .filter(TeamrollePermission.teamrolle_id == teamrolle_id)
        .all()
    )
    return frozenset(k for (k,) in keys)


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> CurrentUser:
    if config.AUTH_DISABLED:
        alle_permissions = frozenset(p.key for p in db.query(Permission).all())
        return CurrentUser(
            user_id=_DEV_USER_ID,
            tenant_id=config.DEV_TENANT_ID,
            teamrolle_id=None,
            teamrolle_name="Owner",
            permissions=alle_permissions,
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

    teamrolle = zuordnung.teamrolle  # via relationship, ein zusätzlicher Join
    return CurrentUser(
        user_id=user_id,
        tenant_id=zuordnung.tenant_id,
        teamrolle_id=teamrolle.id,
        teamrolle_name=teamrolle.name,
        permissions=_lade_permissions(db, teamrolle.id),
        email=zuordnung.email or payload.get("email"),
    )


def get_tenant_id(current: CurrentUser = Depends(get_current_user)) -> str:
    """Rückwärtskompatibel: liefert nur die tenant_id des aktuellen Users."""
    return current.tenant_id


def require_permission(key: str):
    """
    Dependency-Factory: Endpunkt-Signatur `user: CurrentUser = Depends(require_permission("..."))`
    ersetzt `Depends(get_current_user)` 1:1 (liefert denselben CurrentUser),
    prüft aber zusätzlich die Permission und wirft 403 statt eines leeren
    200-Ergebnisses.
    """
    def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.hat_permission(key):
            raise HTTPException(403, f"Fehlende Berechtigung: {key}")
        return user
    return _check
