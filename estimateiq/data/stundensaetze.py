"""
Stundensätze nach Gewerk und Region (Kostenindex 2026, Quelle: handwerk.cloud).

Regionsschlüssel:
  DE-BY  Bayern
  DE-BW  Baden-Württemberg
  DE-HH  Hamburg
  DE-HE  Hessen
  DE-NW  Nordrhein-Westfalen
  DE-BE  Berlin
  DE-sonstige  alle anderen Bundesländer
  AT     Österreich (gesamt)
  CH     Schweiz (gesamt)
"""

from __future__ import annotations

STUNDENSAETZE: dict[str, dict[str, int]] = {
    "Maler": {
        "DE-BY": 68, "DE-BW": 65, "DE-HH": 63,
        "DE-HE": 62, "DE-NW": 60, "DE-BE": 58,
        "DE-sonstige": 55, "AT": 55, "CH": 95,
    },
    "Fliesen": {
        "DE-BY": 72, "DE-BW": 70, "DE-HH": 68,
        "DE-HE": 67, "DE-NW": 64, "DE-BE": 62,
        "DE-sonstige": 60, "AT": 60, "CH": 100,
    },
    "Sanitär": {
        "DE-BY": 88, "DE-BW": 85, "DE-HH": 83,
        "DE-HE": 82, "DE-NW": 78, "DE-BE": 75,
        "DE-sonstige": 72, "AT": 72, "CH": 125,
    },
    "Elektro": {
        "DE-BY": 82, "DE-BW": 80, "DE-HH": 78,
        "DE-HE": 77, "DE-NW": 74, "DE-BE": 72,
        "DE-sonstige": 68, "AT": 68, "CH": 115,
    },
    "Trockenbau": {
        "DE-BY": 65, "DE-BW": 63, "DE-HH": 62,
        "DE-HE": 61, "DE-NW": 60, "DE-BE": 59,
        "DE-sonstige": 58, "AT": 55, "CH": 92,
    },
    "Hochbau": {
        "DE-BY": 75, "DE-BW": 72, "DE-HH": 70,
        "DE-HE": 69, "DE-NW": 67, "DE-BE": 66,
        "DE-sonstige": 65, "AT": 62, "CH": 110,
    },
    "Boden": {
        "DE-BY": 62, "DE-BW": 60, "DE-HH": 59,
        "DE-sonstige": 55, "AT": 52, "CH": 88,
    },
}

AUFSCHLAEGE: dict[str, float] = {
    "overhead":               0.15,
    "gewinn":                 0.08,
    "wagnis":                 0.03,
    "baustellengemeinkosten": 0.05,
}

_AUFSCHLAG_GESAMT: float = sum(AUFSCHLAEGE.values())  # 0.31

# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

_BUNDESLAND_REGION: dict[str, str] = {
    "Bayern":                  "DE-BY",
    "Baden-Württemberg":       "DE-BW",
    "Hamburg":                 "DE-HH",
    "Hessen":                  "DE-HE",
    "Nordrhein-Westfalen":     "DE-NW",
    "Berlin":                  "DE-BE",
    "Schleswig-Holstein":      "DE-sonstige",
    "Niedersachsen":           "DE-sonstige",
    "Bremen":                  "DE-sonstige",
    "Sachsen":                 "DE-sonstige",
    "Sachsen-Anhalt":          "DE-sonstige",
    "Thüringen":               "DE-sonstige",
    "Brandenburg":             "DE-sonstige",
    "Mecklenburg-Vorpommern":  "DE-sonstige",
    "Rheinland-Pfalz":         "DE-sonstige",
    "Saarland":                "DE-sonstige",
}


def bundesland_zu_region(bundesland: str, land: str = "DE") -> str:
    """Wandelt Bundesland-Name in Regionsschlüssel um."""
    land = land.upper()
    if land == "AT":
        return "AT"
    if land == "CH":
        return "CH"
    return _BUNDESLAND_REGION.get(bundesland, "DE-sonstige")


def get_stundensatz(gewerk: str, region: str) -> int:
    """
    Gibt den Stundensatz für ein Gewerk in einer Region zurück.
    Fällt auf DE-sonstige zurück wenn Region unbekannt.
    """
    tarife = STUNDENSAETZE.get(gewerk)
    if tarife is None:
        return 60
    if region in tarife:
        return tarife[region]
    land = region.split("-")[0] if "-" in region else region
    if land in tarife:
        return tarife[land]
    return tarife.get("DE-sonstige", 60)
