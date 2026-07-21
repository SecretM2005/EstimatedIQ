"""
PRIORITÄT 1 – Multi-Tenancy-Isolation.

Die wichtigsten Tests im Projekt: Tenant B darf NIEMALS Daten von Tenant A
sehen oder verändern. Jede Regression hier ist ein Datenleck.
"""


# ── Auth-Guards ───────────────────────────────────────────────────────────────

def test_ohne_token_401(client):
    """Ohne Authorization-Header gibt es keine Daten."""
    assert client.get("/api/v2/projekte").status_code == 401


def test_ungueltiges_token_401(client):
    """Ein manipuliertes/kaputtes Token wird abgelehnt."""
    r = client.get("/api/v2/projekte", headers={"Authorization": "Bearer kaputt.token.hier"})
    assert r.status_code == 401


def test_gueltiges_token_ohne_tenant_403(client, h):
    """Gültig signiert, aber der User ist keinem Tenant zugeordnet → 403 (kein Zugriff)."""
    r = client.get("/api/v2/projekte", headers=h.auth("voellig-unbekannter-user"))
    assert r.status_code == 403


# ── Daten-Isolation zwischen Tenants ──────────────────────────────────────────

def test_projektliste_ist_tenant_isoliert(client, h):
    """Ein von A angelegtes Projekt taucht in B's Liste nicht auf."""
    client.post("/api/v2/projekte", json={"name": "Geheimprojekt A", "kunde": "ACME"},
                headers=h.auth(h.USER_A))

    liste_a = client.get("/api/v2/projekte", headers=h.auth(h.USER_A)).json()
    liste_b = client.get("/api/v2/projekte", headers=h.auth(h.USER_B)).json()

    assert len(liste_a) == 1
    assert liste_a[0]["name"] == "Geheimprojekt A"
    assert liste_b == []  # B sieht nichts von A


def test_fremdes_projekt_direktzugriff_404(client, h):
    """B kann A's Projekt nicht per ID abrufen – es verhält sich wie nicht existent."""
    pid = client.post("/api/v2/projekte", json={"name": "A-Projekt"},
                      headers=h.auth(h.USER_A)).json()["id"]

    r_a = client.get(f"/api/v2/projekte/{pid}", headers=h.auth(h.USER_A))
    r_b = client.get(f"/api/v2/projekte/{pid}", headers=h.auth(h.USER_B))

    assert r_a.status_code == 200
    assert r_b.status_code == 404  # NICHT 403 – Fremdobjekte existieren schlicht nicht


def test_fremde_position_loeschen_404(client, h, fake_embed):
    """B kann eine Position aus A's Projekt nicht löschen (404), sie bleibt erhalten."""
    pid = client.post("/api/v2/projekte", json={"name": "A-Projekt"},
                      headers=h.auth(h.USER_A)).json()["id"]
    pos_id = client.post(
        f"/api/v2/projekte/{pid}/positionen",
        json={"beschreibung_text": "Konzeption", "soll_stunden": 10, "stundensatz_eur": 100},
        headers=h.auth(h.USER_A),
    ).json()["id"]

    r_del = client.delete(f"/api/v2/positionen/{pos_id}", headers=h.auth(h.USER_B))
    assert r_del.status_code == 404

    # Position ist bei A weiterhin vorhanden
    positionen_a = client.get(f"/api/v2/projekte/{pid}/positionen", headers=h.auth(h.USER_A)).json()
    assert len(positionen_a) == 1
