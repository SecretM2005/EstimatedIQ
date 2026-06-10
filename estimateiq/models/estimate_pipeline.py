"""
EstimateIQ – Zweistufige Kostenschätzungs-Pipeline.

Pipeline:
  Schritt 1: Laufzeit schätzen
    dauer_tage = duration_model.predict(beschreibung, cpv_code, land)

  Schritt 2: Personalkosten berechnen
    teamgroesse     = extract_teamgroesse(beschreibung, projekttyp)
    stundensatz     = get_stundensatz(region)["stundensatz_median"]
    personalkosten  = dauer_tage × teamgroesse × stundensatz × 8 h/Tag

  Schritt 3: Overhead-Faktor schätzen
    overhead = overhead_model.predict(...)   → {p25, p50, p75}

  Schritt 4: Gesamtkosten berechnen
    kosten_min      = personalkosten × overhead.p25
    kosten_expected = personalkosten × overhead.p50
    kosten_max      = personalkosten × overhead.p75

Verwendung:
  from estimateiq.models.estimate_pipeline import estimate, PipelineErgebnis

  ergebnis = estimate(
      beschreibung="SAP S/4HANA Migration für 500 Nutzer...",
      cpv_code="72200000",
      land="DE",
      region="DE-BY",
  )
  print(f"Geschätzte Kosten: {ergebnis.kosten_expected:,.0f} €")
  print(f"Bereich: {ergebnis.kosten_min:,.0f} – {ergebnis.kosten_max:,.0f} €")
"""

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# Ergebnis-Datenklasse
# ---------------------------------------------------------------------------

@dataclass
class PipelineErgebnis:
    """Vollständiges Schätzungsergebnis der zweistufigen Pipeline."""

    # Stufe 1: Laufzeit
    dauer_tage: float

    # Stufe 2: Personalkosten
    teamgroesse: float
    stundensatz_eur_h: float
    personalkosten: float

    # Stufe 3: Overhead
    overhead_faktor_p10: float
    overhead_faktor_p25: float
    overhead_faktor_p50: float
    overhead_faktor_p75: float
    overhead_faktor_p90: float

    # Stufe 4: Gesamtkosten
    kosten_min:      float   # personalkosten × overhead.p10
    kosten_low:      float   # personalkosten × overhead.p25
    kosten_expected: float   # personalkosten × overhead.p50
    kosten_high:     float   # personalkosten × overhead.p75
    kosten_max:      float   # personalkosten × overhead.p90

    # Metadaten
    region: str
    projekttyp: str
    cpv_code: str
    stundensatz_quelle: str = ""

    def als_dict(self) -> dict[str, Any]:
        return {
            "dauer_tage":            round(self.dauer_tage),
            "teamgroesse":           round(self.teamgroesse, 1),
            "stundensatz_eur_h":     round(self.stundensatz_eur_h, 1),
            "personalkosten":        round(self.personalkosten, 0),
            "overhead_faktor_p25":   round(self.overhead_faktor_p25, 3),
            "overhead_faktor_p50":   round(self.overhead_faktor_p50, 3),
            "overhead_faktor_p75":   round(self.overhead_faktor_p75, 3),
            "kosten_min":            round(self.kosten_min, 0),
            "kosten_low":            round(self.kosten_low, 0),
            "kosten_expected":       round(self.kosten_expected, 0),
            "kosten_high":           round(self.kosten_high, 0),
            "kosten_max":            round(self.kosten_max, 0),
            "region":                self.region,
            "projekttyp":            self.projekttyp,
        }


# ---------------------------------------------------------------------------
# Lazy-geladene Modell-Singletons
# ---------------------------------------------------------------------------

_duration_modell_cache: dict = {}
_overhead_modell_cache: dict = {}


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
    if not _overhead_modell_cache:
        from estimateiq.models.overhead_model import (
            predict as _predict,
            _feature_engineering as _fe,
            _erstelle_feature_matrix as _fm,
            berechne_personalkosten,
        )
        _overhead_modell_cache["predict"]         = _predict
        _overhead_modell_cache["_feature_eng"]    = _fe
        _overhead_modell_cache["_feature_matrix"] = _fm
        _overhead_modell_cache["personalkosten"]  = berechne_personalkosten
    return _overhead_modell_cache


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
) -> PipelineErgebnis:
    """
    Schätzt Projektkosten via zweistufiger Pipeline.

    Args:
        beschreibung:   Volltext der Ausschreibung (min. 30 Zeichen)
        cpv_code:       CPV-Code (Optional, Standard: 72200000)
        land:           2-Buchstaben-Ländercode für Datensatz (DE/AT/CH)
        region:         ISO 3166-2 für Gehaltssuche (DE, DE-BY, AT, CH, ...)
        datenquelle:    Herkunft (ted/promise/github)
        dauer_override: Laufzeit in Tagen falls bekannt (überspringt Stufe 1)

    Returns:
        PipelineErgebnis mit allen Kostenpositionen
    """
    if not beschreibung or len(beschreibung) < 5:
        raise ValueError("beschreibung muss mindestens 5 Zeichen lang sein.")

    cpv_str = str(cpv_code or "72200000")
    projekttyp = _cpv_zu_projekttyp(cpv_str)
    land_upper = (land or "DE").upper()[:2]

    # ----- Schritt 1: Laufzeit -----
    if dauer_override is not None:
        dauer_tage = float(dauer_override)
        logger.debug("[Pipeline] Laufzeit (überschrieben): %d Tage", round(dauer_tage))
    else:
        dur_cache = _lade_duration_modell()
        df_dur = pd.DataFrame([{
            "beschreibung": beschreibung,
            "cpv_code":     cpv_str,
            "land":         land_upper,
            "projekttyp":   projekttyp,
            "datenquelle":  datenquelle,
        }])
        pred = dur_cache["predict"](df_dur)
        dauer_tage = float(pred[0])
        logger.debug("[Pipeline] Laufzeit geschätzt: %d Tage", round(dauer_tage))

    # ----- Schritt 2: Personalkosten -----
    from estimateiq.models.overhead_model import extract_teamgroesse, berechne_personalkosten

    teamgroesse = extract_teamgroesse(beschreibung, projekttyp)

    try:
        from estimateiq.data.fetch_salary_data import get_stundensatz as _get_stundensatz
        salary_info  = _get_stundensatz(region, "all")
        stundensatz  = salary_info["stundensatz_median"]
        salary_quelle = salary_info["quelle"]
    except Exception:
        stundensatz   = 47.5  # DACH-Fallback DE
        salary_quelle = "hardcoded_fallback"

    personalkosten = berechne_personalkosten(dauer_tage, teamgroesse, stundensatz)
    logger.debug(
        "[Pipeline] Personalkosten: %d Tage × %.1f Pers. × %.1f €/h × 8h = %,.0f €",
        round(dauer_tage), teamgroesse, stundensatz, personalkosten,
    )

    # ----- Schritt 3: Overhead-Faktor -----
    oh_cache = _lade_overhead_modell()
    df_oh = pd.DataFrame([{
        "beschreibung": beschreibung,
        "cpv_code":     cpv_str,
        "land":         land_upper,
        "projekttyp":   projekttyp,
        "datenquelle":  datenquelle,
        "dauer_tage":   dauer_tage,
    }])
    overhead_liste = oh_cache["predict"](df_oh)
    overhead = overhead_liste[0]

    # ----- Schritt 4: Gesamtkosten -----
    kosten_min      = personalkosten * overhead["p10"]
    kosten_low      = personalkosten * overhead["p25"]
    kosten_expected = personalkosten * overhead["p50"]
    kosten_high     = personalkosten * overhead["p75"]
    kosten_max      = personalkosten * overhead["p90"]

    logger.debug(
        "[Pipeline] Overhead p50=%.2f× → Erwartet: %,.0f € [%,.0f – %,.0f €]",
        overhead["p50"], kosten_expected, kosten_low, kosten_high,
    )

    return PipelineErgebnis(
        dauer_tage           = round(dauer_tage, 1),
        teamgroesse          = round(teamgroesse, 1),
        stundensatz_eur_h    = round(stundensatz, 2),
        personalkosten       = round(personalkosten, 2),
        overhead_faktor_p10  = round(overhead["p10"], 4),
        overhead_faktor_p25  = round(overhead["p25"], 4),
        overhead_faktor_p50  = round(overhead["p50"], 4),
        overhead_faktor_p75  = round(overhead["p75"], 4),
        overhead_faktor_p90  = round(overhead["p90"], 4),
        kosten_min           = round(kosten_min, 2),
        kosten_low           = round(kosten_low, 2),
        kosten_expected      = round(kosten_expected, 2),
        kosten_high          = round(kosten_high, 2),
        kosten_max           = round(kosten_max, 2),
        region               = region,
        projekttyp           = projekttyp,
        cpv_code             = cpv_str,
        stundensatz_quelle   = salary_quelle,
    )


def estimate_batch(
    df: pd.DataFrame,
    region_col: str = "land",
    default_region: str = "DE",
) -> list[PipelineErgebnis]:
    """
    Batch-Schätzung für einen DataFrame.
    Erwartet Spalten: beschreibung, cpv_code, land, [projekttyp], [datenquelle].
    """
    ergebnisse = []
    for _, zeile in df.iterrows():
        try:
            region = str(zeile.get(region_col) or default_region)
            ergebnis = estimate(
                beschreibung = str(zeile.get("beschreibung", "")),
                cpv_code     = zeile.get("cpv_code"),
                land         = str(zeile.get("land") or "DE"),
                region       = region,
                datenquelle  = str(zeile.get("datenquelle") or "ted"),
                dauer_override = (
                    float(zeile["dauer_tage"])
                    if "dauer_tage" in zeile and pd.notna(zeile["dauer_tage"])
                    else None
                ),
            )
        except Exception as exc:
            logger.warning("[Pipeline Batch] Fehler bei Zeile: %s", exc)
            ergebnis = None
        ergebnisse.append(ergebnis)
    return ergebnisse
