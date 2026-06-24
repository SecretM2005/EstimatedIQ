"""
PROMISE Repository Connector – lädt Software-Schätzungsdatensätze von Derek Jones' GitHub.
https://github.com/Derek-Jones/Software-estimation-datasets

Konvertiert Effort-Metriken (Person-Hours / Person-Months) in EUR-Budgets:
  Budget = Effort_in_Stunden × STUNDENSATZ_DACH (85 €/h)

Ausgabe: data/raw_promise.jsonl (kompatibel mit preprocess.py)
"""

import json
import logging
import time
from io import StringIO
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

STUNDENSATZ_DACH: float = 85.0
STUNDEN_PRO_MONAT: int  = 152   # Produktive Stunden/Monat (20 Tage × 7,6 h)

GITHUB_API     = "https://api.github.com"
REPO_OWNER     = "Derek-Jones"
REPO_NAME      = "Software-estimation-datasets"
RAW_BASE_URL   = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/master"

RAW_DATA_DIR   = Path("data")
OUTPUT_FILE    = RAW_DATA_DIR / "raw_promise.jsonl"

# ---------------------------------------------------------------------------
# Dataset-Konfiguration – Spaltenmappings je Datei
# ---------------------------------------------------------------------------
# effort_col:   Spaltenname für Aufwand (Pflichtfeld)
# effort_unit:  "hours" | "months"  (Stunden direkt vs. Personenmonate × 152)
# duration_col: Spalte für Laufzeit (optional)
# duration_unit:"months" | "days"
# name_cols:    Spalten für den Projektnamen (in Reihenfolge)
# type_col:     Projekttypbezeichnung
# domain:       Fachbereich als Text-Default
# cpv_default:  Fallback-CPV falls kein Typ erkennbar

DATASET_CONFIG: dict[str, dict[str, Any]] = {
    "desharnais.csv": {
        "effort_col": "Effort", "effort_unit": "months",
        "duration_col": "Length", "duration_unit": "months",
        "name_cols": ["ID"], "type_col": None,
        "domain": "Business Software", "cpv_default": "72200000",
    },
    "albrecht.csv": {
        "effort_col": "Effort", "effort_unit": "months",
        "duration_col": None, "duration_unit": None,
        "name_cols": ["Number"], "type_col": None,
        "domain": "Business Software", "cpv_default": "72200000",
    },
    "kemerer.csv": {
        "effort_col": "Effort", "effort_unit": "months",
        "duration_col": None, "duration_unit": None,
        "name_cols": ["Project"], "type_col": None,
        "domain": "Financial Software", "cpv_default": "72300000",
    },
    "maxwell.csv": {
        "effort_col": "Effort", "effort_unit": "hours",
        "duration_col": "Duration", "duration_unit": "months",
        "name_cols": ["name"], "type_col": "Type",
        "domain": None, "cpv_default": "72200000",
    },
    "nasa93-dem.csv": {
        "effort_col": "Actual.effort", "effort_unit": "months",
        "duration_col": None, "duration_unit": None,
        "name_cols": ["recordnumber"], "type_col": "application.type",
        "domain": "Embedded Systems", "cpv_default": "72200000",
    },
    "miyazaki94.csv": {
        "effort_col": "MM", "effort_unit": "months",
        "duration_col": "DURA", "duration_unit": "months",
        "name_cols": ["proj_ID"], "type_col": None,
        "domain": "Business Software", "cpv_default": "72200000",
    },
    "sdr.csv": {
        "effort_col": "Effort", "effort_unit": "hours",
        "duration_col": "Duration", "duration_unit": "months",
        "name_cols": ["id"], "type_col": None,
        "domain": "Software Development", "cpv_default": "72200000",
    },
    "isbsg2000.csv": {
        "effort_col": "Normalised.Level.1.PDR", "effort_unit": "hours",
        "duration_col": "Project.Elapsed.Time", "duration_unit": "months",
        "name_cols": ["Project.ID"], "type_col": "Application.Type",
        "domain": None, "cpv_default": "72200000",
    },
    "Albrecht2.csv": {
        "effort_col": "Effort", "effort_unit": "months",
        "duration_col": None, "duration_unit": None,
        "name_cols": [], "type_col": None,
        "domain": "Business Software", "cpv_default": "72200000",
    },
    # COCOMO-81: actual = Aufwand in Personenmonaten; loc = KLOC
    "COCOMO-81.csv": {
        "effort_col": "actual", "effort_unit": "months",
        "duration_col": None, "duration_unit": None,
        "name_cols": ["num"], "type_col": "dev_mode",
        "domain": "Embedded Systems Software", "cpv_default": "72200000",
    },
    # UCP-Dataset: Semikolon-getrennt, Aufwand in Person-Hours
    "UCP_Dataset.csv": {
        "effort_col": "Real_Effort_Person_Hours", "effort_unit": "hours",
        "duration_col": None, "duration_unit": None,
        "name_cols": ["Project_No"], "type_col": "ApplicationType",
        "domain": None, "cpv_default": "72200000",
        "csv_sep": ";", "decimal": ",",
    },
}

# Domain-Keyword → CPV-Code
DOMAIN_ZU_CPV: dict[str, str] = {
    "business":     "72200000",
    "finance":      "72300000",
    "financial":    "72300000",
    "banking":      "72300000",
    "insurance":    "72300000",
    "manufacturing":"72200000",
    "embedded":     "72200000",
    "real-time":    "72200000",
    "telecom":      "72700000",
    "network":      "72700000",
    "web":          "72400000",
    "internet":     "72400000",
    "database":     "72300000",
    "data":         "72300000",
    "analytics":    "72300000",
    "maintenance":  "72500000",
    "support":      "72500000",
    "consulting":   "72600000",
    "security":     "72700000",
    "testing":      "72800000",
    "migration":    "72900000",
}


def _cpv_fuer_domain(domain: str | None, typ: str | None) -> str:
    text = f"{domain or ''} {typ or ''}".lower()
    for schluessel, cpv in DOMAIN_ZU_CPV.items():
        if schluessel in text:
            return cpv
    return "72200000"


def _liste_repo_csvs() -> list[str]:
    """Listet alle CSV-Dateien im Repository per GitHub API."""
    url = f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}/contents/"
    try:
        resp = httpx.get(url, headers={"Accept": "application/vnd.github.v3+json"}, timeout=15.0)
        if resp.status_code == 403:
            logger.warning("[PROMISE] GitHub API Rate-Limit – verwende bekannte Dateiliste.")
            return list(DATASET_CONFIG.keys())
        resp.raise_for_status()
        csvs = [item["name"] for item in resp.json()
                if item.get("type") == "file" and item["name"].lower().endswith(".csv")]
        logger.info("[PROMISE] %d CSV-Dateien im Repository gefunden.", len(csvs))
        return csvs
    except Exception as exc:
        logger.warning("[PROMISE] Repository-Listing fehlgeschlagen (%s) – Fallback.", exc)
        return list(DATASET_CONFIG.keys())


def _lade_csv_von_github(dateiname: str, csv_sep: str = ",", decimal: str = ".") -> pd.DataFrame | None:
    url = f"{RAW_BASE_URL}/{dateiname}"
    try:
        resp = httpx.get(url, timeout=30.0, follow_redirects=True)
        if resp.status_code == 404:
            logger.debug("[PROMISE] Nicht gefunden: %s", dateiname)
            return None
        resp.raise_for_status()
        return pd.read_csv(StringIO(resp.text), sep=csv_sep, decimal=decimal)
    except Exception as exc:
        logger.warning("[PROMISE] Fehler beim Laden von %s: %s", dateiname, exc)
        return None


def _auto_detect_spalten(df: pd.DataFrame) -> dict[str, str | None]:
    """Erkennt Effort- und Duration-Spalten via Namens-Heuristik."""
    low = {c.lower(): c for c in df.columns}

    effort_kandidaten = [
        "effort", "actual_effort", "actualeffort", "actual-effort",
        "actual.effort", "mm", "man-months", "man_months",
        "ph", "person-hours", "normalised.level.1.pdr",
    ]
    effort_col = next((low[k] for k in effort_kandidaten if k in low), None)

    dauer_kandidaten = [
        "duration", "length", "dura", "months", "elapsedtime",
        "elapsed_time", "project.elapsed.time",
    ]
    dauer_col = next((low[k] for k in dauer_kandidaten if k in low), None)

    name_kandidaten = ["name", "project", "id", "proj_id", "number", "recordnumber", "project.id"]
    name_col = next((low[k] for k in name_kandidaten if k in low), None)

    return {"effort": effort_col, "dauer": dauer_col, "name": name_col}


def _konvertiere_dataset(dateiname: str, df: pd.DataFrame, config: dict | None) -> list[dict]:
    if config:
        effort_col  = config.get("effort_col")
        effort_unit = config.get("effort_unit", "hours")
        dauer_col   = config.get("duration_col")
        dauer_unit  = config.get("duration_unit", "months")
        name_cols   = config.get("name_cols") or []
        typ_col     = config.get("type_col")
        domain      = config.get("domain", "Software Development")
        cpv_default = config.get("cpv_default", "72200000")
    else:
        auto        = _auto_detect_spalten(df)
        effort_col  = auto["effort"]
        effort_unit = "months"
        dauer_col   = auto["dauer"]
        dauer_unit  = "months"
        name_cols   = [auto["name"]] if auto["name"] else []
        typ_col     = None
        domain      = "Software Development"
        cpv_default = "72200000"

    if not effort_col or effort_col not in df.columns:
        logger.warning("[PROMISE] %s: Effort-Spalte '%s' fehlt – übersprungen.", dateiname, effort_col)
        return []

    dataset_label = dateiname.replace(".csv", "").replace("_", " ").title()
    ergebnisse: list[dict] = []

    for idx, zeile in df.iterrows():
        effort_raw = pd.to_numeric(zeile.get(effort_col), errors="coerce")
        if pd.isna(effort_raw) or effort_raw <= 0:
            continue

        effort_h = float(effort_raw) * STUNDEN_PRO_MONAT if effort_unit == "months" else float(effort_raw)
        budget_eur = round(effort_h * STUNDENSATZ_DACH, 2)

        if not (5_000 <= budget_eur <= 500_000_000):
            continue

        # Laufzeit
        dauer_tage = None
        if dauer_col and dauer_col in df.columns:
            d = pd.to_numeric(zeile.get(dauer_col), errors="coerce")
            if not pd.isna(d) and d > 0:
                tage = int(float(d) * 30.44) if dauer_unit == "months" else int(float(d))
                dauer_tage = tage if 7 <= tage <= 3_650 else None

        # Name
        name_teile = [str(zeile[c]) for c in name_cols
                      if c in df.columns and pd.notna(zeile.get(c))]
        proj_name = " ".join(name_teile) if name_teile else f"Projekt {idx}"

        # Typ & CPV
        typ_text = None
        if typ_col and typ_col in df.columns and pd.notna(zeile.get(typ_col)):
            typ_text = str(zeile[typ_col])
        cpv = _cpv_fuer_domain(domain, typ_text) if (domain or typ_text) else cpv_default

        # Beschreibung
        beschreibung_teile = [f"Softwareprojekt aus PROMISE-Datensatz {dataset_label}: {proj_name}."]
        if domain:
            beschreibung_teile.append(f"Anwendungsbereich: {domain}.")
        if typ_text:
            beschreibung_teile.append(f"Projekttyp: {typ_text}.")
        beschreibung_teile.append(
            f"Aufwand: {effort_raw:.1f} "
            f"{'Personenmonate' if effort_unit == 'months' else 'Personenstunden'}. "
            f"Geschätztes Budget: {budget_eur:,.0f} EUR (DACH-Satz {STUNDENSATZ_DACH:.0f} €/h)."
        )

        ergebnisse.append({
            "document_id":    f"promise_{dateiname.replace('.csv', '')}_{idx}",
            "publication_date": "20200101",
            "title":          f"{dataset_label}: {proj_name}",
            "description":    " ".join(beschreibung_teile),
            "cpv_code":       cpv,
            "estimated_value": budget_eur,
            "currency":       "EUR",
            "country":        "DE",
            "duration_end":   None,
            "dauer_tage_direkt": dauer_tage,   # direktes Feld – umgeht Datumsberechnung in preprocess
            "notice_type":    "promise",
            "datenquelle":    "promise",
            "raw":            {},
        })

    logger.info("[PROMISE] %s: %d / %d Zeilen übernommen.", dateiname, len(ergebnisse), len(df))
    return ergebnisse


# ---------------------------------------------------------------------------
# Haupt-Exportfunktion
# ---------------------------------------------------------------------------

def fetch_promise_data(output_path: Path = OUTPUT_FILE) -> int:
    """Lädt alle PROMISE-Datensätze und speichert als JSONL."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    csv_dateien = _liste_repo_csvs()
    alle: list[dict] = []

    for dateiname in sorted(csv_dateien):
        logger.info("[PROMISE] Lade %s ...", dateiname)
        cfg_sep     = (DATASET_CONFIG.get(dateiname) or {}).get("csv_sep", ",")
        cfg_decimal = (DATASET_CONFIG.get(dateiname) or {}).get("decimal", ".")
        df = _lade_csv_von_github(dateiname, csv_sep=cfg_sep, decimal=cfg_decimal)
        if df is None or df.empty:
            continue
        logger.info("[PROMISE] %s: %d Zeilen, Spalten: %s",
                    dateiname, len(df), list(df.columns)[:10])
        config = DATASET_CONFIG.get(dateiname)
        alle.extend(_konvertiere_dataset(dateiname, df, config))
        time.sleep(0.4)

    with output_path.open("w", encoding="utf-8") as f:
        for ds in alle:
            f.write(json.dumps(ds, ensure_ascii=False) + "\n")

    logger.info("[PROMISE] Gesamt: %d Datensätze → %s", len(alle), output_path)
    return len(alle)


# ---------------------------------------------------------------------------
# Direkt ausführbar
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    n = fetch_promise_data()
    print(f"\nPROMISE-Datensätze gespeichert: {n}")
