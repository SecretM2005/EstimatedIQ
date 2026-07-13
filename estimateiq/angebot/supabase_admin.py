"""
Anlage/Löschung von Supabase-Auth-Usern über die GoTrue-Admin-REST-API.

Bewusst per httpx direkt statt über supabase-py: Die Bibliothek (2.10) lehnt
die neuen `sb_secret_...`-Keys mit "Invalid API key" ab. Der rohe HTTP-Aufruf
funktioniert dagegen mit Legacy- und neuen Secret-Keys.

Benötigt SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (Secret-Key).
"""

from __future__ import annotations

import httpx

from estimateiq.angebot import config


class AdminNichtKonfiguriert(RuntimeError):
    """SUPABASE_URL oder SUPABASE_SERVICE_ROLE_KEY fehlt."""


def _headers() -> dict[str, str]:
    key = config.SUPABASE_SERVICE_ROLE_KEY
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _pruefe_konfiguration() -> None:
    if not (config.SUPABASE_URL and config.SUPABASE_SERVICE_ROLE_KEY):
        raise AdminNichtKonfiguriert(
            "Benutzerverwaltung erfordert SUPABASE_URL und SUPABASE_SERVICE_ROLE_KEY."
        )


def create_auth_user(email: str, passwort: str) -> str:
    """Legt einen bestätigten Auth-User an und gibt dessen user_id zurück."""
    _pruefe_konfiguration()
    resp = httpx.post(
        f"{config.SUPABASE_URL}/auth/v1/admin/users",
        headers=_headers(),
        json={"email": email, "password": passwort, "email_confirm": True},
        timeout=15.0,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Supabase lehnte die User-Anlage ab ({resp.status_code}): {resp.text}")
    return resp.json()["id"]


def delete_auth_user(user_id: str) -> None:
    """Löscht einen Auth-User in Supabase (Best effort)."""
    _pruefe_konfiguration()
    httpx.delete(
        f"{config.SUPABASE_URL}/auth/v1/admin/users/{user_id}",
        headers=_headers(),
        timeout=15.0,
    )
