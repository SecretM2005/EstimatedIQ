"""
Generiert synthetische kleine Bauprojekte (5.000–49.999 €) für EstimateIQ Bau.

Motivation: TED-Ausschreibungen starten selten unter 50k€ (öffentliche Vergabepflicht).
Dadurch kann das Modell kleine Privatprojekte nicht zuverlässig schätzen.

Output: data/raw_notices_bau_small.jsonl (kompatibel mit preprocess_bau.py Glob-Muster)

Verwendung:
    python -m estimateiq.data.generate_small_bau
    python -m estimateiq.data.preprocess_bau
    python train_bau.py --kein-bert
"""

import json
import logging
import random
import uuid
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

AUSGABE_PFAD = Path("data/raw_notices_bau_small.jsonl")

# BBSR-Baukostenindex je Stadt (normalisiert auf 100 = DE-Schnitt)
# Muss mit preprocess_bau → fetch_bbsr konsistent sein
STAEDTE: list[dict] = [
    {"ort": "München",   "land": "DE", "bundesland": "Bayern",                "bbsr": 118.5},
    {"ort": "Hamburg",   "land": "DE", "bundesland": "Hamburg",               "bbsr": 110.0},
    {"ort": "Berlin",    "land": "DE", "bundesland": "Berlin",                "bbsr": 105.8},
    {"ort": "Stuttgart", "land": "DE", "bundesland": "Baden-Württemberg",     "bbsr": 108.0},
    {"ort": "Frankfurt", "land": "DE", "bundesland": "Hessen",                "bbsr": 105.0},
    {"ort": "Köln",      "land": "DE", "bundesland": "Nordrhein-Westfalen",   "bbsr": 101.2},
    {"ort": "Dortmund",  "land": "DE", "bundesland": "Nordrhein-Westfalen",   "bbsr": 101.2},
    {"ort": "Hannover",  "land": "DE", "bundesland": "Niedersachsen",         "bbsr":  98.0},
    {"ort": "Leipzig",   "land": "DE", "bundesland": "Sachsen",               "bbsr":  92.1},
    {"ort": "Dresden",   "land": "DE", "bundesland": "Sachsen",               "bbsr":  92.1},
    {"ort": "Nürnberg",  "land": "DE", "bundesland": "Bayern",                "bbsr": 118.5},
    {"ort": "Bremen",    "land": "DE", "bundesland": "Bremen",                "bbsr": 102.0},
    {"ort": "Erfurt",    "land": "DE", "bundesland": "Thüringen",             "bbsr":  91.5},
    {"ort": "Wien",      "land": "AT", "bundesland": "Wien",                  "bbsr": 108.0},
    {"ort": "Graz",      "land": "AT", "bundesland": "Steiermark",            "bbsr": 104.0},
    {"ort": "Zürich",    "land": "CH", "bundesland": "Zürich",                "bbsr": 125.0},
    {"ort": "Basel",     "land": "CH", "bundesland": "Basel-Stadt",           "bbsr": 122.0},
]

# Qualitätsfaktoren
QUALITAETEN = [
    ("einfach",     0.75),
    ("standard",    1.00),
    ("hochwertig",  1.40),
]

# Projektdefinitionen
# CPV-Codes: 8-stellig, 45xxxxxx (Bau-Hauptgruppe)
# Mapping laut preprocess_bau.py CPV_GEWERK:
#   45440000 → "Maler"           45442000 → "Malerarbeiten"
#   45431000 → "Fliesen"         45430000 → "Fliesen/Boden"
#   45310000 → "Elektro"         45315000 → "Elektroinstallation"
#   45332000 → "Sanitär"         45331000 → "Heizung/Lüftung/Klima"
#   45421000 → "Zimmerei/Tischler" 45422000 → "Holzbau"
#   45410000 → "Putz/Stuck"
#   45400000 → "Ausbau allgemein"
#   45110000 → "Abbruch/Freilegung"
#
# Felder je Projekt:
#   cpv:        8-stelliger CPV-Code
#   titel_tmpl: f-string mit {flaeche}, {qualitaet}, {ort}
#   basis_eur:  Basispreis pro m² (oder Pauschal bei flaeche_range=None)
#   flaeche_range: (min_m2, max_m2) – None = Pauschalpreis
#   dauer_basis: Basisdauer in Tagen je 10m² (oder Pauschale bei flaeche=None)
#   min_budget: Untergrenze nach Filtern (BUDGET_MIN_EUR=5000 in preprocess)

PROJEKTVORLAGEN: list[dict] = [
    # ── Maler ──────────────────────────────────────────────────────────────────
    {
        "cpv": "45442000",
        "titel": [
            "Malerarbeiten Innenräume {flaeche}m²",
            "Anstrich Wohnzimmer und Schlafzimmer {flaeche}m²",
            "Renovierungsanstrich Büroräume {flaeche}m² {qualitaet}",
            "Malerarbeiten nach Wasserschaden {flaeche}m²",
            "Wände und Decken streichen {flaeche}m² Wohngebäude",
        ],
        "beschreibung": [
            "Malerarbeiten in {ort}: Wände und Decken auf {flaeche}m² streichen, "
            "{qualitaet}e Ausführung, inklusive Voranstrich und 2 Deckstriche.",
            "Innenanstrich {flaeche}m² in {ort}. Untergrund spachteln, grundieren, "
            "2× Dispersionsfarbe {qualitaet}e Qualität, Abklebearbeiten inklusive.",
            "Renovierungsanstrich {ort}: {flaeche}m² Wand- und Deckenfläche, "
            "Altanstrich abwaschen, {qualitaet}e Dispersionsfarbe, 2 Arbeitsgänge.",
        ],
        "basis_eur_m2": 18.0,
        "flaeche_range": (20, 180),
        "dauer_tage_pro_10m2": 0.8,
        "dauer_min": 7,
    },
    {
        "cpv": "45440000",
        "titel": [
            "Außenanstrich Fassade Einfamilienhaus {flaeche}m²",
            "Fassadenfarbe auftragen {flaeche}m² {qualitaet}",
            "Außenputz streichen und Fensterrahmen {flaeche}m²",
        ],
        "beschreibung": [
            "Außenanstrich in {ort}: {flaeche}m² Fassadenfläche reinigen, grundieren, "
            "Silikonharzfarbe {qualitaet}e Qualität, witterungsbeständig.",
            "Fassadenanstrich {flaeche}m² in {ort}. Untergrund vorbehandeln, "
            "Risse schließen, {qualitaet}er Fassadenfarbauftrag 2× inklusive Gerüst.",
        ],
        "basis_eur_m2": 22.0,
        "flaeche_range": (40, 220),
        "dauer_tage_pro_10m2": 1.0,
        "dauer_min": 10,
    },
    # ── Fliesen ────────────────────────────────────────────────────────────────
    {
        "cpv": "45431000",
        "titel": [
            "Fliesenarbeiten Badezimmer {flaeche}m²",
            "Wandfliesen und Bodenfliesen {flaeche}m² verlegen",
            "Badfliesen komplett erneuern {flaeche}m² {qualitaet}",
            "Fliesenverlegung Küche und Bad {flaeche}m²",
        ],
        "beschreibung": [
            "Fliesenarbeiten in {ort}: {flaeche}m² Bad- und Küchenfliesen verlegen, "
            "{qualitaet}e Qualität, Untergrund vorbereiten, Verfugen inklusive.",
            "Badezimmer Fliesen {flaeche}m² in {ort}: Altfliesen entfernen, "
            "Untergrund egalisieren, {qualitaet}e Wandfliesen + Bodenfliesen, verfugen.",
            "Fliesenverlegung {ort}: {flaeche}m² Feinsteinzeug Boden und Wandfliesen "
            "{qualitaet}e Ausführung, Sanitärsilikon ringsherum inklusive.",
        ],
        "basis_eur_m2": 65.0,
        "flaeche_range": (8, 60),
        "dauer_tage_pro_10m2": 2.0,
        "dauer_min": 7,
    },
    {
        "cpv": "45430000",
        "titel": [
            "Parkettboden verlegen {flaeche}m²",
            "Vinylboden und Laminat {flaeche}m² {qualitaet}",
            "Bodenbelag Wohnräume {flaeche}m² erneuern",
        ],
        "beschreibung": [
            "Bodenbelagsarbeiten in {ort}: {flaeche}m² {qualitaet}er Parkettboden "
            "verlegen, Untergrund schleifen, Abschlussleisten inklusive.",
            "Laminat / Vinylboden {flaeche}m² in {ort}: Altbelag entfernen, "
            "Estrich ausgleichen, {qualitaet}er schwimmender Bodenbelag verlegen.",
        ],
        "basis_eur_m2": 45.0,
        "flaeche_range": (15, 120),
        "dauer_tage_pro_10m2": 0.7,
        "dauer_min": 7,
    },
    # ── Elektro ────────────────────────────────────────────────────────────────
    {
        "cpv": "45310000",
        "titel": [
            "Elektroinstallation Wohnung erneuern",
            "Unterverteilung und Leitungen sanieren",
            "Elektroleitungen verlegen {flaeche}m² Wohngebäude",
            "Steckdosen und Schalter erneuern {flaeche}m²",
            "Elektroverteiler tauschen Mehrfamilienhaus",
        ],
        "beschreibung": [
            "Elektrosanierung in {ort}: Unterverteilung erneuern, {flaeche}m² "
            "Leitungen NYM-J verlegen, Steckdosen und Schalter {qualitaet}e Qualität.",
            "Elektroinstallation {flaeche}m² in {ort}: Zuleitung erhöhen, "
            "neue Unterverteilung, FI-Schutzschalter, Steckdosen nach VDE.",
            "Elektrosanierung {ort}: {flaeche}m² Wohnung komplett neu verdrahten, "
            "{qualitaet}e Schalterprogramm, Unterputz-Installation.",
        ],
        "basis_eur_m2": 55.0,
        "flaeche_range": (30, 200),
        "dauer_tage_pro_10m2": 0.9,
        "dauer_min": 7,
    },
    # ── Sanitär ────────────────────────────────────────────────────────────────
    {
        "cpv": "45332000",
        "titel": [
            "Sanitärinstallation Bad erneuern",
            "Badezimmer komplett sanieren Sanitär",
            "WC und Waschtisch installieren",
            "Sanitärleitungen sanieren Mehrfamilienhaus",
            "Dusche und Badewanne Austausch",
        ],
        "beschreibung": [
            "Sanitärarbeiten in {ort}: Badezimmer komplett sanieren, {qualitaet}e "
            "Sanitärobjekte (WC, Waschtisch, Dusche), Zu- und Ableitungen erneuern.",
            "Sanitärinstallation {ort}: Wasserinstallation erneuern, {qualitaet}e "
            "Armaturen, Waschtisch und Dusche, Anschlüsse DIN-gerecht.",
            "Bad-Sanierung {ort}: Sanitärobjekte {qualitaet}e Qualität tauschen, "
            "Wasseranschlüsse, Ablaufinstallation, Silikon-Abschluss.",
        ],
        "basis_eur_m2": None,
        "flaeche_range": None,
        "preis_pauschal": (4_500, 18_000),
        "dauer_min": 7,
        "dauer_max": 21,
    },
    # ── Heizung / HLK ──────────────────────────────────────────────────────────
    {
        "cpv": "45331000",
        "titel": [
            "Heizungsanlage erneuern Wohngebäude",
            "Gasheizung austauschen Brennwertkessel",
            "Wärmepumpe installieren Einfamilienhaus",
            "Heizkörper und Thermostate erneuern",
            "Heizkreislauf sanieren und optimieren",
        ],
        "beschreibung": [
            "Heizungssanierung in {ort}: Alte Gasheizung durch {qualitaet}en "
            "Brennwertkessel ersetzen, Heizkörper anpassen, hydraulischer Abgleich.",
            "Heizungsanlage {ort}: Gas-Brennwertgerät {qualitaet}e Qualität, "
            "Warmwasserspeicher, Thermostatventile, Inbetriebnahme inklusive.",
            "Wärmeversorgung sanieren {ort}: {qualitaet}e Heizungsanlage, "
            "Heizkörper tauschen, Leitungen isolieren, Abgasmessung.",
        ],
        "basis_eur_m2": None,
        "flaeche_range": None,
        "preis_pauschal": (5_000, 22_000),
        "dauer_min": 7,
        "dauer_max": 28,
    },
    # ── Putz / Stuck ───────────────────────────────────────────────────────────
    {
        "cpv": "45410000",
        "titel": [
            "Innenputz erneuern {flaeche}m²",
            "Außenputz ausbessern Fassade {flaeche}m²",
            "Wärmedämmverbundsystem WDVS {flaeche}m²",
            "Fassadenputz sanieren {flaeche}m² {qualitaet}",
        ],
        "beschreibung": [
            "Putzarbeiten in {ort}: {flaeche}m² Innenputz erneuern, Kalkgipsputz "
            "{qualitaet}e Ausführung, Ecken und Laibungen abziehen.",
            "Fassadenputz {flaeche}m² in {ort}: Altputz abstocken, Unterputz, "
            "{qualitaet}er Edelputz, Sockelbereich angepasst.",
            "WDVS {flaeche}m² in {ort}: Styropordämmung 12cm, Gewebeeinlage, "
            "{qualitaet}er Silikonharzputz, Anschlüsse fugendicht.",
        ],
        "basis_eur_m2": 38.0,
        "flaeche_range": (20, 200),
        "dauer_tage_pro_10m2": 0.8,
        "dauer_min": 7,
    },
    # ── Holzbau / Zimmerer ─────────────────────────────────────────────────────
    {
        "cpv": "45422000",
        "titel": [
            "Carport Holzkonstruktion bauen",
            "Terrassenüberdachung Holzbau {flaeche}m²",
            "Pergola und Überdachung errichten",
            "Holzterrasse und Deckenkonstruktion {flaeche}m²",
            "Gartenhaus Holzständerbauweise",
        ],
        "beschreibung": [
            "Holzbau in {ort}: Carport / Terrassenüberdachung {flaeche}m² in "
            "Holzständerbauweise, {qualitaet}e Ausführung, Dacheindeckung inklusive.",
            "Pergola / Holzkonstruktion {flaeche}m² in {ort}: Statik geprüft, "
            "Lärcheholz {qualitaet}e Qualität, Gründung Betonfundamente.",
            "Terrassendach {flaeche}m² in {ort}: Bausatz Holzkonstruktion, "
            "{qualitaet}e Dacheindeckung VSG-Glas oder Polycarbonat.",
        ],
        "basis_eur_m2": 180.0,
        "flaeche_range": (12, 60),
        "dauer_tage_pro_10m2": 2.5,
        "dauer_min": 10,
    },
    # ── Trockenbau / Ausbau ────────────────────────────────────────────────────
    {
        "cpv": "45400000",
        "titel": [
            "Trockenbau Wände und Decken {flaeche}m²",
            "Leichtbauwände Büro und Wohngebäude {flaeche}m²",
            "Vorsatzschale und Trockenestrich {flaeche}m²",
            "Deckenabhängung und Installationskanal {flaeche}m²",
        ],
        "beschreibung": [
            "Trockenbauarbeiten in {ort}: {flaeche}m² Metallständerwände CW/UW-Profile, "
            "Gipskarton doppelt beplankt, {qualitaet}e Oberfläche Q2/Q3.",
            "Trockenbau {flaeche}m² in {ort}: Abgehängte Decken, Wandvormauerungen, "
            "{qualitaet}e Ausführung, Schallschutzanforderungen berücksichtigt.",
            "Ausbau {flaeche}m² Bürofläche in {ort}: Trennwände, Abgehängte Decken, "
            "Kabelkanäle, Oberfläche {qualitaet}e Qualität.",
        ],
        "basis_eur_m2": 48.0,
        "flaeche_range": (20, 200),
        "dauer_tage_pro_10m2": 0.7,
        "dauer_min": 7,
    },
    # ── Abbruch / Demontage ────────────────────────────────────────────────────
    {
        "cpv": "45110000",
        "titel": [
            "Abbrucharbeiten Innenausbau {flaeche}m²",
            "Demontage Trennwände und Bodenbelag {flaeche}m²",
            "Kernbohrungen und Wanddurchbrüche",
            "Rückbau Badezimmer und Sanitär",
        ],
        "beschreibung": [
            "Abbruch in {ort}: {flaeche}m² Innenausbau rückbauen, Trennwände entfernen, "
            "Schutt entsorgen, Entsorgungsnachweis inklusive.",
            "Demontage {flaeche}m² Büroausbau in {ort}: Trockenbauwände, Bodenbelag, "
            "Deckenelemente rückbauen, Entsorgung nach Abfallverzeichnis.",
            "Rückbau Bad und WC in {ort}: Sanitärobjekte demontieren, Fliesen abstemmen, "
            "{flaeche}m² Untergrund freilegen, Schuttentsorgung.",
        ],
        "basis_eur_m2": 28.0,
        "flaeche_range": (15, 150),
        "dauer_tage_pro_10m2": 0.6,
        "dauer_min": 7,
    },
    # ── Zimmerei / Tischler (Dach) ─────────────────────────────────────────────
    {
        "cpv": "45421000",
        "titel": [
            "Fenster und Türen austauschen {n_einh} Stück",
            "Holzfenster durch Kunststofffenster ersetzen",
            "Haustür und Nebentür erneuern",
            "Innentüren komplett erneuern Wohngebäude",
        ],
        "beschreibung": [
            "Fenstererneuerung in {ort}: {n_einh} Kunststofffenster {qualitaet}e "
            "Qualität 2-/3-fach Verglasung, Uw ≤ 1,1 W/m²K, Montage inklusive.",
            "Fenster tauschen {ort}: {n_einh} Stück {qualitaet}e Aluminiumfenster, "
            "Wärmedämmglas, Fensteranschlussbänder, RAL-Montage.",
            "Türerneuerung {ort}: {n_einh} Holz-Innentüren {qualitaet}e Qualität, "
            "Zargen neu, Beschläge, Schwellen, Montage und Einstellung.",
        ],
        "basis_eur_m2": None,
        "flaeche_range": None,
        "n_einh_range": (3, 15),
        "preis_pro_einh": (400, 1_200),
        "dauer_min": 7,
        "dauer_max": 21,
    },
]

# Veröffentlichungsdaten – nur 2023–2024 damit --min-jahr 2023 Filter überlebt
PUBLIKATIONSDATEN = [
    "20230201", "20230401", "20230601", "20230801", "20231001", "20231201",
    "20240115", "20240301", "20240501", "20240701", "20240901", "20241101",
]


def _preisband_zu_budget(vorlage: dict, flaeche: float, qualitaet_faktor: float,
                          n_einh: int, bbsr: float) -> float:
    """Berechnet das Budget nach der Preisformel."""
    if vorlage.get("preis_pauschal"):
        lo, hi = vorlage["preis_pauschal"]
        basis = random.uniform(lo, hi)
    elif vorlage.get("n_einh_range"):
        lo, hi = vorlage["preis_pro_einh"]
        basis = n_einh * random.uniform(lo, hi)
    else:
        m2_preis = vorlage["basis_eur_m2"] * random.uniform(0.85, 1.15)
        basis = flaeche * m2_preis

    budget = basis * qualitaet_faktor * (bbsr / 100.0)
    return round(budget, 0)


def _dauer_aus_vorlage(vorlage: dict, flaeche: float, budget: float) -> int:
    dauer_min = vorlage.get("dauer_min", 7)
    if vorlage.get("dauer_max"):
        dauer = random.randint(dauer_min, vorlage["dauer_max"])
    elif vorlage.get("dauer_tage_pro_10m2"):
        basis_tage = (flaeche / 10.0) * vorlage["dauer_tage_pro_10m2"]
        dauer = max(dauer_min, int(basis_tage * random.uniform(0.7, 1.4)))
    else:
        dauer = random.randint(dauer_min, dauer_min + 14)
    return dauer


def generiere_datensatz(vorlage: dict, stadt: dict, qualitaet: tuple[str, float]) -> dict | None:
    """Erstellt einen einzelnen synthetischen Datensatz."""
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

    budget = _preisband_zu_budget(vorlage, flaeche, qual_faktor, n_einh, stadt["bbsr"])

    # Unter Budget-Grenze des Preprocessors → überspringen (wird sowieso gefiltert)
    if budget < 5_000 or budget > 49_999:
        return None

    dauer = _dauer_aus_vorlage(vorlage, flaeche, budget)
    if dauer < 7:
        dauer = 7

    # Titel und Beschreibung auswählen
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
        "datenquelle":      "synthetic_small",
    }


def generiere_alle(n_ziel: int = 500, seed: int = 42) -> list[dict]:
    """Generiert n_ziel synthetische Datensätze (balanciert über Vorlagen und Städte)."""
    random.seed(seed)
    datensaetze: list[dict] = []
    versuche    = 0
    max_versuche = n_ziel * 20

    while len(datensaetze) < n_ziel and versuche < max_versuche:
        vorlage  = random.choice(PROJEKTVORLAGEN)
        stadt    = random.choice(STAEDTE)
        qualitaet = random.choice(QUALITAETEN)

        ds = generiere_datensatz(vorlage, stadt, qualitaet)
        if ds is not None:
            datensaetze.append(ds)
        versuche += 1

    logger.info(
        "[Synthetisch] %d von %d Datensätzen generiert (%d Versuche).",
        len(datensaetze), n_ziel, versuche,
    )
    return datensaetze


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Generiert synthetische kleine Bauprojekte")
    parser.add_argument("--n", type=int, default=500,
                        help="Anzahl Datensätze (default: 500)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random-Seed für Reproduzierbarkeit")
    parser.add_argument("--ausgabe", type=str, default=str(AUSGABE_PFAD),
                        help=f"Ausgabepfad (default: {AUSGABE_PFAD})")
    args = parser.parse_args()

    ausgabe = Path(args.ausgabe)
    ausgabe.parent.mkdir(parents=True, exist_ok=True)

    datensaetze = generiere_alle(n_ziel=args.n, seed=args.seed)

    with ausgabe.open("w", encoding="utf-8") as f:
        for ds in datensaetze:
            f.write(json.dumps(ds, ensure_ascii=False) + "\n")

    logger.info("[Synthetisch] Gespeichert: %s (%d Zeilen)", ausgabe, len(datensaetze))

    # Verteilungs-Überblick
    budgets = [ds["estimated_value"] for ds in datensaetze]
    under_15k = sum(1 for b in budgets if b < 15_000)
    under_30k = sum(1 for b in budgets if 15_000 <= b < 30_000)
    under_50k = sum(1 for b in budgets if b >= 30_000)
    print(f"\nBudget-Verteilung der synthetischen Projekte:")
    print(f"  5k–15k€:  {under_15k:>4} Projekte  ({100*under_15k/len(budgets):.0f}%)")
    print(f"  15k–30k€: {under_30k:>4} Projekte  ({100*under_30k/len(budgets):.0f}%)")
    print(f"  30k–50k€: {under_50k:>4} Projekte  ({100*under_50k/len(budgets):.0f}%)")

    from collections import Counter
    cpv_zaehler = Counter(ds["cpv_code"] for ds in datensaetze)
    print(f"\nVerteilung nach CPV:")
    for cpv, n in sorted(cpv_zaehler.items(), key=lambda x: -x[1]):
        print(f"  {cpv}: {n:>4}")


if __name__ == "__main__":
    main()
