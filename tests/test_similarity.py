"""
PRIORITÄT 1 – Isolation der Ähnlichkeitssuche (der subtilste Leck-Pfad)
PRIORITÄT 2 – korrektes Ranking der Suche

Die Embedding-Suche ist besonders heikel: Wenn hier der tenant_id-Filter fehlt,
bekäme ein Tenant fremde Positionen als "ähnliche Treffer" vorgeschlagen –
ein Datenleck, das in der UI wie ein Feature aussieht.
"""

from estimateiq.angebot import models
from estimateiq.angebot.similarity import suche_aehnliche, suche_aehnliche_projekte


def _unit(index: int, dim: int = 384) -> list[float]:
    v = [0.0] * dim
    v[index % dim] = 1.0
    return v


def _projekt(s, tenant_id, name, ist_referenz=False):
    p = models.Projekt(tenant_id=tenant_id, name=name, ist_referenz=ist_referenz)
    s.add(p)
    s.flush()
    return p


def _position(s, tenant_id, projekt_id, text, vec, soll, ist=None):
    pos = models.Leistungsposition(
        tenant_id=tenant_id, projekt_id=projekt_id,
        beschreibung_text=text, soll_stunden=soll, ist_stunden=ist,
        ist_historisch=False,
    )
    pos.set_embedding(vec)
    s.add(pos)
    s.flush()
    return pos


# ── P1: Suche ist tenant-isoliert ─────────────────────────────────────────────

def test_positionssuche_endpoint_liefert_keine_fremden_treffer(client, h, fake_embed):
    """
    A und B haben eine Position mit IDENTISCHEM Text (also identischem Vektor).
    Sucht B danach, darf ausschließlich B's Position zurückkommen – niemals A's.
    """
    pid_a = client.post("/api/v2/projekte", json={"name": "A"}, headers=h.auth(h.USER_A)).json()["id"]
    pid_b = client.post("/api/v2/projekte", json={"name": "B"}, headers=h.auth(h.USER_B)).json()["id"]

    id_a = client.post(f"/api/v2/projekte/{pid_a}/positionen",
                       json={"beschreibung_text": "Zahlungsanbindung Stripe", "soll_stunden": 12},
                       headers=h.auth(h.USER_A)).json()["id"]
    id_b = client.post(f"/api/v2/projekte/{pid_b}/positionen",
                       json={"beschreibung_text": "Zahlungsanbindung Stripe", "soll_stunden": 12},
                       headers=h.auth(h.USER_B)).json()["id"]

    res = client.post("/api/v2/positionen/suche",
                      json={"beschreibung_text": "Zahlungsanbindung Stripe", "k": 5},
                      headers=h.auth(h.USER_B)).json()

    treffer_ids = [t["id"] for t in res["treffer"]]
    assert id_b in treffer_ids          # B findet seine eigene Position
    assert id_a not in treffer_ids      # aber NIEMALS die identische von A


def test_referenzprojekt_suche_ist_tenant_isoliert(db_factory):
    """suche_aehnliche_projekte gibt nur Referenzprojekte des eigenen Tenants zurück."""
    s = db_factory()
    try:
        pa = _projekt(s, "tenant-a", "Ref A", ist_referenz=True)
        pa.set_embedding(_unit(0))
        pb = _projekt(s, "tenant-b", "Ref B", ist_referenz=True)
        pb.set_embedding(_unit(0))
        s.commit()

        treffer_b = suche_aehnliche_projekte(_unit(0), s, tenant_id="tenant-b", k=5)
        namen = [t["projekt_name"] for t in treffer_b]
        assert "Ref B" in namen
        assert "Ref A" not in namen  # A's Referenzprojekt bleibt unsichtbar für B
    finally:
        s.close()


# ── P2: Ranking der Suche ist korrekt ─────────────────────────────────────────

def test_similarity_ranking_und_schaetzvorschlag(db_factory):
    """
    Drei Positionen mit orthogonalen Vektoren; die Query trifft exakt eine.
    Erwartung: dieser Treffer steht oben und der Stundenvorschlag entspricht ihm.
    """
    s = db_factory()
    try:
        p = _projekt(s, "tenant-a", "Projekt A")
        _position(s, "tenant-a", p.id, "Treffer",     _unit(0), soll=10)
        _position(s, "tenant-a", p.id, "Daneben 1",   _unit(1), soll=20)
        _position(s, "tenant-a", p.id, "Daneben 2",   _unit(2), soll=30)
        s.commit()

        res = suche_aehnliche(_unit(0), s, tenant_id="tenant-a", k=3)

        assert res["treffer"][0]["beschreibung_text"] == "Treffer"
        assert res["treffer"][0]["aehnlichkeit"] > 0.99   # exakter Cosine-Treffer
        assert res["schaetzvorschlag"] == 10.0            # gewichtet nur vom echten Treffer
        assert res["n_verglichen"] == 3
    finally:
        s.close()
