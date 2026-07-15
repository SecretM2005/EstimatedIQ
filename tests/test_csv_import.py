"""
PRIORITÄT 2 – CSV/Excel-Import.

parse_upload ist reine Parselogik (ohne DB/Embeddings) und lässt sich direkt
als Unit-Test prüfen. Der Encoding-Fall ist ein bewusster Regressionsschutz:
deutsche Excel-Exporte (ISO-8859-1/cp1252) müssen funktionieren.
"""

from estimateiq.angebot.csv_import import parse_upload

CSV_PROJEKT = (
    "Projekt,Beschreibung,Rolle,Soll_Stunden,Stundensatz\n"
    "CRM-2024,Frontend Entwicklung,Senior Dev,40,120\n"
    "CRM-2024,Backend API,Backend Dev,24,110\n"
    "Portal,UX Konzept,Designer,12,95\n"
)


def test_import_gruppiert_nach_projekt():
    """Mit Projekt-Spalte werden Positionen korrekt nach Projekt gruppiert."""
    parsed = parse_upload(CSV_PROJEKT.encode("utf-8"), "test.csv")

    assert parsed["hat_projekt_spalte"] is True
    assert parsed["stats"]["akzeptiert"] == 3
    projekte = {p["name"]: p for p in parsed["projekte"]}
    assert set(projekte) == {"CRM-2024", "Portal"}
    assert len(projekte["CRM-2024"]["positionen"]) == 2
    assert projekte["CRM-2024"]["positionen"][0]["soll_stunden"] == 40.0


def test_import_encoding_fallback_latin1():
    """
    Regressionsschutz: eine ISO-8859-1-kodierte CSV mit Umlauten (typischer
    deutscher Excel-Export) muss importierbar sein und die Umlaute erhalten.
    """
    csv_umlaut = (
        "Beschreibung,Soll_Stunden\n"
        "Qualitätssicherung Müller,16\n"
    )
    parsed = parse_upload(csv_umlaut.encode("latin-1"), "umlaut.csv")

    assert parsed["stats"]["akzeptiert"] == 1
    pos = parsed["einzelpositionen"][0]
    assert "Qualitätssicherung Müller" in pos["beschreibung_text"]


def test_import_fehlende_pflichtspalten_gibt_fehler_kein_crash():
    """Fehlt eine Pflichtspalte (Beschreibung/Soll), kommt ein sauberer Fehler zurück."""
    csv_kaputt = "Irgendwas,Andere\nfoo,bar\n"
    parsed = parse_upload(csv_kaputt.encode("utf-8"), "kaputt.csv")

    assert parsed["stats"]["akzeptiert"] == 0
    assert parsed["projekte"] == []
    assert parsed["einzelpositionen"] == []
    assert len(parsed["fehler"]) > 0  # es gibt eine erklärende Fehlermeldung
