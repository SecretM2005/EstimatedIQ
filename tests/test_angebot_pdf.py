"""
PRIORITÄT 2 – Angebotsberechnung und PDF.

Zwei getrennte Absicherungen:
  - Die Geldrechnung (soll_kosten) muss stimmen – sie steht auf jedem Angebot.
  - Die PDF-Erzeugung muss ein valides Dokument liefern und nicht crashen.
"""

from estimateiq.angebot.pdf_export import erstelle_angebots_pdf


def test_angebotssumme_wird_korrekt_aggregiert(client, h, fake_embed):
    """soll_kosten = Summe(soll_stunden * Stundensatz) über die Positionen."""
    pid = client.post("/api/v2/projekte", json={"name": "Kalkulation"},
                      headers=h.auth(h.USER_A)).json()["id"]

    client.post(f"/api/v2/projekte/{pid}/positionen",
                json={"beschreibung_text": "Konzept", "soll_stunden": 10, "stundensatz_eur": 100},
                headers=h.auth(h.USER_A))
    client.post(f"/api/v2/projekte/{pid}/positionen",
                json={"beschreibung_text": "Umsetzung", "soll_stunden": 20, "stundensatz_eur": 120},
                headers=h.auth(h.USER_A))

    projekt = client.get(f"/api/v2/projekte/{pid}", headers=h.auth(h.USER_A)).json()

    assert projekt["soll_stunden_gesamt"] == 30.0
    assert projekt["soll_kosten"] == 10 * 100 + 20 * 120  # 3400


def test_pdf_ist_valides_dokument():
    """erstelle_angebots_pdf liefert ein nicht-leeres, valides PDF (mit Umlauten)."""
    pdf = erstelle_angebots_pdf(
        angebot_nr="A-0001",
        firmenname="Demo Agentur GmbH",
        kunde="Bäckerei Müller",
        projekt_name="Onlineshop",
        positionen=[
            {"nr": 1, "beschreibung": "Konzeption & Setup", "rolle": "Projektleiter",
             "stunden": 10, "stundensatz": 120, "summe": 1200},
        ],
    )
    assert pdf[:5] == b"%PDF-"   # PDF-Magic-Bytes
    assert len(pdf) > 1000       # kein leeres Dokument
