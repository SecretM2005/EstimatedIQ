"""
RBAC Phase 2/3: Rote Tests (TDD) für KPI-Registry, Kpi-Definitionen und
Dashboard-Layout – VOR der Router-Implementierung geschrieben (siehe CLAUDE.md
/ Auftrag: "Bevor du migrierst: schreib die Cross-Tenant- und Permission-Tests
für die NEUEN Endpunkte zuerst, lass sie rot laufen, dann implementiere.").

Erwartete Endpunkte (werden erst in router.py ergänzt):
  GET    /api/v2/kpi-registry
  GET    /api/v2/kpi-definitionen
  POST   /api/v2/kpi-definitionen
  PATCH  /api/v2/kpi-definitionen/{id}
  DELETE /api/v2/kpi-definitionen/{id}
  POST   /api/v2/kpi-definitionen/vorschau
  GET    /api/v2/dashboard/layout
  PUT    /api/v2/dashboard/layout
  DELETE /api/v2/dashboard/layout
"""

def _custom_kpi_body(**overrides) -> dict:
    body = {
        "key": "eigene_kennzahl",
        "label": "Eigene Kennzahl",
        "quelle": "projekte",
        "feld": "auftragswert",
        "aggregation": "sum",
        "filters": [],
    }
    body.update(overrides)
    return body


# ── Permission-Gates (403, nicht leeres 200 oder 404) ────────────────────────

def test_kpi_registry_erfordert_permission(client, h):
    r = client.get("/api/v2/kpi-registry", headers=h.auth(h.USER_A))
    assert r.status_code == 403

    r = client.get("/api/v2/kpi-registry", headers=h.auth(h.OWNER_A))
    assert r.status_code == 200
    katalog = r.json()
    assert "projekte" in katalog["quellen"]
    assert "leistungspositionen" in katalog["quellen"]
    assert "sum" in katalog["aggregationen"]


def test_kpi_definitionen_permission_gates(client, h):
    """Mitarbeiter (ohne settings.manage_kpis) wird auf allen Schreib-/Lese-
    Endpunkten mit 403 abgewiesen – nicht mit 404 (Endpunkt existiert nicht)
    oder leerem 200 (Berechtigung nicht geprüft)."""
    auth = h.auth(h.USER_A)

    assert client.get("/api/v2/kpi-definitionen", headers=auth).status_code == 403
    assert client.post("/api/v2/kpi-definitionen", json=_custom_kpi_body(), headers=auth).status_code == 403
    assert client.post("/api/v2/kpi-definitionen/vorschau", json=_custom_kpi_body(), headers=auth).status_code == 403
    assert client.patch("/api/v2/kpi-definitionen/1", json={"label": "x"}, headers=auth).status_code == 403
    assert client.delete("/api/v2/kpi-definitionen/1", headers=auth).status_code == 403


def test_dashboard_layout_permission_gates(client, h):
    auth = h.auth(h.USER_A)
    # Lesen des eigenen Dashboards ist mit dashboard.view erlaubt.
    assert client.get("/api/v2/dashboard/layout", headers=auth).status_code == 200
    # "Ansehen als Rolle X" ist eine Admin-Funktion, auch für Mitarbeiter mit
    # dashboard.view gesperrt.
    r = client.get(f"/api/v2/dashboard/layout?als_rolle_id={h.teamrollen_a['Admin']}", headers=auth)
    assert r.status_code == 403
    # Layout-Bearbeitung ist IMMER an settings.manage_layout gebunden – auch
    # für das eigene persönliche Layout (scope=user).
    body = {"scope": "user", "layout": []}
    assert client.put("/api/v2/dashboard/layout", json=body, headers=auth).status_code == 403
    assert client.delete("/api/v2/dashboard/layout?scope=user", headers=auth).status_code == 403


# ── Whitelist-Validierung (kein freies SQL) ──────────────────────────────────

def test_kpi_definition_unbekanntes_feld_wird_abgelehnt(client, h):
    body = _custom_kpi_body(feld="does_not_exist")
    r = client.post("/api/v2/kpi-definitionen", json=body, headers=h.auth(h.OWNER_A))
    assert r.status_code == 400


def test_kpi_definition_unbekannte_quelle_wird_abgelehnt(client, h):
    body = _custom_kpi_body(quelle="benutzer")
    r = client.post("/api/v2/kpi-definitionen", json=body, headers=h.auth(h.OWNER_A))
    assert r.status_code == 400


def test_kpi_definition_unerlaubter_operator_wird_abgelehnt(client, h):
    body = _custom_kpi_body(filters=[{"feld": "auftragswert", "operator": "like", "wert": "x"}])
    r = client.post("/api/v2/kpi-definitionen", json=body, headers=h.auth(h.OWNER_A))
    assert r.status_code == 400


def test_kpi_vorschau_lehnt_ungueltige_definition_ab(client, h):
    body = _custom_kpi_body(aggregation="unbekannt")
    r = client.post("/api/v2/kpi-definitionen/vorschau", json=body, headers=h.auth(h.OWNER_A))
    assert r.status_code == 400


def test_kpi_definition_injection_versuch_in_filterwert_wird_neutralisiert(client, h):
    """Filterwerte laufen über Parameterbindung – ein String, der wie ein
    SQL-Angriff aussieht, wird als reiner Vergleichswert behandelt, nicht
    ausgeführt. Nachweis: exakt 1 Treffer (Literal-Match) UND die Tabelle
    bleibt danach voll funktionsfähig."""
    boesartig = "Bad'); DROP TABLE projekte;--"
    auth = h.auth(h.OWNER_A)

    r = client.post("/api/v2/projekte", json={"name": "Injection-Testprojekt", "kunde": boesartig}, headers=auth)
    assert r.status_code == 201

    vorschau_body = {
        "quelle": "projekte", "feld": "auftragswert", "aggregation": "count",
        "filters": [{"feld": "kunde", "operator": "=", "wert": boesartig}],
    }
    r = client.post("/api/v2/kpi-definitionen/vorschau", json=vorschau_body, headers=auth)
    assert r.status_code == 200
    assert r.json()["wert"] == 1.0

    # Tabelle intakt: normale Projekt-Liste funktioniert weiterhin.
    r = client.get("/api/v2/projekte", headers=auth)
    assert r.status_code == 200
    assert any(p["kunde"] == boesartig for p in r.json())


# ── Cross-Tenant-Isolation ────────────────────────────────────────────────────

def test_kpi_definitionen_cross_tenant_isolation(client, h):
    owner_a = h.auth(h.OWNER_A)
    admin_b = h.auth(h.ADMIN_B)

    r = client.post("/api/v2/kpi-definitionen", json=_custom_kpi_body(), headers=owner_a)
    assert r.status_code == 201
    kpi_id = r.json()["id"]

    # Tenant B sieht die Custom-KPI von Tenant A nicht in der Liste.
    r = client.get("/api/v2/kpi-definitionen", headers=admin_b)
    assert r.status_code == 200
    assert all(k["id"] != kpi_id for k in r.json())

    # Direkter Zugriff über die ID verhält sich wie nicht existent.
    assert client.patch(f"/api/v2/kpi-definitionen/{kpi_id}", json={"label": "gehackt"}, headers=admin_b).status_code == 404
    assert client.delete(f"/api/v2/kpi-definitionen/{kpi_id}", headers=admin_b).status_code == 404


def test_system_kpi_kann_nicht_geloescht_werden(client, h):
    system_kpi_id = h.kpis_a["offene_angebote_anzahl"]
    r = client.delete(f"/api/v2/kpi-definitionen/{system_kpi_id}", headers=h.auth(h.OWNER_A))
    assert r.status_code == 403


def test_dashboard_layout_cross_tenant_role_referenz_wird_abgelehnt(client, h):
    """Ein Tenant darf sein Rollen-Layout nicht auf eine fremde Teamrolle-ID legen."""
    fremde_rolle_id = h.teamrollen_b["Owner"]
    body = {"scope": "role", "scope_ref_id": str(fremde_rolle_id), "layout": []}
    r = client.put("/api/v2/dashboard/layout", json=body, headers=h.auth(h.OWNER_A))
    assert r.status_code == 400


def test_dashboard_layout_cross_tenant_kpi_referenz_wird_abgelehnt(client, h):
    """Ein Layout darf keine KPI-ID eines fremden Tenants referenzieren."""
    fremde_kpi_id = h.kpis_b["offene_angebote_anzahl"]
    body = {
        "scope": "tenant_default",
        "layout": [{"kpi_id": fremde_kpi_id, "x": 0, "y": 0, "w": 1, "h": 1}],
    }
    r = client.put("/api/v2/dashboard/layout", json=body, headers=h.auth(h.OWNER_A))
    assert r.status_code == 400


# ── Auflösungsreihenfolge: user > role > tenant_default > system_default ────

def test_dashboard_layout_resolution_order(client, h):
    owner_auth = h.auth(h.OWNER_A)
    anzahl_kpi = h.kpis_a["offene_angebote_anzahl"]
    trefferquote_kpi = h.kpis_a["trefferquote"]
    wert_kpi = h.kpis_a["offene_angebote_wert"]

    # Ohne jedes DB-Layout: Code-seitiger Systemdefault greift.
    r = client.get("/api/v2/dashboard/layout", headers=owner_auth)
    assert r.status_code == 200
    assert r.json()["scope_used"] == "system_default"

    # tenant_default gesetzt → überschreibt Systemdefault.
    r = client.put("/api/v2/dashboard/layout", json={
        "scope": "tenant_default",
        "layout": [{"kpi_id": trefferquote_kpi, "x": 0, "y": 0, "w": 1, "h": 1}],
    }, headers=owner_auth)
    assert r.status_code == 200

    r = client.get("/api/v2/dashboard/layout", headers=owner_auth)
    assert r.json()["scope_used"] == "tenant_default"
    assert [w["kpi_id"] for w in r.json()["widgets"]] == [trefferquote_kpi]

    # role-Layout für die Owner-Rolle → überschreibt tenant_default.
    owner_rolle_id = h.teamrollen_a["Owner"]
    r = client.put("/api/v2/dashboard/layout", json={
        "scope": "role", "scope_ref_id": str(owner_rolle_id),
        "layout": [{"kpi_id": anzahl_kpi, "x": 0, "y": 0, "w": 1, "h": 1}],
    }, headers=owner_auth)
    assert r.status_code == 200

    r = client.get("/api/v2/dashboard/layout", headers=owner_auth)
    assert r.json()["scope_used"] == "role"
    assert [w["kpi_id"] for w in r.json()["widgets"]] == [anzahl_kpi]

    # user-Layout → überschreibt role.
    r = client.put("/api/v2/dashboard/layout", json={
        "scope": "user",
        "layout": [{"kpi_id": wert_kpi, "x": 0, "y": 0, "w": 1, "h": 1}],
    }, headers=owner_auth)
    assert r.status_code == 200

    r = client.get("/api/v2/dashboard/layout", headers=owner_auth)
    assert r.json()["scope_used"] == "user"
    assert [w["kpi_id"] for w in r.json()["widgets"]] == [wert_kpi]

    # Zurücksetzen des persönlichen Layouts → fällt zurück auf role.
    r = client.delete("/api/v2/dashboard/layout?scope=user", headers=owner_auth)
    assert r.status_code == 204

    r = client.get("/api/v2/dashboard/layout", headers=owner_auth)
    assert r.json()["scope_used"] == "role"


def test_dashboard_layout_tenant_default_isoliert_je_tenant(client, h):
    """tenant_default von Tenant A darf Tenant B nicht beeinflussen."""
    trefferquote_a = h.kpis_a["trefferquote"]
    client.put("/api/v2/dashboard/layout", json={
        "scope": "tenant_default",
        "layout": [{"kpi_id": trefferquote_a, "x": 0, "y": 0, "w": 1, "h": 1}],
    }, headers=h.auth(h.OWNER_A))

    r = client.get("/api/v2/dashboard/layout", headers=h.auth(h.ADMIN_B))
    assert r.status_code == 200
    assert r.json()["scope_used"] == "system_default"


# ── required_permission steuert, ob der Wert überhaupt Teil der Response ist ─

def test_required_permission_entfernt_wert_serverseitig(client, h):
    anzahl_kpi = h.kpis_a["offene_angebote_anzahl"]        # keine Permission nötig
    wert_kpi   = h.kpis_a["offene_angebote_wert"]           # projekte.marge_einsehen nötig

    client.put("/api/v2/dashboard/layout", json={
        "scope": "tenant_default",
        "layout": [
            {"kpi_id": anzahl_kpi, "x": 0, "y": 0, "w": 1, "h": 1},
            {"kpi_id": wert_kpi, "x": 1, "y": 0, "w": 1, "h": 1},
        ],
    }, headers=h.auth(h.OWNER_A))

    # Owner hat projekte.marge_einsehen → beide Widgets vorhanden.
    r = client.get("/api/v2/dashboard/layout", headers=h.auth(h.OWNER_A))
    kpi_ids = {w["kpi_id"] for w in r.json()["widgets"]}
    assert kpi_ids == {anzahl_kpi, wert_kpi}

    # Mitarbeiter (USER_A) hat projekte.marge_einsehen NICHT → Widget fehlt
    # komplett aus der Response (nicht nur ausgeblendet).
    r = client.get("/api/v2/dashboard/layout", headers=h.auth(h.USER_A))
    kpi_ids = {w["kpi_id"] for w in r.json()["widgets"]}
    assert kpi_ids == {anzahl_kpi}
    assert all(w["kpi_id"] != wert_kpi for w in r.json()["widgets"])


def test_required_permission_gate_gilt_auch_fuer_custom_kpis(client, h):
    """Wie oben, aber über eine Custom-Kennzahl (generischer Builder) statt
    einer System-Kennzahl – die System-Kennzahl 'offene_angebote_wert' hat
    im Resolver eine zusätzliche, redundante hat_marge-Prüfung, die einen
    Fehler im allgemeinen required_permission-Gate in berechne_kpi_wert()
    maskieren könnte. Diese Custom-Kennzahl hat KEINE solche Redundanz und
    prüft daher genau diesen einen Codepfad isoliert."""
    owner_auth = h.auth(h.OWNER_A)
    r = client.post("/api/v2/kpi-definitionen", json=_custom_kpi_body(
        key="custom_margen_kpi", required_permission="projekte.marge_einsehen",
    ), headers=owner_auth)
    assert r.status_code == 201
    custom_kpi_id = r.json()["id"]

    client.put("/api/v2/dashboard/layout", json={
        "scope": "tenant_default",
        "layout": [{"kpi_id": custom_kpi_id, "x": 0, "y": 0, "w": 1, "h": 1}],
    }, headers=owner_auth)

    r = client.get("/api/v2/dashboard/layout", headers=owner_auth)
    assert {w["kpi_id"] for w in r.json()["widgets"]} == {custom_kpi_id}

    r = client.get("/api/v2/dashboard/layout", headers=h.auth(h.USER_A))
    assert r.json()["widgets"] == []
