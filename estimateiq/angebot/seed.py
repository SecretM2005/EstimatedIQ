"""
Seed-Skript für Demo-Daten.

Legt einen Demo-Tenant mit realistischen historischen IT-Projekten an, damit
die Embedding-basierte Ähnlichkeitssuche in einer Live-Demo sofort sinnvolle
Treffer liefert. Nutzt dieselbe DB-Umschaltung wie die App (SQLite lokal bzw.
Supabase Postgres, je nach DATABASE_URL).

Aufruf:
    python -m estimateiq.angebot.seed            # anlegen (idempotent)
    python -m estimateiq.angebot.seed --reset    # Tenant-Daten vorher löschen

Tenant-Ziel:
    - AUTH_DISABLED=true  → fester Dev-Tenant (Daten ohne Login sichtbar)
    - Supabase-Modus      → Demo-Tenant "Demo IT-Solutions GmbH";
                            mit SUPABASE_SERVICE_ROLE_KEY wird zusätzlich ein
                            Login-User angelegt und dem Tenant zugeordnet.
"""

from __future__ import annotations

import sys

from estimateiq.angebot import config
from estimateiq.angebot.database import SessionLocal, init_db
from estimateiq.angebot.models import (
    Angebot, Leistungsposition, Projekt, Rolle, Tenant, TenantUser,
)

DEMO_TENANT_NAME = "Demo IT-Solutions GmbH"
DEMO_LOGIN_EMAIL = "demo@estimateiq.de"
DEMO_LOGIN_PASSWORT = "Demo1234!"

# ── Rollen & Stundensätze (DACH-marktüblich, netto €/h) ──────────────────────
ROLLEN: list[tuple[str, float]] = [
    ("Projektleiter",       130.0),
    ("Senior Developer",    120.0),
    ("Backend Developer",   110.0),
    ("Frontend Developer",  105.0),
    ("Mobile Developer",    115.0),
    ("DevOps Engineer",     125.0),
    ("UX/UI Designer",      100.0),
    ("QA Engineer",          85.0),
    ("Junior Developer",     75.0),
]

# ── Referenzprojekte: (Name, Kunde, [(Beschreibung, Rolle, Phase, soll, ist)]) ─
PROJEKTE: list[dict] = [
    {
        "name": "CRM-Einführung Großhandel Berger",
        "kunde": "Berger Großhandel GmbH",
        "positionen": [
            ("Anforderungsanalyse und Workshops mit Vertrieb und Innendienst", "Projektleiter", "Analyse", 32, 38),
            ("Datenmodell und Rechtekonzept für Kundenverwaltung", "Backend Developer", "Konzeption", 24, 22),
            ("Frontend Kundenportal in React mit Rollen-Login", "Frontend Developer", "Umsetzung", 90, 104),
            ("REST-API für Kontakte, Angebote und Aktivitäten", "Backend Developer", "Umsetzung", 72, 68),
            ("Datenmigration aus Altsystem inklusive Bereinigung", "Backend Developer", "Migration", 40, 55),
            ("Testautomatisierung und manuelle Abnahmetests", "QA Engineer", "Test", 32, 30),
            ("Anwenderschulung und Go-Live-Begleitung", "Projektleiter", "Rollout", 16, 18),
        ],
    },
    {
        "name": "E-Commerce Relaunch Modehaus Vogt",
        "kunde": "Modehaus Vogt KG",
        "positionen": [
            ("Shopware 6 Setup, Hosting und Grundkonfiguration", "Senior Developer", "Setup", 24, 20),
            ("Individuelles Theme und responsives Storefront-Design", "UX/UI Designer", "Design", 48, 52),
            ("Produktkatalog, Kategoriebaum und Filter-Navigation", "Frontend Developer", "Umsetzung", 40, 44),
            ("Zahlungsanbindung Stripe, PayPal und Kauf auf Rechnung", "Backend Developer", "Umsetzung", 32, 28),
            ("Schnittstelle zum Warenwirtschaftssystem für Lagerbestände", "Backend Developer", "Integration", 36, 41),
            ("SEO-Optimierung und Performance-Tuning", "Frontend Developer", "Optimierung", 20, 18),
            ("Testing über alle Browser und Abnahme", "QA Engineer", "Test", 24, 26),
        ],
    },
    {
        "name": "Außendienst-App Klimatechnik Reuter",
        "kunde": "Reuter Klimatechnik AG",
        "positionen": [
            ("Konzeption Nutzerführung und Feature-Priorisierung", "Projektleiter", "Konzeption", 24, 26),
            ("UI/UX Design für iOS und Android inklusive Prototyp", "UX/UI Designer", "Design", 56, 60),
            ("iOS-App in Swift mit Auftrags- und Terminverwaltung", "Mobile Developer", "Umsetzung", 96, 110),
            ("Android-App in Kotlin mit identischem Funktionsumfang", "Mobile Developer", "Umsetzung", 96, 102),
            ("Backend-API und Offline-Synchronisation der Aufträge", "Backend Developer", "Umsetzung", 64, 72),
            ("Testing auf Geräten und Store-Deployment", "QA Engineer", "Test", 32, 34),
        ],
    },
    {
        "name": "Cloud-Migration Logistik Sander",
        "kunde": "Sander Logistik GmbH",
        "positionen": [
            ("Ist-Analyse der Server-Landschaft und Migrationsstrategie", "DevOps Engineer", "Analyse", 32, 30),
            ("Zielarchitektur auf AWS mit VPC, ECS und RDS", "DevOps Engineer", "Konzeption", 40, 44),
            ("Infrastruktur als Code mit Terraform", "DevOps Engineer", "Umsetzung", 56, 62),
            ("Migration der Anwendungen und Datenbanken", "Backend Developer", "Migration", 48, 58),
            ("CI/CD-Pipeline mit automatisierten Deployments", "DevOps Engineer", "Umsetzung", 32, 30),
            ("Monitoring, Alerting und Dokumentation", "DevOps Engineer", "Abschluss", 24, 22),
        ],
    },
    {
        "name": "Website-Relaunch Stadtwerke Lindau",
        "kunde": "Stadtwerke Lindau",
        "positionen": [
            ("Konzept, Informationsarchitektur und Wireframes", "UX/UI Designer", "Konzeption", 32, 34),
            ("Screendesign für Startseite und Unterseiten", "UX/UI Designer", "Design", 40, 38),
            ("TYPO3-Templating und barrierefreie Umsetzung", "Frontend Developer", "Umsetzung", 72, 80),
            ("Content-Migration und Redaktionsschulung", "Junior Developer", "Migration", 32, 40),
            ("DSGVO-konforme Formulare und Cookie-Management", "Backend Developer", "Umsetzung", 20, 18),
            ("Abnahme, Performance-Check und Go-Live", "QA Engineer", "Test", 16, 15),
        ],
    },
    {
        "name": "BI-Dashboard Produktion Hofmann",
        "kunde": "Hofmann Maschinenbau GmbH",
        "positionen": [
            ("Anforderungsaufnahme Kennzahlen und Berichtswesen", "Projektleiter", "Analyse", 24, 26),
            ("Datenanbindung an ERP und Maschinendaten", "Backend Developer", "Integration", 40, 46),
            ("ETL-Strecken und Aufbereitung der Rohdaten", "Backend Developer", "Umsetzung", 48, 52),
            ("Power-BI-Dashboards für Produktion und Vertrieb", "Frontend Developer", "Umsetzung", 40, 38),
            ("Rollen- und Rechtekonzept für Berichte", "Backend Developer", "Umsetzung", 16, 14),
            ("Schulung der Fachbereiche", "Projektleiter", "Rollout", 12, 13),
        ],
    },
    {
        "name": "API-Integration Zahlungsdienstleister Kern",
        "kunde": "Kern Finanzservice GmbH",
        "positionen": [
            ("Analyse der Schnittstellen und Datenflüsse", "Senior Developer", "Analyse", 24, 22),
            ("Schnittstellendesign und API-Spezifikation", "Backend Developer", "Konzeption", 32, 30),
            ("Implementierung der REST-Anbindung mit Webhooks", "Backend Developer", "Umsetzung", 56, 64),
            ("Fehlerbehandlung, Retry-Logik und Logging", "Backend Developer", "Umsetzung", 24, 28),
            ("Technische Dokumentation und Übergabe", "Senior Developer", "Abschluss", 16, 14),
            ("Integrationstests und Lasttests", "QA Engineer", "Test", 24, 26),
        ],
    },
]


def _hole_ziel_tenant(db) -> Tenant:
    """Ermittelt/erzeugt den Tenant, in den geseedet wird."""
    if config.AUTH_DISABLED:
        tenant = db.get(Tenant, config.DEV_TENANT_ID)
        if tenant is None:
            tenant = Tenant(id=config.DEV_TENANT_ID, name=config.DEV_TENANT_NAME)
            db.add(tenant)
            db.flush()
        return tenant

    tenant = db.query(Tenant).filter(Tenant.name == DEMO_TENANT_NAME).first()
    if tenant is None:
        tenant = Tenant(name=DEMO_TENANT_NAME)
        db.add(tenant)
        db.flush()
    return tenant


def _loesche_tenant_daten(db, tenant_id: str) -> None:
    """Löscht alle Geschäftsdaten eines Tenants (für --reset)."""
    for modell in (Leistungsposition, Angebot, Projekt, Rolle):
        db.query(modell).filter(modell.tenant_id == tenant_id).delete()
    db.flush()


def _seed_rollen(db, tenant_id: str) -> dict[str, int]:
    """Legt Rollen an (get-or-create) und gibt Name→id zurück."""
    rollen_map: dict[str, int] = {}
    for name, satz in ROLLEN:
        rolle = (
            db.query(Rolle)
            .filter(Rolle.tenant_id == tenant_id, Rolle.name == name)
            .first()
        )
        if rolle is None:
            rolle = Rolle(tenant_id=tenant_id, name=name, stundensatz_eur=satz)
            db.add(rolle)
            db.flush()
        rollen_map[name] = rolle.id
    return rollen_map


def _seed_projekte(db, tenant_id: str, rollen_map: dict[str, int], embed, embed_batch) -> int:
    """Legt Referenzprojekte samt Positionen und Embeddings an."""
    satz_map = {name: satz for name, satz in ROLLEN}
    angelegt = 0

    for proj in PROJEKTE:
        vorhanden = (
            db.query(Projekt)
            .filter(
                Projekt.tenant_id == tenant_id,
                Projekt.name == proj["name"],
                Projekt.ist_referenz == True,  # noqa: E712
            )
            .first()
        )
        if vorhanden:
            continue  # idempotent

        projekt = Projekt(
            tenant_id=tenant_id,
            name=proj["name"],
            kunde=proj["kunde"],
            beschreibung=f"Referenzprojekt: {proj['name']}",
            status="abgeschlossen",
            ist_referenz=True,
        )
        db.add(projekt)
        db.flush()

        texte = [p[0] for p in proj["positionen"]]
        vecs = embed_batch(texte) if embed_batch else [None] * len(texte)

        for i, (beschreibung, rolle_name, phase, soll, ist) in enumerate(proj["positionen"]):
            pos = Leistungsposition(
                tenant_id=tenant_id,
                projekt_id=projekt.id,
                rolle_id=rollen_map.get(rolle_name),
                beschreibung_text=beschreibung,
                soll_stunden=float(soll),
                ist_stunden=float(ist),
                stundensatz_snapshot=satz_map.get(rolle_name),
                phase=phase,
                ist_historisch=False,
            )
            if vecs and vecs[i] is not None:
                pos.set_embedding(vecs[i])
            db.add(pos)

        # Projekt-Embedding: Name + Positionstexte (für Referenzprojekt-Suche)
        if embed:
            try:
                projekt.set_embedding(embed(proj["name"] + ". " + " | ".join(texte)))
            except Exception:
                pass

        angelegt += 1

    return angelegt


def _seed_login_user(tenant_id: str) -> str | None:
    """
    Legt in Supabase einen Login-User an und ordnet ihn dem Tenant zu.
    Nur möglich mit SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY. Gibt die
    Benutzer-ID zurück oder None (dann bitte manuell anlegen, siehe Ausgabe).
    """
    if not (config.SUPABASE_URL and config.SUPABASE_SERVICE_ROLE_KEY):
        return None

    # Client-Aufbau + Admin-Aufrufe komplett absichern: schlägt die automatische
    # Anlage fehl (z. B. neuer sb_secret_-Key, den supabase-py noch nicht
    # akzeptiert), fällt das Skript sauber auf die manuelle Anleitung zurück.
    try:
        from supabase import create_client
        client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)
    except Exception as exc:
        print(f"[Hinweis] Automatische Login-User-Anlage nicht möglich: {exc}")
        print("  (supabase-py akzeptiert die neuen sb_secret_-Keys noch nicht – "
              "nutze einen Legacy-service_role-Key oder lege den User manuell an.)")
        return None

    # Bestehenden User finden oder neu anlegen
    user_id: str | None = None
    try:
        res = client.auth.admin.create_user({
            "email": DEMO_LOGIN_EMAIL,
            "password": DEMO_LOGIN_PASSWORT,
            "email_confirm": True,
        })
        user_id = res.user.id
    except Exception:
        # User existiert vermutlich schon → in der Liste suchen
        try:
            for u in client.auth.admin.list_users():
                if getattr(u, "email", None) == DEMO_LOGIN_EMAIL:
                    user_id = u.id
                    break
        except Exception:
            pass

    if not user_id:
        return None

    # Zuordnung in tenant_users (eigene DB-Session, get-or-create)
    db = SessionLocal()
    try:
        tu = db.get(TenantUser, user_id)
        if tu is None:
            db.add(TenantUser(user_id=user_id, tenant_id=tenant_id, email=DEMO_LOGIN_EMAIL))
        else:
            tu.tenant_id = tenant_id
        db.commit()
    finally:
        db.close()

    return user_id


def seed(reset: bool = False) -> None:
    init_db()

    try:
        from estimateiq.angebot.embeddings import embed, embed_batch
    except Exception as exc:
        print(f"[Warnung] Embedding-Modell nicht verfügbar ({exc}). "
              "Daten werden ohne Embeddings angelegt – die Ähnlichkeitssuche "
              "liefert dann keine Treffer.")
        embed = embed_batch = None  # type: ignore[assignment]

    db = SessionLocal()
    try:
        tenant = _hole_ziel_tenant(db)
        if reset:
            _loesche_tenant_daten(db, tenant.id)
            print(f"[Reset] Bestehende Daten von Tenant '{tenant.name}' gelöscht.")

        rollen_map = _seed_rollen(db, tenant.id)
        angelegt = _seed_projekte(db, tenant.id, rollen_map, embed, embed_batch)
        db.commit()

        n_projekte = (
            db.query(Projekt)
            .filter(Projekt.tenant_id == tenant.id, Projekt.ist_referenz == True)  # noqa: E712
            .count()
        )
        n_positionen = (
            db.query(Leistungsposition)
            .filter(Leistungsposition.tenant_id == tenant.id)
            .count()
        )
    finally:
        db.close()

    print("─" * 60)
    print(f"Tenant:        {tenant.name}")
    print(f"  ID:          {tenant.id}")
    print(f"Rollen:        {len(ROLLEN)}")
    print(f"Referenzprojekte: {n_projekte} ({angelegt} neu angelegt)")
    print(f"Positionen:    {n_positionen}")

    if config.AUTH_DISABLED:
        print("\nModus: lokal (AUTH_DISABLED=true) – kein Login nötig.")
        print("Die Daten sind im laufenden Dev-Server sofort sichtbar.")
    else:
        print("\nModus: Supabase.")
        user_id = _seed_login_user(tenant.id)
        if user_id:
            print("Login-User angelegt und dem Tenant zugeordnet:")
            print(f"  E-Mail:   {DEMO_LOGIN_EMAIL}")
            print(f"  Passwort: {DEMO_LOGIN_PASSWORT}")
        else:
            print("Login-User bitte manuell anlegen:")
            print(f"  1. Supabase → Authentication → Users → 'Add user' → 'Create new user'")
            print(f"     E-Mail: {DEMO_LOGIN_EMAIL}, Passwort: {DEMO_LOGIN_PASSWORT}, 'Auto Confirm User' anhaken")
            print("  2. Benutzer-UID kopieren und im SQL Editor ausführen:")
            print("     insert into tenant_users (user_id, tenant_id, email)")
            print(f"     values ('<USER-UID>', '{tenant.id}', '{DEMO_LOGIN_EMAIL}')")
            print("     on conflict (user_id) do update set tenant_id = excluded.tenant_id;")
    print("─" * 60)


if __name__ == "__main__":
    seed(reset="--reset" in sys.argv)
