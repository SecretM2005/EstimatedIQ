"""
EstimateIQ – Deterministische Kostenschätzungs-Pipeline.

Pipeline:
  Schritt 1: Laufzeit schätzen (ML)
    dauer_tage = duration_model.predict(beschreibung, cpv_code, land)

  Schritt 2: Kosten deterministisch berechnen
    technologie    = Keyword-Erkennung aus Beschreibung
    stundensatz    = salary_lookup.get(region, technologie)
    teamgroesse    = extract_teamgroesse(beschreibung)  # Fallback: 2
    overhead       = overhead_lookup.get(projekttyp)    # Web=1.3, ML=1.6, SAP=1.8
    personalkosten = dauer_tage × teamgroesse × stundensatz × 8h
    kosten         = personalkosten × overhead

  Schritt 3: Kostenbänder (±20 % / ±40 %)
    kosten_low/high  = kosten × [0.8, 1.4]
    kosten_min/max   = kosten × [0.6, 2.0]

Verwendung:
  from estimateiq.models.estimate_pipeline import estimate, PipelineErgebnis

  ergebnis = estimate(
      beschreibung="SAP S/4HANA Migration für 500 Nutzer...",
      cpv_code="72200000",
      land="DE",
      region="DE-BY",
  )
  print(f"Geschätzte Kosten: {ergebnis.kosten_expected:,.0f} €")
  print(f"Bereich: {ergebnis.kosten_low:,.0f} – {ergebnis.kosten_high:,.0f} €")
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

STUNDEN_PRO_TAG = 8.0

# Skalierungsfaktoren je Projektgröße
# "klein": Freelancer/Solo bis ~3 Monate; "mittel": Standardprojekt; "gross": Enterprise
GROESSE_TEAM_FAKTOR: dict[str, float] = {
    "klein":  0.40,
    "mittel": 1.00,
    "gross":  1.60,
}
GROESSE_DAUER_HINWEIS: dict[str, str] = {
    "klein":  "⚠ Kleine Projekte werden vom Modell tendenziell überschätzt.",
    "mittel": "",
    "gross":  "",
}

# TED-Ausschreibungen enthalten Wartungs-/Betriebsphasen und Vergabe-Puffer.
# Die reale Entwicklungszeit im Privatmarkt beträgt ca. 35–65 % der Ausschreibungslaufzeit.
DAUER_KALIBRIERUNG: dict[str, float] = {
    "klein":  0.35,   # kurze Projekte: ~35 % der TED-Laufzeit
    "mittel": 0.45,   # Standardprojekte: ~45 %
    "gross":  0.65,   # Enterprise (inkl. Rollout): ~65 %
}

# Kalibrierungsfaktoren für spezialisierte Modelle
# Nach Integration von 2.000 synthetischen DACH-Projekten sind die Modelle
# bereits auf realistische Dauern kalibriert – kein zusätzlicher Abzug nötig.
KALIBRIERUNG_SPEZIALISIERT: dict[str, float] = {
    "klein":  1.0,
    "mittel": 1.0,
    "gross":  1.0,
}

# Bevorzugte Datenquelle für Inferenz je Grössenklasse
DATENQUELLE_MODELL: dict[str, str] = {
    "klein":  "github",
    "mittel": "github",
    "gross":  "ted",
}

# Overhead-Faktor je Projekttyp (deterministisch, kein ML)
# Quelle: Destatis Branchenstruktur + Erfahrungswerte DACH IT-Markt
OVERHEAD_FAKTOREN: dict[str, float] = {
    "Softwareentwicklung":           1.3,
    "Internet- & Cloud-Dienste":     1.3,
    "IT-Betrieb & Wartung":          1.2,
    "IT-Beratung & Support":         1.2,
    "Datenverarbeitung & Analytics": 1.6,
    "IT-Prüfung & Testing":          1.3,
    "Netzwerk & Infrastruktur":      1.4,
    "Datenmigration & Backup":       1.5,
    "IT-Hardware & Systeme":         1.3,
    "Sonstige IT":                   1.3,
}

# CPV-Code → Projekttyp (aus preprocess.py gespiegelt)
_CPV_PROJEKTTYPEN: list[tuple[range, str]] = [
    (range(72200000, 72300000), "Softwareentwicklung"),
    (range(72300000, 72400000), "Datenverarbeitung & Analytics"),
    (range(72400000, 72500000), "Internet- & Cloud-Dienste"),
    (range(72500000, 72600000), "IT-Betrieb & Wartung"),
    (range(72600000, 72700000), "IT-Beratung & Support"),
    (range(72700000, 72800000), "Netzwerk & Infrastruktur"),
    (range(72800000, 72900000), "IT-Prüfung & Testing"),
    (range(72900000, 72999999), "Datenmigration & Backup"),
    (range(72000000, 72200000), "IT-Hardware & Systeme"),
]


def _cpv_zu_projekttyp(cpv_code: str | int | None) -> str:
    if cpv_code is None:
        return "Softwareentwicklung"
    try:
        code = int(str(cpv_code).replace("-", "")[:8])
        for bereich, label in _CPV_PROJEKTTYPEN:
            if code in bereich:
                return label
    except (ValueError, TypeError):
        pass
    return "Softwareentwicklung"


def _team_effizienz(n: float) -> float:
    """Effektive Produktivität pro Person bei Teamgröße n.
    Modelliert Koordinationsaufwand und nicht parallelisierbare Aufgaben (Brooks's Law).
    n=1: 100 %, n=2: 95 %, n=5: 83 %, n=10: 69 %
    """
    return max(0.40, 1.0 / (1.0 + 0.05 * max(0.0, n - 1.0)))


def _overhead_faktor(beschreibung: str, projekttyp: str) -> float:
    """Bestimmt Overhead-Faktor aus Projekttyp mit SAP/Mobile-Keyword-Vorrang."""
    text = (beschreibung or "").lower()
    if re.search(r"\bsap\b", text):
        return 1.8
    if re.search(r"\b(mobil|mobile|ios|android|flutter|react\s*native)\b", text):
        return 1.4
    return OVERHEAD_FAKTOREN.get(projekttyp, 1.3)


def _extrahiere_technologie(beschreibung: str) -> str:
    """
    Erkennt dominante Technologie aus Freitext.
    Gibt SO-Survey-Kategorienamen zurück (für stundensaetze_stackoverflow.json).
    """
    text = (beschreibung or "").lower()
    # Reihenfolge: Spezifischste zuerst
    if re.search(r"\bsap\b", text):
        return "SAP"
    if re.search(r"\b(mobil|mobile|ios|android|flutter|swift|react[\s-]native)\b", text):
        return "Mobile"
    if re.search(r"\b(python|ml|machine.?learning|pytorch|tensorflow|scikit|nlp)\b", text):
        return "Python/ML"
    if re.search(r"\b(rust|go(?:lang)?|c\+\+)\b", text):
        return "Backend"
    if re.search(r"\b(c#|\.net|aspnet|blazor|dotnet)\b", text):
        return ".NET"
    if re.search(r"\b(typescript|angular|react|vue|node\.?js|next\.?js)\b", text):
        return "JavaScript"
    if re.search(r"\b(javascript|js\b)\b", text):
        return "JavaScript"
    if re.search(r"\b(java|spring|quarkus|jakarta)\b", text):
        return "Java"
    if re.search(r"\b(php|wordpress|symfony|laravel|woocommerce)\b", text):
        return "PHP"
    return "Allgemein"


# ---------------------------------------------------------------------------
# Ergebnis-Datenklasse
# ---------------------------------------------------------------------------

@dataclass
class PipelineErgebnis:
    """Vollständiges Schätzungsergebnis der zweistufigen Pipeline."""

    # Stufe 1: Laufzeit
    dauer_tage: float

    # Stufe 2: Tagespreis (EUR/Tag) – Hauptschätzgröße
    tagespreis_p10: float
    tagespreis_p25: float
    tagespreis_p50: float
    tagespreis_p75: float
    tagespreis_p90: float

    # Stufe 3: Gesamtkosten (dauer_tage × tagespreis_pXX)
    kosten_min:      float   # dauer_tage × tagespreis_p10
    kosten_low:      float   # dauer_tage × tagespreis_p25
    kosten_expected: float   # dauer_tage × tagespreis_p50
    kosten_high:     float   # dauer_tage × tagespreis_p75
    kosten_max:      float   # dauer_tage × tagespreis_p90

    # Reporting: Personalkosten-Ausweis (nicht für Kostenschätzung verwendet)
    teamgroesse: float
    stundensatz_eur_h: float
    personalkosten: float

    # Metadaten (keine Defaults)
    region: str
    projekttyp: str
    cpv_code: str

    # Felder mit Defaults müssen ans Ende
    teamgroesse_modell: float  = 0.0    # was das Modell ohne Override empfiehlt
    team_assessment:    str | None = None  # "passend" | "zu_klein" | "zu_gross"
    stundensatz_quelle: str = ""
    projekt_groesse: str = "mittel"

    # Neu: Grössenklassifikator-Konfidenz und Auto-Erkennungs-Flag
    groesse_konfidenz:   float = 0.0   # Konfidenz des ML-Klassifikators (0.0 = manuell/Fallback)
    groesse_auto_erkannt: bool = False  # True wenn Grösse via Klassifikator bestimmt wurde

    # Rückwärtskompatibilität: overhead_faktor_p50 = tagespreis_p50 / (team × stundensatz × 8)
    @property
    def overhead_faktor_p50(self) -> float:
        basis = self.personalkosten
        if basis > 0:
            return self.kosten_expected / basis
        return 1.0

    def als_dict(self) -> dict[str, Any]:
        return {
            "dauer_tage":            round(self.dauer_tage),
            "tagespreis_p25":        round(self.tagespreis_p25, 0),
            "tagespreis_p50":        round(self.tagespreis_p50, 0),
            "tagespreis_p75":        round(self.tagespreis_p75, 0),
            "teamgroesse":           round(self.teamgroesse, 1),
            "teamgroesse_modell":    round(self.teamgroesse_modell or self.teamgroesse, 1),
            "team_assessment":       self.team_assessment,
            "stundensatz_eur_h":     round(self.stundensatz_eur_h, 1),
            "personalkosten":        round(self.personalkosten, 0),
            "kosten_min":            round(self.kosten_min, 0),
            "kosten_low":            round(self.kosten_low, 0),
            "kosten_expected":       round(self.kosten_expected, 0),
            "kosten_high":           round(self.kosten_high, 0),
            "kosten_max":            round(self.kosten_max, 0),
            "region":                self.region,
            "projekttyp":            self.projekttyp,
            "projekt_groesse":       self.projekt_groesse,
            "groesse_konfidenz":     round(self.groesse_konfidenz, 3),
            "groesse_auto_erkannt":  self.groesse_auto_erkannt,
        }


# ---------------------------------------------------------------------------
# Lazy-geladene Modell-Singletons
# ---------------------------------------------------------------------------

_duration_modell_cache: dict = {}


def _lade_duration_modell():
    if not _duration_modell_cache:
        from estimateiq.models.duration_model import (
            predict as _predict,
            _lade_modell as _lm,
            _feature_engineering as _fe,
            _erstelle_feature_matrix as _fm,
        )
        _duration_modell_cache["predict"]          = _predict
        _duration_modell_cache["_lade_modell"]     = _lm
        _duration_modell_cache["_feature_eng"]     = _fe
        _duration_modell_cache["_feature_matrix"]  = _fm
    return _duration_modell_cache


def _lade_overhead_modell():
    """Stub für Rückwärtskompatibilität – Overhead wird jetzt deterministisch berechnet."""
    return {}


def _lade_v3_modell():
    """Stub für Rückwärtskompatibilität – v3 nicht mehr im Ensemble."""
    return {}


def _klassifiziere_groesse(beschreibung: str) -> tuple[str, float]:
    """
    Klassifiziert Projektgrösse via ML-Modell.

    Gibt (groesse, konfidenz) zurück, z.B. ("klein", 0.82).
    Fällt auf "mittel" + 0.0 zurück wenn Modell fehlt oder ein Fehler auftritt.

    Args:
        beschreibung: Projektbeschreibungstext

    Returns:
        Tupel (groesse, konfidenz): groesse in {"klein", "mittel", "gross"},
        konfidenz zwischen 0.0 und 1.0
    """
    try:
        from estimateiq.models.size_classifier import predict_proba as _proba
        result = _proba([beschreibung])[0]
        groesse = max(result, key=result.get)
        konfidenz = result[groesse]
        logger.debug(
            "[Pipeline] ML-Grössenklassifikation: %s (Konfidenz %.1f%%) | klein=%.2f mittel=%.2f gross=%.2f",
            groesse, konfidenz * 100,
            result.get("klein", 0), result.get("mittel", 0), result.get("gross", 0),
        )
        return groesse, round(konfidenz, 3)
    except FileNotFoundError:
        logger.debug("[Pipeline] Grössenklassifikator nicht trainiert – Fallback auf 'mittel'.")
        return "mittel", 0.0
    except Exception as exc:
        logger.debug("[Pipeline] Grössenklassifikator-Fehler: %s – Fallback auf 'mittel'.", exc)
        return "mittel", 0.0


def _lade_duration_modell_spezialisiert(groesse: str):
    """
    Versucht das spezialisierte Laufzeit-Modell für die angegebene Grössenklasse zu laden.

    Args:
        groesse: "klein", "mittel" oder "gross"

    Returns:
        predict-Funktion des spezialisierten Modells, oder None bei Fehler/nicht vorhanden.
    """
    try:
        if groesse == "klein":
            from estimateiq.models.duration_model_klein import predict as _pred
            return _pred
        elif groesse == "mittel":
            from estimateiq.models.duration_model_mittel import predict as _pred
            return _pred
        elif groesse == "gross":
            from estimateiq.models.duration_model_gross import predict as _pred
            return _pred
    except (FileNotFoundError, ImportError) as exc:
        logger.debug(
            "[Pipeline] Spezialisiertes Modell für '%s' nicht verfügbar (%s) – "
            "Fallback auf generisches Modell.",
            groesse, type(exc).__name__,
        )
    return None


# ---------------------------------------------------------------------------
# Kern-Funktion: estimate()
# ---------------------------------------------------------------------------

def estimate(
    beschreibung: str,
    cpv_code: str | int | None = None,
    land: str = "DE",
    region: str = "DE",
    datenquelle: str = "ted",
    dauer_override: float | None = None,
    projekt_groesse: str = "mittel",
    teamgroesse_override: float | None = None,
    projekt_groesse_auto: bool = True,
    groesse_konfidenz_override: float | None = None,
) -> PipelineErgebnis:
    """
    Schätzt Projektkosten via deterministischer Pipeline.

    Args:
        beschreibung:              Volltext der Ausschreibung (min. 5 Zeichen)
        cpv_code:                  CPV-Code (Optional, Standard: 72200000)
        land:                      2-Buchstaben-Ländercode für Datensatz (DE/AT/CH)
        region:                    ISO 3166-2 für Gehaltssuche (DE, DE-BY, AT, CH, ...)
        datenquelle:               Herkunft (ted/promise/github)
        dauer_override:            Laufzeit in Tagen falls bekannt (überspringt Stufe 1)
        projekt_groesse:           "klein" (Freelancer/Solo), "mittel" (Standard), "gross" (Enterprise)
        teamgroesse_override:      Verfügbare Teamgrösse in Personen; löst Assessment aus wenn gesetzt
        projekt_groesse_auto:      True = ML-Klassifikator nutzen wenn projekt_groesse=="mittel" (Default);
                                   False = immer den übergebenen Wert nutzen
        groesse_konfidenz_override: Optionale manuelle Konfidenz (nur für Tests/Debugging)

    Returns:
        PipelineErgebnis mit allen Kostenpositionen
    """
    if not beschreibung or len(beschreibung) < 5:
        raise ValueError("beschreibung muss mindestens 5 Zeichen lang sein.")

    cpv_str    = str(cpv_code or "72200000")
    projekttyp = _cpv_zu_projekttyp(cpv_str)
    land_upper = (land or "DE").upper()[:2]
    groesse_key = projekt_groesse if projekt_groesse in GROESSE_TEAM_FAKTOR else "mittel"

    # Auto-Erkennung der Projektgrösse via ML-Klassifikator
    # Nur wenn: Auto-Mode aktiv UND Nutzer hat keinen expliziten Wert ungleich "mittel" übergeben
    groesse_konfidenz   = groesse_konfidenz_override or 0.0
    groesse_auto_erkannt = False

    if projekt_groesse_auto and projekt_groesse == "mittel":
        erkannte_groesse, erkannte_konfidenz = _klassifiziere_groesse(beschreibung)
        # Klassifikator-Ergebnis nur übernehmen wenn Konfidenz > 0 (Modell vorhanden)
        if erkannte_konfidenz > 0:
            groesse_key           = erkannte_groesse
            groesse_konfidenz     = erkannte_konfidenz
            groesse_auto_erkannt  = True
            logger.debug(
                "[Pipeline] Grösse auto-erkannt: %s (Konfidenz %.1f%%)",
                groesse_key, groesse_konfidenz * 100,
            )

    # ----- Schritt 1: Gesamtaufwand schätzen (Personentage) -----
    # Das ML-Modell liefert eine Laufzeit auf TED-Skala; kalibriert ergibt das
    # den Gesamtaufwand in Personentagen für den Privatmarkt.
    if dauer_override is not None:
        effort_tage = None  # wird nach Teamgrösse gesetzt (Laufzeit ist fest)
    else:
        # Spezialisiertes Modell für erkannte Grössenklasse versuchen
        spez_datenquelle = DATENQUELLE_MODELL.get(groesse_key, datenquelle)
        df_dur = pd.DataFrame([{
            "beschreibung": beschreibung,
            "cpv_code":     cpv_str,
            "land":         land_upper,
            "projekttyp":   projekttyp,
            "datenquelle":  spez_datenquelle,
        }])

        spez_predict = _lade_duration_modell_spezialisiert(groesse_key)
        if spez_predict is not None:
            # Spezialisiertes Modell: Kalibrierung aus KALIBRIERUNG_SPEZIALISIERT
            kalibrierung = KALIBRIERUNG_SPEZIALISIERT.get(groesse_key, 1.0)
            pred        = spez_predict(df_dur)
            effort_tage = max(3.0, float(pred[0]) * kalibrierung)
            logger.debug(
                "[Pipeline] Spez. Laufzeit-Modell (%s): %d Tage × Kalibrierung %.2f = %d Personentage",
                groesse_key, round(float(pred[0])), kalibrierung, round(effort_tage),
            )
        else:
            # Generisches Modell als Fallback
            dur_cache = _lade_duration_modell()
            df_dur_generic = pd.DataFrame([{
                "beschreibung": beschreibung,
                "cpv_code":     cpv_str,
                "land":         land_upper,
                "projekttyp":   projekttyp,
                "datenquelle":  datenquelle,
            }])
            pred        = dur_cache["predict"](df_dur_generic)
            effort_tage = max(3.0, float(pred[0]) * DAUER_KALIBRIERUNG.get(groesse_key, 0.45))
            logger.debug("[Pipeline] Generisches Modell: %d Personentage", round(effort_tage))

    # ----- Schritt 2: Team & Effizienz -----
    from estimateiq.models.overhead_model import extract_teamgroesse
    teamgroesse_basis  = extract_teamgroesse(beschreibung, projekttyp)
    teamgroesse_modell = max(1.0, teamgroesse_basis * GROESSE_TEAM_FAKTOR[groesse_key])

    if teamgroesse_override is not None and teamgroesse_override > 0:
        teamgroesse = float(teamgroesse_override)
        ratio = teamgroesse / teamgroesse_modell
        team_assessment: str | None = (
            "zu_gross" if ratio >= 1.5  else
            "zu_klein" if ratio <= 0.65 else
            "passend"
        )
    else:
        teamgroesse     = teamgroesse_modell
        team_assessment = None

    # ----- Schritt 3: Laufzeit aus Aufwand und Teameffizienz ableiten -----
    # dauer = effort / (n × effizienz(n))
    # effizienz(n) < 1: Koordinationsaufwand, nicht-parallele Aufgaben, Ramp-up.
    if effort_tage is None:
        # dauer_override: Laufzeit fest, Aufwand ergibt sich
        dauer_tage  = float(dauer_override)  # type: ignore[arg-type]
    else:
        effizienz_kapazitaet = teamgroesse * _team_effizienz(teamgroesse)
        dauer_tage = max(3.0, effort_tage / effizienz_kapazitaet)
        logger.debug(
            "[Pipeline] Laufzeit: %.0f Tage (Aufwand %d × %.1f Pers. × eff %.2f = %.1f Kap.)",
            dauer_tage, round(effort_tage), teamgroesse,
            _team_effizienz(teamgroesse), effizienz_kapazitaet,
        )

    technologie = _extrahiere_technologie(beschreibung)

    # Stundensatz: SO-Survey-JSON → fetch_salary_data → Fallback
    try:
        from estimateiq.data.fetch_stackoverflow import lookup as _so_lookup
        salary_info   = _so_lookup(region, technologie)
        stundensatz   = salary_info["median"]
        salary_quelle = salary_info["quelle"]
    except Exception:
        try:
            from estimateiq.data.fetch_salary_data import get_stundensatz as _get_stundensatz
            salary_info   = _get_stundensatz(region, technologie)
            stundensatz   = salary_info["stundensatz_median"]
            salary_quelle = salary_info["quelle"]
        except Exception:
            stundensatz   = 47.5
            salary_quelle = "hardcoded_fallback"

    overhead       = _overhead_faktor(beschreibung, projekttyp)
    personalkosten = dauer_tage * teamgroesse * stundensatz * STUNDEN_PRO_TAG
    kosten_base    = personalkosten * overhead

    # Tagespreis-Äquivalent (für Berichtsfelder)
    tagespreis_p50 = teamgroesse * stundensatz * STUNDEN_PRO_TAG * overhead

    # ----- Schritt 3: Kostenbänder -----
    # p10 × 0.6 | p25 × 0.8 | p50 × 1.0 | p75 × 1.4 | p90 × 2.0
    kosten_min      = kosten_base * 0.6
    kosten_low      = kosten_base * 0.8
    kosten_expected = kosten_base
    kosten_high     = kosten_base * 1.4
    kosten_max      = kosten_base * 2.0

    logger.debug(
        "[Pipeline] %d Tage × %d Pers. × %.1f €/h × %gh × OH %.1f → %,.0f € [%,.0f – %,.0f €]",
        round(dauer_tage), round(teamgroesse), stundensatz, STUNDEN_PRO_TAG,
        overhead, kosten_expected, kosten_low, kosten_high,
    )

    return PipelineErgebnis(
        dauer_tage           = round(dauer_tage, 1),
        tagespreis_p10       = round(tagespreis_p50 * 0.6, 2),
        tagespreis_p25       = round(tagespreis_p50 * 0.8, 2),
        tagespreis_p50       = round(tagespreis_p50, 2),
        tagespreis_p75       = round(tagespreis_p50 * 1.4, 2),
        tagespreis_p90       = round(tagespreis_p50 * 2.0, 2),
        kosten_min           = round(kosten_min, 2),
        kosten_low           = round(kosten_low, 2),
        kosten_expected      = round(kosten_expected, 2),
        kosten_high          = round(kosten_high, 2),
        kosten_max           = round(kosten_max, 2),
        teamgroesse          = round(teamgroesse, 1),
        stundensatz_eur_h    = round(stundensatz, 2),
        personalkosten       = round(personalkosten, 2),
        region               = region,
        projekttyp           = projekttyp,
        cpv_code             = cpv_str,
        stundensatz_quelle   = salary_quelle,
        projekt_groesse      = groesse_key,
        teamgroesse_modell   = round(teamgroesse_modell, 1),
        team_assessment      = team_assessment,
        groesse_konfidenz    = groesse_konfidenz,
        groesse_auto_erkannt = groesse_auto_erkannt,
    )


def estimate_batch(
    df: pd.DataFrame,
    region_col: str = "land",
    default_region: str = "DE",
    verwende_tatsaechliche_dauer: bool = False,
    projekt_groesse: str = "mittel",
) -> list[PipelineErgebnis]:
    """
    Batch-Schätzung für einen DataFrame.
    Erwartet Spalten: beschreibung, cpv_code, land, [projekttyp], [datenquelle].

    Args:
        verwende_tatsaechliche_dauer: Falls True, wird dauer_tage aus dem DataFrame
            als dauer_override übergeben (nur für Diagnose/Ablation, nicht für echte Validierung).
            Standard: False — immer Stufe 1 verwenden.
        projekt_groesse: "klein" / "mittel" / "gross" für alle Zeilen (oder je Zeile aus Spalte).
    """
    ergebnisse = []
    for _, zeile in df.iterrows():
        try:
            region = str(zeile.get(region_col) or default_region)

            dauer_ov = None
            if verwende_tatsaechliche_dauer and "dauer_tage" in zeile and pd.notna(zeile["dauer_tage"]):
                dauer_ov = float(zeile["dauer_tage"])

            # projekt_groesse kann aus Zeile kommen oder als Fallback-Default
            groesse = str(zeile.get("projekt_groesse") or projekt_groesse)

            ergebnis = estimate(
                beschreibung    = str(zeile.get("beschreibung", "")),
                cpv_code        = zeile.get("cpv_code"),
                land            = str(zeile.get("land") or "DE"),
                region          = region,
                datenquelle     = str(zeile.get("datenquelle") or "ted"),
                dauer_override  = dauer_ov,
                projekt_groesse = groesse,
            )
        except Exception as exc:
            logger.warning("[Pipeline Batch] Fehler bei Zeile: %s", exc)
            ergebnis = None
        ergebnisse.append(ergebnis)
    return ergebnisse
