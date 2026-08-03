"""
Statischer Permission-Katalog + Systemrollen-Definitionen.

Einzige Quelle der Wahrheit für erlaubte Permission-Keys – wird von
database.py (SQLite-Migration + Dev-Bootstrap), router.py (Validierung neuer
Custom-Teamrollen) und migrations/003_teamrollen_permissions.sql (Postgres,
manuell synchron zu halten) verwendet.

Systemrollen sind fix (is_system=true): Name und Löschen sind gesperrt.
Owner ist zusätzlich in seinem Permission-Set gesperrt (immer alle Rechte).
"""

from __future__ import annotations

# (key, bereich, beschreibung) – bereich gruppiert die Darstellung im Rollen-Editor.
KATALOG: list[tuple[str, str, str]] = [
    ("dashboard.view",            "dashboard", "Dashboard aufrufen"),
    ("projekte.erstellen",        "projekte",  "Neues Projekt/Angebot anlegen"),
    ("projekte.bearbeiten",       "projekte",  "Projekt bearbeiten (kombiniert mit Ownership)"),
    ("projekte.loeschen",         "projekte",  "Projekt löschen (kombiniert mit Ownership)"),
    ("projekte.status_aendern",   "projekte",  "Angebotsstatus ändern, Angebot/PDF erzeugen"),
    ("projekte.alle_ansehen",     "projekte",  "Alle Projekte im Tenant sehen (nicht nur eigene)"),
    ("projekte.marge_einsehen",   "projekte",  "Interne Kosten/Marge/Stundensätze einsehen"),
    ("positionen.bearbeiten",     "positionen","Leistungspositionen anlegen/ändern/löschen"),
    ("rollen.verwalten",          "rollen",    "Stundensatz-Rollen verwalten"),
    ("import.durchfuehren",       "import",    "CSV/Excel-Import durchführen"),
    ("settings.manage_users",     "settings",  "Team & Rollen verwalten"),
    ("settings.manage_layout",    "settings",  "Dashboard-Layout verwalten (Phase 2, noch ungenutzt)"),
    ("settings.manage_kpis",      "settings",  "Eigene Kennzahlen verwalten (Phase 3, noch ungenutzt)"),
]

GUELTIGE_KEYS: frozenset[str] = frozenset(k for k, _, _ in KATALOG)

_ALLE = GUELTIGE_KEYS

# Systemrollen: Name → Permission-Keys. Owner bekommt immer ALLE (auch künftig
# neue) Permissions – das wird in Code erzwungen, nicht nur hier gelistet.
SYSTEMROLLEN: dict[str, frozenset[str]] = {
    "Owner": _ALLE,
    "Admin": _ALLE,
    "Mitarbeiter": frozenset({
        "dashboard.view",
        "projekte.erstellen",
        "projekte.bearbeiten",
        "projekte.loeschen",
        "projekte.status_aendern",
        "positionen.bearbeiten",
        "import.durchfuehren",
    }),
    "Nur-Lesen": frozenset({
        "dashboard.view",
        "projekte.alle_ansehen",
        "projekte.marge_einsehen",
    }),
}

# Reihenfolge für die Anlage neuer Tenants/Migration (Owner zuerst, u.a. für
# Lesbarkeit in der UI-Liste).
SYSTEMROLLEN_REIHENFOLGE: list[str] = ["Owner", "Admin", "Mitarbeiter", "Nur-Lesen"]
