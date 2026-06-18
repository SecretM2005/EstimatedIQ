"""
NLP-Extraktor: Leistungspositionen aus Freitext erkennen.

Primärer Ansatz: regelbasiertes Keyword-Matching + Proximity-Score.
Optionaler BERT-Modus: semantisches Scoring via [CLS]-Embeddings (Stub).

Beispiel:
  extract_positionen("Badezimmer 12m² Fliesen Boden und Wand, Dusche, WC")
  → [{"position": "fliesen_boden", "menge": 12.0},
     {"position": "fliesen_wand",  "menge": 18.0},
     {"position": "dusche_komplett", "menge": 1.0},
     {"position": "wc_komplett",     "menge": 1.0}]
"""

from __future__ import annotations

import re

from estimateiq.data.zeitwerte import ZEITWERTE

# ── Keyword-Mapping ───────────────────────────────────────────────────────────
# Format: position_name → [trigger_phrases] (lowercase, teilweise regex-frei)

KEYWORDS: dict[str, list[str]] = {

    # Maler
    "maler_wand_innen": [
        "wand streichen", "wände streichen", "streichen wand", "innenanstrich",
        "wandfarbe", "malerarbeiten wand", "wand anstrich", "anstrich wand",
        "wände und decken streichen", "wohnzimmer streichen",
    ],
    "maler_decke": [
        "decke streichen", "decken streichen", "deckenfarbe",
        "anstrich decke", "decke anstrich", "malerarbeiten decke",
    ],
    "maler_fassade": [
        "fassade streichen", "fassadenfarbe", "außenanstrich", "aussenanstrich",
        "fassade anstrich", "fassadenanstrich",
    ],
    "tapezieren_wand": [
        "tapezieren", "tapete", "tapeten", "vliestapete", "raufasertapete",
    ],
    "spachteln_glaetten": [
        "spachteln", "glätten", "glaetten", "glattspachtel",
        "verspachteln", "spachtel",
    ],

    # Fliesen
    "fliesen_boden": [
        "bodenfliesen", "fliesen boden", "boden fliesen",
        "bodenplatten", "fliesen legen boden", "bodenbelag fliesen",
    ],
    "fliesen_wand": [
        "wandfliesen", "fliesen wand", "wand fliesen",
        "kacheln wand", "wandkacheln", "wandbelag fliesen",
    ],
    "fliesen_duschbereich": [
        "duschfliesen", "fliesen dusche", "duschbereich fliesen",
        "fliesen duschbereich",
    ],
    "estrich_schwimmend": [
        "estrich", "schwimmender estrich", "zementestrich", "heizestrich",
    ],

    # Sanitär
    "wc_komplett": [
        "wc", "toilette", "klo", "wc anlage", "wc einbauen",
        "toilette einbauen", "wc-anlage",
    ],
    "waschbecken_komplett": [
        "waschbecken", "waschtisch", "handwaschbecken",
        "waschbecken einbauen", "waschtisch einbauen",
    ],
    "dusche_komplett": [
        "dusche", "duschkabine", "duschanlage", "duschbereich",
        "dusche komplett", "neue dusche",
    ],
    "badewanne_komplett": [
        "badewanne", "wanne einbauen", "badewanne einbauen",
        "neue badewanne",
    ],
    "heizkoerper_tauschen": [
        "heizkörper", "heizkoerper", "heizkörper tauschen",
        "thermostat ventil", "thermostatventil",
    ],
    "fussbodenheizung": [
        "fußbodenheizung", "fussbodenheizung", "fbh", "bodenheizung",
        "flächenheizung", "flaechenheizung",
    ],
    "waermepumpe_luft": [
        "wärmepumpe", "waermepumpe", "wp luft", "luftwasserwärmepumpe",
        "luftquelle", "luft-wasser-wärmepumpe", "wärmepumpe luft",
        "wärmepumpe luftquelle",
    ],
    "gasheizung_komplett": [
        "gasheizung", "gas heizung", "gasbrennwert", "brennwertkessel",
        "gasbrennwertkessel", "heizungsanlage gas", "gas-brennwertgerät",
        "neue heizung gas",
    ],

    # Elektro
    "steckdose_neu": [
        "steckdose", "steckdosen einbauen", "steckdosen neu",
    ],
    "lichtschalter_neu": [
        "lichtschalter", "schalter neu", "dimmer einbauen",
    ],
    "unterverteilung_neu": [
        "unterverteilung", "sicherungskasten", "verteilung erneuern",
        "zählerschrank", "hauptverteilung",
    ],
    "elektro_grundinstall_m2": [
        "elektroinstallation", "elektro installation", "elektroleitungen",
        "elektro grundinstallation", "elektrosanierung", "elektro sanierung",
        "strom legen", "elektroinstallation komplett",
    ],
    "aussenbeleuchtung": [
        "außenbeleuchtung", "aussenbeleuchtung", "gartenbeleuchtung",
        "fassadenbeleuchtung",
    ],

    # Trockenbau
    "trockenbau_wand": [
        "trockenbau wand", "leichtbauwand", "gipskarton wand",
        "gk wand", "ständerwand", "trockenbau wände",
        "trennwand trockenbau",
    ],
    "trockenbau_decke": [
        "trockenbau decke", "abgehängte decke", "gipskarton decke",
        "abhängedecke", "deckenabhängung", "abgehängte decken",
        "trockenbau decken",
    ],
    "daemmung_dach_innen": [
        "dachdämmung", "daemmung dach", "dach dämmen",
        "zwischensparrendämmung", "zwischensparren",
        "dachdämmung innen", "dachausbau dämmung",
    ],
    "daemmung_fassade_wdvs": [
        "wdvs", "fassadendämmung", "außendämmung", "ausendämmung",
        "wärmedämmverbundsystem", "styropor fassade",
        "fassade dämmen", "wärmedämmung fassade",
    ],

    # Hochbau
    "mauerwerk_aussen": [
        "mauerwerk", "ziegel mauern", "mauersteine", "außenmauerwerk",
    ],
    "beton_decke": [
        "betondecke", "stahlbeton decke", "decke betonieren",
        "stahlbetondecke",
    ],
    "fundament": [
        "fundament", "bodenplatte", "streifenfundament",
        "betonbodenplatte",
    ],
    "dachstuhl_holz": [
        "dachstuhl", "dach holz", "holzdachstuhl", "dachwerk",
        "zimmerei dach", "dachstuhl erneuern",
    ],

    # Boden
    "parkett_verlegen": [
        "parkett", "parkettboden", "dielung", "parkett verlegen",
        "holzboden", "massivparkett",
    ],
    "laminat_verlegen": [
        "laminat", "laminatboden", "laminat verlegen",
    ],
    "teppich_verlegen": [
        "teppich", "teppichboden", "teppich verlegen",
        "bodenbelag teppich",
    ],
    "vinyl_kleben": [
        "vinyl", "vinylboden", "lvt", "pvc boden", "klebebelag",
        "designboden",
    ],
}

# ── Regex-Muster für Mengenextraktion ─────────────────────────────────────────

_MENGEN_MUSTER: list[tuple[str, str]] = [
    (r"(\d[\d.]*(?:[,.]\d+)?)\s*m\s*[²2]",            "m²"),
    (r"(\d[\d.]*(?:[,.]\d+)?)\s*qm",                   "m²"),
    (r"(\d[\d.]*(?:[,.]\d+)?)\s*Quadratmeter",         "m²"),
    (r"(\d[\d.]*(?:[,.]\d+)?)\s*m\s*[³3]",            "m³"),
    (r"(\d+)\s*(?:Stück|Stk\.?|St\.)\b",              "St"),
    (r"(\d+)\s*x\s",                                   "St"),
]


def _parse_zahl(s: str) -> float:
    """Parst deutsche und englische Zahlenformate."""
    s = s.strip()
    if "," in s:
        return float(s.replace(".", "").replace(",", "."))
    parts = s.split(".")
    if len(parts) == 2 and len(parts[1]) == 3:
        return float(s.replace(".", ""))
    return float(s)


def _extrahiere_mengen(text: str, einheit: str) -> list[tuple[int, float]]:
    """
    Gibt Liste von (text_position, wert) für alle Mengen der gesuchten Einheit zurück.
    """
    ergebnis: list[tuple[int, float]] = []
    for pat, typ in _MENGEN_MUSTER:
        if typ != einheit:
            continue
        for m in re.finditer(pat, text, re.IGNORECASE):
            try:
                wert = _parse_zahl(m.group(1))
                if 0 < wert < 1_000_000:
                    ergebnis.append((m.start(), wert))
            except (ValueError, IndexError):
                pass
    return ergebnis


def _naechste_menge(pos_name: str, text: str,
                    mengen: list[tuple[int, float]]) -> float | None:
    """
    Findet die Mengenangabe, die am nächsten zu einem der Trigger-Keywords liegt.
    """
    if not mengen:
        return None
    kws = KEYWORDS.get(pos_name, [])
    best_dist = float("inf")
    best_val  = None
    for kw in kws:
        idx = text.find(kw)
        if idx == -1:
            continue
        for menge_idx, wert in mengen:
            dist = abs(menge_idx - idx)
            if dist < best_dist:
                best_dist = dist
                best_val  = wert
    if best_val is None and mengen:
        best_val = mengen[0][1]
    return best_val


def _extrahiere_stueckzahl(pos_name: str, text: str) -> float:
    """
    Extrahiert explizite Stückzahlen aus dem Text (z. B. "3 WC", "2x Dusche").
    Fallback: 1.
    """
    kws = KEYWORDS.get(pos_name, [])
    for kw in kws:
        kw_idx = text.find(kw)
        if kw_idx == -1:
            continue
        vorher = text[max(0, kw_idx - 8): kw_idx]
        m = re.search(r"(\d+)\s*(?:x\s*)?$", vorher)
        if m:
            return float(m.group(1))
        nachher = text[kw_idx: kw_idx + len(kw) + 6]
        m = re.search(r"(?:^|\s)(\d+)", nachher)
        if m:
            return float(m.group(1))
    return 1.0


def _sonderregeln(text: str, result: dict[str, float],
                  mengen_m2: list[tuple[int, float]]) -> None:
    """Nachverarbeitung: spezielle Ableitungsregeln."""
    # Fliesen Boden + Wand mit gleicher Fläche → Wand = 1.5 × Boden
    if "fliesen_boden" in result and "fliesen_wand" in result:
        if abs(result["fliesen_boden"] - result["fliesen_wand"]) < 1.0:
            result["fliesen_wand"] = round(result["fliesen_boden"] * 1.5, 0)

    # "Fliesen Boden und Wand" / "fliesen…wand" ohne direkten Wand-Treffer
    # Typisch: "12m² Fliesen Boden und Wand" → wand = boden × 1.5
    if "fliesen_boden" in result and "fliesen_wand" not in result:
        if re.search(r"fliesen\b.{0,25}\bwand\b|\bwand\b.{0,25}fliesen\b", text):
            result["fliesen_wand"] = round(result["fliesen_boden"] * 1.5, 0)

    # Fliesen ohne Richtung (generisch "fliesen") → Boden-Treffer
    if "fliesen_boden" not in result and "fliesen_wand" not in result:
        generic_kws = ["fliesen", "kacheln", "fliesen verlegen"]
        if any(kw in text for kw in generic_kws) and mengen_m2:
            m2 = mengen_m2[0][1]
            result["fliesen_boden"] = m2
            result["fliesen_wand"]  = round(m2 * 1.5, 0)

    # Duschbereich impliziert auch Wand-Fliesen wenn noch keine vorhanden
    if "fliesen_duschbereich" in result and "fliesen_wand" not in result:
        result["fliesen_wand"] = result["fliesen_duschbereich"]


def extract_positionen(beschreibung: str,
                       mit_bert: bool = False) -> list[dict]:
    """
    Extrahiert Leistungspositionen und Mengen aus einem Freitext.

    Args:
        beschreibung: Projektbeschreibung (deutsch, Freitext)
        mit_bert:     Aktiviert semantisches BERT-Scoring (noch Stub)

    Returns:
        Liste von {"position": str, "menge": float}
    """
    text = beschreibung.lower()

    mengen_m2 = _extrahiere_mengen(text, "m²")
    mengen_st = _extrahiere_mengen(text, "St")
    mengen_m3 = _extrahiere_mengen(text, "m³")

    # Score jede Position nach Keyword-Treffern
    scores: dict[str, int] = {}
    for pos, kws in KEYWORDS.items():
        s = sum(1 for kw in kws if kw in text)
        if s > 0:
            scores[pos] = s

    if not scores:
        return []

    # Menge je Position bestimmen
    result: dict[str, float] = {}
    for pos in scores:
        zw = ZEITWERTE.get(pos)
        if zw is None:
            continue
        einheit = zw[1]

        if einheit == "m²":
            m = _naechste_menge(pos, text, mengen_m2)
            if m and m > 0:
                result[pos] = m

        elif einheit == "St":
            result[pos] = _extrahiere_stueckzahl(pos, text)

        elif einheit == "m³":
            if mengen_m3:
                result[pos] = mengen_m3[0][1]
            elif mengen_m2:
                result[pos] = mengen_m2[0][1] * 0.3  # Näherung: Tiefe ~0.3m

    _sonderregeln(text, result, mengen_m2)

    if mit_bert:
        _bert_korrekturen(text, result, scores)

    positionen = [
        {"position": p, "menge": round(m, 1)}
        for p, m in result.items()
        if m and m > 0
    ]
    positionen.sort(key=lambda x: -scores.get(x["position"], 0))
    return positionen


def _bert_korrekturen(text: str, result: dict[str, float],
                      scores: dict[str, int]) -> None:
    """
    BERT-basiertes Scoring – erhöht Konfidenz per Kosinus-Ähnlichkeit.
    Stub: aktuell keine Anpassungen.
    TODO: Precompute position embeddings, compute input embedding, adjust scores.
    """
    pass
