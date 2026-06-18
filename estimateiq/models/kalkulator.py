"""
Regelbasierter Kalkulator: Leistungspositionen → Kosten + Laufzeit.

Kernformel:
  lohn     = menge × h_pro_einheit × stundensatz
  material = lohn  × material_faktor
  netto    = lohn + material
  brutto   = netto × (1 + summe_aufschlaege)   [31 %]
  dauer    = gesamt_stunden / 8                 [Tage]

Verwendung:
  from estimateiq.models.kalkulator import kalkuliere, kalkuliere_aus_text

  ergebnis = kalkuliere_aus_text(
      "Badezimmer 12m² Fliesen Boden und Wand, Dusche, WC",
      region="DE-BY"
  )
"""

from __future__ import annotations

from estimateiq.data.zeitwerte import ZEITWERTE, EINHEIT_LABEL
from estimateiq.data.stundensaetze import (
    STUNDENSAETZE, AUFSCHLAEGE, _AUFSCHLAG_GESAMT,
    get_stundensatz, bundesland_zu_region,
)
from estimateiq.models.nlp_extractor import extract_positionen


def kalkuliere(
    positionen: list[dict],
    region: str = "DE-sonstige",
) -> dict:
    """
    Berechnet Kosten und Laufzeit für eine Liste von Leistungspositionen.

    Args:
        positionen: [{"position": str, "menge": float}, ...]
        region:     Regionsschlüssel (z. B. "DE-BY", "AT", "CH")

    Returns:
        dict mit aufgeschlüsselten Kosten, Stunden und Laufzeit.
    """
    ergebnis_positionen = []
    gesamt_stunden  = 0.0
    gesamt_lohn     = 0.0
    gesamt_material = 0.0

    for pos in positionen:
        pos_name = pos["position"]
        menge    = float(pos.get("menge", 0))

        zw = ZEITWERTE.get(pos_name)
        if zw is None:
            continue

        h_pro_einheit, einheit, mat_faktor, gewerk = zw
        stundensatz = get_stundensatz(gewerk, region)

        stunden  = menge * h_pro_einheit
        lohn     = stunden * stundensatz
        material = lohn * mat_faktor
        gesamt_pos = lohn + material

        ergebnis_positionen.append({
            "position":    pos_name,
            "menge":       round(menge, 1),
            "einheit":     EINHEIT_LABEL.get(einheit, einheit),
            "gewerk":      gewerk,
            "stunden":     round(stunden, 1),
            "stundensatz": stundensatz,
            "lohn":        round(lohn, 2),
            "material":    round(material, 2),
            "gesamt":      round(gesamt_pos, 2),
        })

        gesamt_stunden  += stunden
        gesamt_lohn     += lohn
        gesamt_material += material

    netto     = gesamt_lohn + gesamt_material
    aufschlag = netto * _AUFSCHLAG_GESAMT
    gesamt    = netto + aufschlag

    dauer_netto = gesamt_stunden / 8.0

    return {
        "positionen":      ergebnis_positionen,
        "region":          region,
        "gesamt_stunden":  round(gesamt_stunden, 1),
        "dauer_tage":      round(dauer_netto, 1),
        "dauer_min_tage":  round(dauer_netto * 0.80, 1),
        "dauer_max_tage":  round(dauer_netto * 1.40, 1),
        "lohnkosten":      round(gesamt_lohn, 2),
        "materialkosten":  round(gesamt_material, 2),
        "aufschlaege":     round(aufschlag, 2),
        "kosten_erwartet": round(gesamt, 2),
        "kosten_min":      round(gesamt * 0.85, 2),
        "kosten_max":      round(gesamt * 1.25, 2),
    }


def kalkuliere_aus_text(
    beschreibung: str,
    region: str = "DE-sonstige",
    mit_bert: bool = False,
) -> dict:
    """
    End-to-End: Freitext → Kosten + Laufzeit.

    Args:
        beschreibung: Projektbeschreibung
        region:       Regionsschlüssel
        mit_bert:     BERT-Extraktion aktivieren

    Returns:
        Kalkulations-dict (gleiche Struktur wie kalkuliere())
        + "erkannte_positionen_roh": raw NLP output
    """
    positionen = extract_positionen(beschreibung, mit_bert=mit_bert)
    ergebnis   = kalkuliere(positionen, region=region)
    ergebnis["erkannte_positionen_roh"] = positionen
    return ergebnis


def kalkuliere_aus_text_mit_ort(
    beschreibung: str,
    bundesland: str = "",
    land: str = "DE",
    mit_bert: bool = False,
) -> dict:
    """Wie kalkuliere_aus_text, aber mit Bundesland statt Regionsschlüssel."""
    region = bundesland_zu_region(bundesland, land)
    return kalkuliere_aus_text(beschreibung, region=region, mit_bert=mit_bert)
