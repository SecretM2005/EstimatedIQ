"""
Rollenbasierte Marktpreise für DACH IT-Freelancer und Consultants.

Datenquelle:
  freelancermap.de Stundenatz-Index 2024 (jährliche Marktauswertung, > 30.000 Profile).
  Werte entsprechen Median-Stundensätzen in EUR für erfahrene Freelancer / externe Consultants
  auf dem DACH-Markt (Deutschland Bundesdurchschnitt als Referenz).

Regionale Faktoren:
  Basieren auf Kaufkraftparität und Gehalts-/Kostenstruktur der jeweiligen Region.
  Quellen: Destatis Kaufkraftindex, BSF Bundesstatistik Österreich, BFS Schweiz.

Verwendung:
  from estimateiq.data.market_rates import get_gewichteter_stundensatz
  info = get_gewichteter_stundensatz("SAP S/4HANA Migration 800 Nutzer", "DE-BY")
  # info["gewichteter_satz"] → gewichteter Stundensatz in EUR/h
  # info["rollen"]           → Liste von Rollen mit Anteilen und Stundensätzen
  # info["komposition_typ"]  → erkannter Projekttyp (z.B. "sap", "mobile", "python_ml")
"""

import re

# ---------------------------------------------------------------------------
# Stundensatz-Tabelle (EUR/h, DACH Median Freelancer/Consultant 2024)
# Quelle: freelancermap.de Stundensatz-Index 2024
# ---------------------------------------------------------------------------

ROLLEN_STUNDENSATZ_DE: dict[str, float] = {
    "SAP Consultant":       165.0,
    "SAP Technical":        145.0,
    "Java Developer":       115.0,
    "Backend Developer":    108.0,
    "Frontend Developer":    98.0,
    ".NET Developer":       105.0,
    "Python/ML Engineer":   118.0,
    "Mobile Developer":     112.0,
    "DevOps Engineer":      118.0,
    "Data Engineer":        118.0,
    "PHP Developer":         88.0,
    "WordPress Developer":   75.0,
    "UX Designer":           88.0,
    "Project Manager":      115.0,
    "Business Analyst":      98.0,
    "Security Consultant":  138.0,
    "Fullstack Developer":  102.0,
    "Allgemein":             98.0,
}

# ---------------------------------------------------------------------------
# Regionale Multiplikatoren (relativ zum deutschen Bundesdurchschnitt)
# ---------------------------------------------------------------------------

REGION_FAKTOR: dict[str, float] = {
    # Schweiz – deutlich höhere Lebenshaltungskosten
    "CH":    1.50,
    # Österreich
    "AT":    0.95,
    # Deutschland national
    "DE":    1.00,
    # DE Bundesländer
    "DE-BY": 1.15,   # Bayern (München)
    "DE-BW": 1.10,   # Baden-Württemberg
    "DE-HH": 1.08,   # Hamburg
    "DE-NW": 1.05,   # Nordrhein-Westfalen
    "DE-HE": 1.05,   # Hessen (Frankfurt)
    "DE-BE": 0.95,   # Berlin
    "DE-SN": 0.88,   # Sachsen
    "DE-TH": 0.87,   # Thüringen
    "DE-BB": 0.88,   # Brandenburg
    "DE-MV": 0.87,   # Mecklenburg-Vorpommern
    "DE-SA": 0.87,   # Sachsen-Anhalt
    "DE-SH": 0.95,   # Schleswig-Holstein
    "DE-NI": 0.93,   # Niedersachsen
    "DE-RP": 0.93,   # Rheinland-Pfalz
    "DE-SL": 0.92,   # Saarland
    "DE-HB": 0.97,   # Bremen
}

# ---------------------------------------------------------------------------
# Team-Kompositionen je Projekttyp (Rolle → Anteil am Gesamtaufwand)
# ---------------------------------------------------------------------------

TEAM_KOMPOSITION: dict[str, list[tuple[str, float]]] = {
    "sap": [
        ("SAP Consultant",  0.55),
        ("Business Analyst", 0.20),
        ("Project Manager",  0.15),
        ("SAP Technical",    0.10),
    ],
    "erp": [
        ("SAP Consultant",   0.45),
        ("Business Analyst", 0.25),
        ("Project Manager",  0.20),
        ("Backend Developer", 0.10),
    ],
    "mobile": [
        ("Mobile Developer",  0.60),
        ("Backend Developer", 0.20),
        ("UX Designer",       0.15),
        ("Project Manager",   0.05),
    ],
    "python_ml": [
        ("Python/ML Engineer", 0.65),
        ("Data Engineer",       0.20),
        ("Backend Developer",   0.10),
        ("DevOps Engineer",     0.05),
    ],
    "data": [
        ("Data Engineer",      0.55),
        ("Backend Developer",  0.25),
        ("Business Analyst",   0.15),
        ("DevOps Engineer",    0.05),
    ],
    "devops": [
        ("DevOps Engineer",    0.65),
        ("Backend Developer",  0.25),
        ("Security Consultant", 0.10),
    ],
    "wordpress": [
        ("WordPress Developer", 1.0),
    ],
    "php": [
        ("PHP Developer",      0.80),
        ("Frontend Developer", 0.20),
    ],
    "dotnet": [
        (".NET Developer",     0.75),
        ("Frontend Developer", 0.25),
    ],
    "java": [
        ("Java Developer",     0.65),
        ("Frontend Developer", 0.20),
        ("DevOps Engineer",    0.15),
    ],
    "frontend": [
        ("Frontend Developer", 0.70),
        ("UX Designer",        0.20),
        ("Backend Developer",  0.10),
    ],
    "security": [
        ("Security Consultant", 0.65),
        ("Backend Developer",   0.25),
        ("DevOps Engineer",     0.10),
    ],
    "enterprise": [  # Großprojekte ohne klare Technologie
        ("Backend Developer",  0.30),
        ("Frontend Developer", 0.20),
        ("Project Manager",    0.20),
        ("Business Analyst",   0.15),
        ("DevOps Engineer",    0.15),
    ],
    "allgemein": [
        ("Fullstack Developer", 0.65),
        ("Project Manager",     0.20),
        ("UX Designer",         0.15),
    ],
}

# ---------------------------------------------------------------------------
# Erkennungsregeln: Beschreibungstext → Kompositionstyp
# Reihenfolge ist bedeutsam – spezifischste Muster zuerst.
# ---------------------------------------------------------------------------

BESCHREIBUNG_ZU_KOMPOSITION: list[tuple[str, str]] = [
    # SAP zuerst (sehr spezifisch)
    (r"\bsap\b",                          "sap"),
    (r"\berp\b",                          "erp"),
    # ML/Python
    (r"\b(machine.?learning|ml|nlp|pytorch|tensorflow|scikit|bert|llm)\b", "python_ml"),
    (r"\bpython\b",                       "python_ml"),
    # Data
    (r"\b(data.?warehouse|data.?lake|analytics|bi\b|power.?bi|tableau)\b", "data"),
    # Mobile
    (r"\b(ios|android|flutter|swift|react.?native|kotlin)\b", "mobile"),
    (r"\b(mobil|mobile|app\b)\b",         "mobile"),
    # DevOps
    (r"\b(kubernetes|docker|ci.?cd|devops|terraform|ansible)\b", "devops"),
    # WordPress/CMS
    (r"\b(wordpress|woocommerce|cms|typo3|drupal|joomla)\b", "wordpress"),
    # PHP
    (r"\b(php|laravel|symfony)\b",        "php"),
    # .NET
    (r"\b(\.net|c#|asp\.?net|blazor|dotnet)\b", "dotnet"),
    # Java
    (r"\b(java|spring|quarkus|jakarta)\b", "java"),
    # Frontend/JS
    (r"\b(react|angular|vue|typescript|next\.?js|nuxt)\b", "frontend"),
    # Security
    (r"\b(pentest|sicherheit|security|nis2|dsgvo.+audit)\b", "security"),
]


# ---------------------------------------------------------------------------
# Öffentliche Funktionen
# ---------------------------------------------------------------------------

def erkenne_rollen(beschreibung: str) -> list[tuple[str, float]]:
    """
    Erkennt die passende Team-Komposition anhand der Projektbeschreibung.

    Geht die Erkennungsregeln der Reihe nach durch und gibt die erste
    Übereinstimmung zurück. Fällt auf "allgemein" zurück wenn kein
    Keyword passt.

    Args:
        beschreibung: Freitext der Projektbeschreibung.

    Returns:
        Liste von (rolle, anteil)-Tupeln, deren Anteile sich zu 1.0 summieren.
    """
    text = (beschreibung or "").lower()
    for muster, komposition_key in BESCHREIBUNG_ZU_KOMPOSITION:
        if re.search(muster, text):
            return list(TEAM_KOMPOSITION[komposition_key])
    return list(TEAM_KOMPOSITION["allgemein"])


def get_stundensatz(rolle: str, region: str) -> float:
    """
    Gibt den regionalen Stundensatz für eine Rolle zurück.

    Wendet den regionalen Multiplikator auf den deutschen Basisstundensatz an.
    Unbekannte Rollen fallen auf "Allgemein" zurück; unbekannte Regionen auf
    den deutschen Bundesdurchschnitt (Faktor 1.0).

    Args:
        rolle:   Rollenbezeichnung, muss in ROLLEN_STUNDENSATZ_DE vorkommen.
        region:  ISO 3166-2 Regionscode (z.B. "DE", "DE-BY", "AT", "CH").

    Returns:
        Stundensatz in EUR/h als Float.
    """
    basis = ROLLEN_STUNDENSATZ_DE.get(rolle, ROLLEN_STUNDENSATZ_DE["Allgemein"])

    # Regionscode normalisieren: "at" → "AT", "de-by" → "DE-BY"
    region_norm = (region or "DE").upper()

    faktor = REGION_FAKTOR.get(region_norm)
    if faktor is None:
        # Fallback: Land-Prefix (z.B. "DE-XY" → "DE")
        land_prefix = region_norm[:2]
        faktor = REGION_FAKTOR.get(land_prefix, 1.0)

    return round(basis * faktor, 2)


def get_gewichteter_stundensatz(beschreibung: str, region: str) -> dict:
    """
    Berechnet den gewichteten Stundensatz für ein Projekt.

    Erkennt den Projekttyp aus der Beschreibung, bestimmt die passende
    Team-Komposition und berechnet den anteilsgewichteten Stundensatz.

    Args:
        beschreibung: Freitext der Projektbeschreibung.
        region:       ISO 3166-2 Regionscode (z.B. "DE", "DE-BY", "AT", "CH").

    Returns:
        Dict mit:
          - "gewichteter_satz"  (float): anteilsgewichteter EUR/h-Satz
          - "rollen"            (list):  [{"rolle": str, "anteil": float,
                                           "stundensatz": float}, ...]
          - "komposition_typ"   (str):   erkannter Projekttyp (z.B. "sap")
    """
    text = (beschreibung or "").lower()

    # Kompositionstyp ermitteln
    komposition_typ = "allgemein"
    for muster, key in BESCHREIBUNG_ZU_KOMPOSITION:
        if re.search(muster, text):
            komposition_typ = key
            break

    komposition = TEAM_KOMPOSITION[komposition_typ]

    # Stundensatz je Rolle berechnen und gewichteten Gesamt-Satz ermitteln
    rollen_detail: list[dict] = []
    gewichteter_satz = 0.0

    for rolle, anteil in komposition:
        satz = get_stundensatz(rolle, region)
        rollen_detail.append({
            "rolle":       rolle,
            "anteil":      anteil,
            "stundensatz": satz,
        })
        gewichteter_satz += anteil * satz

    return {
        "gewichteter_satz": round(gewichteter_satz, 2),
        "rollen":           rollen_detail,
        "komposition_typ":  komposition_typ,
    }
