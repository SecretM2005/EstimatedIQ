"""
BBSR Baupreisindex – Kalibrierungsgrundlage für EstimateIQ Bau.

Liefert regionalisierte Baupreisindizes pro Bundesland.
Basis: Bundesdurchschnitt = 100.0

Quelle: Statistisches Bundesamt / BBSR, Stand 2024.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BBSR_INDEX_PFAD = Path("data/bbsr_index.json")

# Baupreisindizes 2024, Basis Bundesdurchschnitt = 100.0
# Quelle: Destatis, Fachserie 17, Reihe 4 / BBSR-Auswertung
BBSR_INDEX_2024: dict[str, float] = {
    "Bayern":                    118.5,
    "Baden-Württemberg":         115.2,
    "Hamburg":                   113.8,
    "Hessen":                    111.4,
    "Nordrhein-Westfalen":       108.2,
    "Bremen":                    106.1,
    "Berlin":                    105.8,
    "Schleswig-Holstein":        102.3,
    "Rheinland-Pfalz":           101.7,
    "Niedersachsen":             100.5,
    "Saarland":                   98.6,
    "Brandenburg":                96.4,
    "Sachsen":                    92.1,
    "Thüringen":                  89.8,
    "Sachsen-Anhalt":             88.5,
    "Mecklenburg-Vorpommern":     87.2,
    # Österreich / Schweiz (Pauschalwerte)
    "AT":                        108.0,
    "CH":                        168.0,
    "default":                   100.0,
}

# Für frühere Jahre: leichte Anpassung basierend auf durchschnittlicher Preissteigerung
JAHRES_FAKTOR: dict[int, float] = {
    2020: 0.87,
    2021: 0.91,
    2022: 0.96,
    2023: 0.99,
    2024: 1.00,
}

# Bundesland-Normalisierung: Aliase und Kurzformen
BUNDESLAND_ALIASE: dict[str, str] = {
    "BY": "Bayern",
    "BW": "Baden-Württemberg",
    "HH": "Hamburg",
    "HE": "Hessen",
    "NW": "Nordrhein-Westfalen",
    "HB": "Bremen",
    "BE": "Berlin",
    "SH": "Schleswig-Holstein",
    "RP": "Rheinland-Pfalz",
    "NI": "Niedersachsen",
    "SL": "Saarland",
    "BB": "Brandenburg",
    "SN": "Sachsen",
    "TH": "Thüringen",
    "ST": "Sachsen-Anhalt",
    "MV": "Mecklenburg-Vorpommern",
    "mecklenburg-vorpommern": "Mecklenburg-Vorpommern",
    "mecklenburg vorpommern": "Mecklenburg-Vorpommern",
    "north rhine-westphalia": "Nordrhein-Westfalen",
    "north rhine westphalia": "Nordrhein-Westfalen",
    "rhineland-palatinate": "Rheinland-Pfalz",
    "lower saxony": "Niedersachsen",
    "saxony": "Sachsen",
    "saxony-anhalt": "Sachsen-Anhalt",
    "thuringia": "Thüringen",
    "hesse": "Hessen",
    "hamburg": "Hamburg",
    "bremen": "Bremen",
    "berlin": "Berlin",
    "saarland": "Saarland",
    "bavaria": "Bayern",
    "bavaria (germany)": "Bayern",
    "hamburg (city)": "Hamburg",
    "brandenbourg": "Brandenburg",
    "österreich": "AT",
    "austria": "AT",
    "schweiz": "CH",
    "switzerland": "CH",
}


def _normalisiere_bundesland(bundesland: str | None) -> str:
    """Normalisiert Bundesland-Namen auf den kanonischen deutschen Namen."""
    if not bundesland:
        return "default"
    bl = bundesland.strip()
    # Direkte Übereinstimmung
    if bl in BBSR_INDEX_2024:
        return bl
    # Alias-Tabelle (case-insensitive)
    alias = BUNDESLAND_ALIASE.get(bl) or BUNDESLAND_ALIASE.get(bl.lower())
    if alias:
        return alias
    # Teilstring-Suche
    bl_lower = bl.lower()
    for kanon in BBSR_INDEX_2024:
        if kanon.lower() in bl_lower or bl_lower in kanon.lower():
            return kanon
    return "default"


def get_bbsr_index(bundesland: str | None, jahr: int | None = None) -> float:
    """
    Gibt den Baupreisindex für ein Bundesland zurück.

    Args:
        bundesland: Bundeslandname (deutsch, englisch oder Kürzel)
        jahr:       Baujahr (2020–2024); None → aktuellster Wert

    Returns:
        float – Index normalisiert auf Bundesdurchschnitt=100.0
    """
    bl_kanon = _normalisiere_bundesland(bundesland)
    basis    = BBSR_INDEX_2024.get(bl_kanon, BBSR_INDEX_2024["default"])

    if jahr and jahr in JAHRES_FAKTOR:
        return round(basis * JAHRES_FAKTOR[jahr], 2)
    return basis


def speichere_bbsr_index(pfad: Path = BBSR_INDEX_PFAD) -> None:
    """Persistiert den BBSR-Index als JSON-Datei."""
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with pfad.open("w", encoding="utf-8") as f:
        json.dump(BBSR_INDEX_2024, f, ensure_ascii=False, indent=2)
    logger.info("[BBSR] Index gespeichert: %s", pfad)


if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    speichere_bbsr_index()

    print("\n═" * 42)
    print("  BBSR Baupreisindex 2024 (Basis=100)")
    print("═" * 42)
    for bl, idx in sorted(BBSR_INDEX_2024.items(), key=lambda x: -x[1]):
        if bl != "default":
            print(f"  {bl:<30} {idx:>6.1f}")
    print(f"\n  Bundesdurchschnitt:            100.0")
    print("═" * 42 + "\n")
