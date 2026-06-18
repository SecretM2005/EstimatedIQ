"""
Generiert synthetische mittlere und große Bauprojekte (50.000–8.000.000 €) für EstimateIQ Bau.

Motivation: TED-Ausschreibungen enthalten kaum explizite Flächenangaben in Textform.
Das Kostenmodell kann deshalb Großprojekte (Schulen, Wohnanlagen, Büros) nicht korrekt
schätzen, weil es nie gelernt hat: 2500 m² Generalsanierung = 1,5 M€.
Diese synthetischen Daten ergänzen den Trainingsbestand gezielt mit expliziten m²-/WE-
Angaben im Bereich 50 k–8 M€.

Output: data/raw_notices_bau_large.jsonl (kompatibel mit preprocess_bau.py Glob-Muster)

Verwendung:
    python -m estimateiq.data.generate_large_bau
    python -m estimateiq.data.preprocess_bau
    python train_bau.py
"""

import json
import logging
import random
import uuid
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

AUSGABE_PFAD = Path("data/raw_notices_bau_large.jsonl")

BUDGET_MIN_EUR = 50_000
BUDGET_MAX_EUR = 8_000_000

STAEDTE: list[dict] = [
    {"ort": "München",    "land": "DE", "bundesland": "Bayern",              "bbsr": 118.5},
    {"ort": "Hamburg",    "land": "DE", "bundesland": "Hamburg",             "bbsr": 110.0},
    {"ort": "Berlin",     "land": "DE", "bundesland": "Berlin",              "bbsr": 105.8},
    {"ort": "Stuttgart",  "land": "DE", "bundesland": "Baden-Württemberg",   "bbsr": 108.0},
    {"ort": "Frankfurt",  "land": "DE", "bundesland": "Hessen",              "bbsr": 105.0},
    {"ort": "Köln",       "land": "DE", "bundesland": "Nordrhein-Westfalen", "bbsr": 101.2},
    {"ort": "Dortmund",   "land": "DE", "bundesland": "Nordrhein-Westfalen", "bbsr": 101.2},
    {"ort": "Hannover",   "land": "DE", "bundesland": "Niedersachsen",       "bbsr":  98.0},
    {"ort": "Leipzig",    "land": "DE", "bundesland": "Sachsen",             "bbsr":  92.1},
    {"ort": "Dresden",    "land": "DE", "bundesland": "Sachsen",             "bbsr":  92.1},
    {"ort": "Nürnberg",   "land": "DE", "bundesland": "Bayern",              "bbsr": 118.5},
    {"ort": "Bremen",     "land": "DE", "bundesland": "Bremen",              "bbsr": 102.0},
    {"ort": "Erfurt",     "land": "DE", "bundesland": "Thüringen",           "bbsr":  91.5},
    {"ort": "Mannheim",   "land": "DE", "bundesland": "Baden-Württemberg",   "bbsr": 106.0},
    {"ort": "Augsburg",   "land": "DE", "bundesland": "Bayern",              "bbsr": 116.0},
    {"ort": "Wien",       "land": "AT", "bundesland": "Wien",                "bbsr": 108.0},
    {"ort": "Graz",       "land": "AT", "bundesland": "Steiermark",          "bbsr": 104.0},
    {"ort": "Linz",       "land": "AT", "bundesland": "Oberösterreich",      "bbsr": 102.0},
    {"ort": "Zürich",     "land": "CH", "bundesland": "Zürich",              "bbsr": 125.0},
    {"ort": "Basel",      "land": "CH", "bundesland": "Basel-Stadt",         "bbsr": 122.0},
]

QUALITAETEN = [
    ("einfach",    0.75),
    ("standard",   1.00),
    ("hochwertig", 1.40),
]

# Projektvorlagen – CPV-Codes laut preprocess_bau.py CPV_GEWERK-Mapping:
#   45214200 → Prefix "452140" → "Schulen"
#   45211000 → Prefix "452110" → "Wohngebäude"
#   45213100 → Prefix "452130" → "Gewerbegebäude"
#   45331000 → Prefix "453310" → "Heizung/Lüftung/Klima"
#   45310000 → Prefix "453100" → "Elektro"
#   45453000 → Prefix "454530" → kein direkter Treffer → fallback "Ausbau allgemein"
#   45210000 → Prefix "452100" → "Hochbau/Neubau"
#
# Beschreibungen MÜSSEN explizit m² oder WE enthalten damit _extrahiere_flaeche /
# _extrahiere_einheiten im Modell die Features befüllen können.

PROJEKTVORLAGEN: list[dict] = [
    # ── Generalsanierung Grundschule (klein, 800–2500 m²) ─────────────────────
    {
        "cpv": "45214200",
        "titel": [
            "Generalsanierung Grundschule {ort} {flaeche}m² BGF",
            "Komplettsanierung Schulgebäude {flaeche}m² in {ort}",
            "Vollsanierung Grundschule {ort} {flaeche}m² inkl. Haustechnik",
        ],
        "beschreibung": [
            "Generalsanierung Grundschule in {ort}: {flaeche}m² Bruttogrundfläche. "
            "Leistungsumfang: Fassade WDVS, neue Fenster (Uw ≤ 1,0 W/m²K), "
            "Heizungsanlage Wärmepumpe, Elektro komplett, Innenausbau "
            "{qualitaet}e Ausführung. Laufender Schulbetrieb in Etappen.",
            "Komplettsanierung Schulgebäude in {ort}: {flaeche}m² BGF, Baujahr ca. "
            "1970. Kernsanierung inklusive energetischer Hülle (WDVS 14 cm, "
            "Fenster 3-fach), TGA-Erneuerung und Brandschutz. Qualität: {qualitaet}.",
            "Vollsanierung Grundschule {ort}: {flaeche}m² Nutzfläche. Maßnahmen: "
            "Dach, Fassade, Fenster, Heizung Gas-Brennwert, Elektrosanierung, "
            "Innenausbau Klassen- und Nebenräume. Qualitätsstufe: {qualitaet}.",
        ],
        "basis_eur_m2": 650.0,
        "flaeche_range": (800, 2500),
        "dauer_tage_pro_100m2": 12.0,
        "dauer_min": 180,
    },
    # ── Generalsanierung Gymnasium / Berufsschule (groß, 2000–7000 m²) ────────
    {
        "cpv": "45214200",
        "titel": [
            "Generalsanierung Gymnasium {ort} {flaeche}m² BGF",
            "Kernsanierung Berufsschule {flaeche}m² in {ort}",
            "Vollsanierung Schulkomplex {ort} {flaeche}m² Bruttofläche",
        ],
        "beschreibung": [
            "Generalsanierung Gymnasium in {ort}: {flaeche}m² Bruttogeschossfläche. "
            "Umfasst energetische Hüllsanierung (WDVS, Dach, Fenster), "
            "komplette TGA-Erneuerung (Heizung, Lüftung, Elektro, MSR), "
            "Innenausbau {qualitaet}e Qualität, Barrierefreiheit.",
            "Kernsanierung Berufsschule {ort}: {flaeche}m² BGF, mehrere Gebäudeteile. "
            "Tragwerk erhalten, Gebäudehülle und TGA vollständig erneuern, "
            "Brandschutzkonzept, {qualitaet}e Ausstattung Lehrräume und Werkstätten.",
            "Komplettsanierung Schulkomplex {ort}: {flaeche}m² BGF (3 Baukörper). "
            "Generalunternehmer gesucht: Rohbau ergänzen, Fassade WDVS, TGA, "
            "Ausbau {qualitaet}e Qualitätsstufe. Energetisches Ziel: EH 70.",
        ],
        "basis_eur_m2": 750.0,
        "flaeche_range": (2000, 7000),
        "dauer_tage_pro_100m2": 8.0,
        "dauer_min": 360,
    },
    # ── Neubau Wohnanlage / Mehrfamilienhaus (8–50 WE) ────────────────────────
    {
        "cpv": "45211000",
        "titel": [
            "Neubau Wohnanlage {n_einh} Wohneinheiten in {ort}",
            "Errichtung Mehrfamilienhaus {n_einh} WE {qualitaet}e Ausstattung",
            "Neubau Wohngebäude {n_einh} Wohnungen {ort} ca. {flaeche}m²",
        ],
        "beschreibung": [
            "Neubau Wohnanlage in {ort}: {n_einh} Wohneinheiten, Wohnfläche "
            "ca. {flaeche}m² gesamt. Massivbauweise KfW-55, Tiefgarage, "
            "Aufzug, {qualitaet}e Innenausstattung. Schlüsselfertig.",
            "Errichtung Mehrfamilienhaus in {ort} mit {n_einh} WE "
            "(ca. {flaeche}m² Wohnfläche). Stahlbeton-Skelett, Wärmedämmung "
            "A-Standard, Fußbodenheizung, {qualitaet}e Haustechnik.",
            "Neubau Wohngebäude {ort}: {n_einh} Wohnungen, ca. {flaeche}m² "
            "Wohnfläche gesamt. KfW 55, Tiefgarage, Balkon je WE, "
            "{qualitaet}e Qualitätsstufe. Generalunternehmer gesucht.",
        ],
        "basis_eur_m2": None,
        "flaeche_range": None,
        "n_einh_range": (8, 50),
        "wohnflaeche_pro_we": (72, 105),
        "preis_pro_we": (80_000, 170_000),
        "dauer_tage_pro_we": 13.0,
        "dauer_min": 300,
    },
    # ── Kernsanierung Mehrfamilienhaus (400–2500 m²) ──────────────────────────
    {
        "cpv": "45211000",
        "titel": [
            "Kernsanierung Mehrfamilienhaus {ort} {flaeche}m² Wohnfläche",
            "Komplettsanierung Wohngebäude {flaeche}m² in {ort}",
            "Vollsanierung Mehrfamilienwohnhaus {flaeche}m² {qualitaet}",
        ],
        "beschreibung": [
            "Kernsanierung Mehrfamilienhaus in {ort}: {flaeche}m² Wohnfläche, "
            "Baujahr ca. 1968–1985. Leistungen: Dachsanierung, WDVS-Fassade, "
            "Fenster, Heizung, Elektro komplett neu, Bäder sanieren. "
            "Qualität: {qualitaet}.",
            "Komplettsanierung Wohngebäude in {ort}: {flaeche}m² Wohnfläche. "
            "Kernsanierung mit Erhalt Tragwerk, neue TGA, Fassadendämmung WDVS, "
            "Fenster, Treppenhaussanierung, Balkonsanierung. {qualitaet}e Ausführung.",
            "Vollsanierung Mehrfamilienhaus {ort}: {flaeche}m² Wohnfläche gesamt. "
            "Gebäude Baujahr 1960–1980 wird umfassend saniert: Dach, Außenwände, "
            "Fenster, gesamte Haustechnik erneuert. Qualitätsniveau: {qualitaet}.",
        ],
        "basis_eur_m2": 380.0,
        "flaeche_range": (400, 2500),
        "dauer_tage_pro_100m2": 10.0,
        "dauer_min": 150,
    },
    # ── Neubau Bürogebäude (500–4000 m²) ─────────────────────────────────────
    {
        "cpv": "45213100",
        "titel": [
            "Neubau Bürogebäude {ort} {flaeche}m² BGF",
            "Errichtung Verwaltungsgebäude {flaeche}m² in {ort}",
            "Neubau Büro- und Geschäftshaus {ort} {flaeche}m²",
        ],
        "beschreibung": [
            "Neubau Bürogebäude in {ort}: {flaeche}m² Bruttogeschossfläche, "
            "4–5 Geschosse. Stahlbeton-Skelett, Vorhangfassade Aluminium-Glas, "
            "TGA nach DGNB-Standard, {qualitaet}e Ausstattung inkl. Tiefgarage.",
            "Errichtung Verwaltungsgebäude in {ort}: {flaeche}m² BGF. Offene "
            "Bürolandschaft, Konferenzbereich, Kantine. Energiestandard EH 55, "
            "Wärmepumpe. Qualitätsstufe: {qualitaet}. Schlüsselfertig.",
            "Neubau Büro- und Geschäftshaus {ort}: {flaeche}m² Nutzfläche. "
            "Generalunternehmer schlüsselfertig. Haustechnik: Wärmepumpe, KWL, "
            "LED-DALI-Beleuchtung, {qualitaet}e Ausbauqualität.",
        ],
        "basis_eur_m2": 1100.0,
        "flaeche_range": (500, 4000),
        "dauer_tage_pro_100m2": 10.0,
        "dauer_min": 270,
    },
    # ── TGA-Komplettsanierung Schule / Verwaltungsgebäude (1000–6000 m²) ─────
    {
        "cpv": "45331000",
        "titel": [
            "TGA-Komplettsanierung Schulgebäude {ort} {flaeche}m²",
            "Heizung, Lüftung und Elektro Sanierung {flaeche}m² Schule {ort}",
            "Haustechnik-Erneuerung öffentliches Gebäude {flaeche}m² in {ort}",
        ],
        "beschreibung": [
            "TGA-Komplettsanierung Schulgebäude in {ort}: {flaeche}m² BGF. "
            "Umfasst Heizungsanlage (Gas-Brennwert → Wärmepumpe), Lüftung "
            "mit Wärmerückgewinnung, Elektro komplett, Gebäudeautomation MSR. "
            "Qualität: {qualitaet}.",
            "Sanierung Heizung/Lüftung/Klima Schulkomplex {ort}: {flaeche}m² "
            "beheizte Fläche. Neue Heizzentrale Wärmepumpe, dezentrale Lüftungsgeräte "
            "mit WRG, Heizkörper tauschen, Hydraulik optimieren. {qualitaet}e Technik.",
            "Haustechnik-Erneuerung öffentliches Gebäude in {ort}: {flaeche}m² "
            "Nutzfläche. Komplette TGA-Sanierung: Heizung, Lüftung, Sanitär, "
            "Elektro, MSR-Technik. Energetisches Ziel: 30 % Einsparung. "
            "Qualität: {qualitaet}.",
        ],
        "basis_eur_m2": 180.0,
        "flaeche_range": (1000, 6000),
        "dauer_tage_pro_100m2": 4.0,
        "dauer_min": 120,
    },
    # ── Neubau Kindertagesstätte (300–900 m²) ────────────────────────────────
    {
        "cpv": "45214100",
        "titel": [
            "Neubau Kindertagesstätte {ort} {flaeche}m² Nutzfläche",
            "Errichtung Kita {ort} {flaeche}m² {qualitaet}e Ausstattung",
            "Neubau Kindergarten {flaeche}m² in {ort} schlüsselfertig",
        ],
        "beschreibung": [
            "Neubau Kindertagesstätte in {ort}: {flaeche}m² Nutzfläche für "
            "4 Gruppen à 25 Plätze. Holzständerbauweise, Flachdach begrünt, "
            "Fußbodenheizung, {qualitaet}e Ausstattung, Außenanlagen inklusive.",
            "Errichtung Kita in {ort}: {flaeche}m² NF, 75–100 Plätze. "
            "Massivbauweise EH-40-Standard, KWL mit WRG, {qualitaet}e "
            "Innenausstattung und Außenspielbereich 800m². Schlüsselfertig.",
            "Neubau Kindergarten {ort}: {flaeche}m² Nutzfläche, eingeschossig, "
            "Stahlbeton, Flachdach. 4–5 Gruppen. Qualität: {qualitaet}. "
            "Außengelände gestalten, Küche inklusive.",
        ],
        "basis_eur_m2": 2000.0,
        "flaeche_range": (300, 900),
        "dauer_tage_pro_100m2": 25.0,
        "dauer_min": 210,
    },
    # ── Sanierung Verwaltungsgebäude (500–3000 m²) ───────────────────────────
    {
        "cpv": "45213100",
        "titel": [
            "Sanierung Verwaltungsgebäude {ort} {flaeche}m² BGF",
            "Modernisierung Bürogebäude {flaeche}m² in {ort} {qualitaet}",
            "Komplettsanierung Verwaltungsbau {ort} {flaeche}m²",
        ],
        "beschreibung": [
            "Sanierung Verwaltungsgebäude in {ort}: {flaeche}m² BGF, Baujahr "
            "ca. 1985–2000. Fassadensanierung, Fenster, TGA-Erneuerung, "
            "Innenausbau komplett neu. {qualitaet}e Ausführung, EH-70-Ziel.",
            "Modernisierung Bürogebäude {flaeche}m² in {ort}: Grundsanierung "
            "Rohbau, Fassade, TGA (Heizung, Klima, Elektro), Innenausbau "
            "{qualitaet}e Qualitätsstufe. Betrieb teilweise aufrechterhalten.",
            "Komplettsanierung Verwaltungsbau in {ort}: {flaeche}m² NF. "
            "Dach, Fassade, Fenster, gesamte TGA und Innenausbau. "
            "Generalunternehmer, {qualitaet}e Ausstattung, schlüsselfertig.",
        ],
        "basis_eur_m2": 500.0,
        "flaeche_range": (500, 3000),
        "dauer_tage_pro_100m2": 8.0,
        "dauer_min": 180,
    },
    # ── Elektrosanierung Großgebäude (500–5000 m²) ───────────────────────────
    {
        "cpv": "45310000",
        "titel": [
            "Elektrosanierung Schulgebäude {ort} {flaeche}m²",
            "Elektroinstallation erneuern {flaeche}m² Verwaltungsgebäude",
            "Starkstrom- und Schwachstromsanierung {flaeche}m² in {ort}",
        ],
        "beschreibung": [
            "Elektrosanierung Schulgebäude in {ort}: {flaeche}m² BGF komplett "
            "neu verdrahten. Hauptverteilung, Unterverteilungen, Leitungen "
            "NYM-J, LED-Beleuchtung DALI, Brandmeldeanlage. Qualität: {qualitaet}.",
            "Elektroinstallation Verwaltungsgebäude {ort}: {flaeche}m² NGF, "
            "Unterverteilungen erneuern, Steckdosen/Schalter, USV, "
            "EIB-Gebäudeautomation. {qualitaet}e Schalterprogramm.",
            "Starkstrom- und Schwachstromsanierung {flaeche}m² in {ort}: "
            "Komplette Erneuerung Elektro (FI/LS, Leitungen, Leuchten), "
            "Netzwerk Cat6A, ELA-Anlage. {qualitaet}e Ausführung nach VDE.",
        ],
        "basis_eur_m2": 130.0,
        "flaeche_range": (500, 5000),
        "dauer_tage_pro_100m2": 3.5,
        "dauer_min": 90,
    },
    # ── Neubau Sporthalle (500–2000 m²) ──────────────────────────────────────
    {
        "cpv": "45212200",
        "titel": [
            "Neubau Sporthalle {ort} {flaeche}m² BGF",
            "Errichtung Dreifeldsporthalle {ort} ca. {flaeche}m²",
            "Neubau Schulsportgebäude {flaeche}m² in {ort}",
        ],
        "beschreibung": [
            "Neubau Sporthalle in {ort}: {flaeche}m² Bruttogeschossfläche, "
            "Dreifeldteilung, Tribüne, Geräteräume, Umkleiden. Stahlbeton-Skelett, "
            "Akustikdecke, {qualitaet}e Sportböden DIN 18032.",
            "Errichtung Dreifeldsporthalle in {ort}: ca. {flaeche}m² BGF. "
            "Stahltragwerk, Trapezblechdach gedämmt, Prallwände nach DIN, "
            "Heizung Luft-Wasser-WP, {qualitaet}e Ausstattung.",
            "Neubau Schulsportgebäude {ort}: {flaeche}m² BGF. Gymnastikhalle "
            "und Haupthalle, Umkleide-Trakt, Zuschauertribüne. Schlüsselfertig, "
            "Qualitätsstufe: {qualitaet}.",
        ],
        "basis_eur_m2": 1800.0,
        "flaeche_range": (500, 2000),
        "dauer_tage_pro_100m2": 15.0,
        "dauer_min": 270,
    },
]

PUBLIKATIONSDATEN = [
    "20230201", "20230401", "20230601", "20230801", "20231001", "20231201",
    "20240115", "20240301", "20240501", "20240701", "20240901", "20241101",
]


def _berechne_budget(vorlage: dict, flaeche: float, qual_faktor: float,
                     n_einh: int, bbsr: float) -> float:
    if vorlage.get("n_einh_range"):
        lo, hi = vorlage["preis_pro_we"]
        basis = n_einh * random.uniform(lo, hi)
    else:
        m2_preis = vorlage["basis_eur_m2"] * random.uniform(0.85, 1.15)
        basis = flaeche * m2_preis
    return round(basis * qual_faktor * (bbsr / 100.0), 0)


def _berechne_dauer(vorlage: dict, flaeche: float, n_einh: int) -> int:
    dauer_min = vorlage.get("dauer_min", 90)
    if vorlage.get("dauer_tage_pro_we") and n_einh:
        basis = n_einh * vorlage["dauer_tage_pro_we"]
    elif vorlage.get("dauer_tage_pro_100m2"):
        basis = (flaeche / 100.0) * vorlage["dauer_tage_pro_100m2"]
    else:
        return random.randint(dauer_min, dauer_min + 90)
    return max(dauer_min, int(basis * random.uniform(0.7, 1.4)))


def generiere_datensatz(vorlage: dict, stadt: dict, qualitaet: tuple[str, float]) -> dict | None:
    qual_name, qual_faktor = qualitaet
    ort = stadt["ort"]

    flaeche = 0.0
    n_einh  = 0
    if vorlage.get("flaeche_range"):
        lo, hi  = vorlage["flaeche_range"]
        flaeche = round(random.uniform(lo, hi), 0)
    elif vorlage.get("n_einh_range"):
        lo, hi = vorlage["n_einh_range"]
        n_einh = random.randint(lo, hi)
        wf_lo, wf_hi = vorlage.get("wohnflaeche_pro_we", (72, 100))
        flaeche = round(n_einh * random.uniform(wf_lo, wf_hi), 0)

    budget = _berechne_budget(vorlage, flaeche, qual_faktor, n_einh, stadt["bbsr"])
    if budget < BUDGET_MIN_EUR or budget > BUDGET_MAX_EUR:
        return None

    dauer = _berechne_dauer(vorlage, flaeche, n_einh)

    titel_tmpl = random.choice(vorlage["titel"])
    titel = titel_tmpl.format(
        flaeche=int(flaeche) if flaeche else "",
        qualitaet=qual_name,
        ort=ort,
        n_einh=n_einh if n_einh else "",
    ).strip()

    beschr_tmpl = random.choice(vorlage["beschreibung"])
    beschreibung = beschr_tmpl.format(
        flaeche=int(flaeche) if flaeche else "",
        qualitaet=qual_name,
        ort=ort,
        n_einh=n_einh if n_einh else "",
    ).strip()

    pub_date = random.choice(PUBLIKATIONSDATEN)

    return {
        "document_id":      f"synth_{uuid.uuid4().hex[:10]}",
        "title":            f"{ort}: {titel}",
        "description":      beschreibung,
        "cpv_code":         vorlage["cpv"],
        "estimated_value":  budget,
        "currency":         "EUR",
        "country":          stadt["land"],
        "publication_date": pub_date,
        "duration_days":    dauer,
        "auftraggeber_ort": ort,
        "auftraggeber_plz": None,
        "datenquelle":      "synthetic_large",
    }


def generiere_alle(n_ziel: int = 800, seed: int = 42) -> list[dict]:
    random.seed(seed)
    datensaetze: list[dict] = []
    versuche = 0
    max_versuche = n_ziel * 20

    while len(datensaetze) < n_ziel and versuche < max_versuche:
        vorlage   = random.choice(PROJEKTVORLAGEN)
        stadt     = random.choice(STAEDTE)
        qualitaet = random.choice(QUALITAETEN)
        ds = generiere_datensatz(vorlage, stadt, qualitaet)
        if ds is not None:
            datensaetze.append(ds)
        versuche += 1

    logger.info(
        "[Synthetisch Groß] %d von %d Datensätzen generiert (%d Versuche).",
        len(datensaetze), n_ziel, versuche,
    )
    return datensaetze


def main() -> None:
    import argparse
    from collections import Counter

    parser = argparse.ArgumentParser(description="Generiert synthetische mittlere/große Bauprojekte")
    parser.add_argument("--n",      type=int, default=800,          help="Anzahl Datensätze")
    parser.add_argument("--seed",   type=int, default=42,           help="Random-Seed")
    parser.add_argument("--ausgabe", type=str, default=str(AUSGABE_PFAD), help="Ausgabepfad")
    args = parser.parse_args()

    ausgabe = Path(args.ausgabe)
    ausgabe.parent.mkdir(parents=True, exist_ok=True)

    datensaetze = generiere_alle(n_ziel=args.n, seed=args.seed)

    with ausgabe.open("w", encoding="utf-8") as f:
        for ds in datensaetze:
            f.write(json.dumps(ds, ensure_ascii=False) + "\n")

    logger.info("[Synthetisch Groß] Gespeichert: %s (%d Zeilen)", ausgabe, len(datensaetze))

    budgets = [ds["estimated_value"] for ds in datensaetze]
    klassen = [
        ("50k–200k€",    50_000,   200_000),
        ("200k–1M€",    200_000, 1_000_000),
        ("1M–5M€",    1_000_000, 5_000_000),
        ("5M–8M€",    5_000_000, 8_000_001),
    ]
    print(f"\nBudget-Verteilung der synthetischen Großprojekte ({len(budgets)} Datensätze):")
    for label, lo, hi in klassen:
        n = sum(1 for b in budgets if lo <= b < hi)
        print(f"  {label:<14}: {n:>4} ({100*n/len(budgets):.0f}%)")

    print(f"\nVerteilung nach CPV:")
    for cpv, n in sorted(Counter(ds["cpv_code"] for ds in datensaetze).items(), key=lambda x: -x[1]):
        print(f"  {cpv}: {n:>4}")


if __name__ == "__main__":
    main()
