"""
EstimateIQ – Gehaltsdaten-Connector für DACH IT-Stundensätze.

Drei Quellen (mit automatischem Fallback):
  1. Stack Overflow Developer Survey  – reale Marktdaten (DACH-gefiltert)
  2. Eurostat EARN_SES_HOURLY         – Stundenverdienste IT-Sektor, NACE J62/J63
  3. Destatis GENESIS                 – Bruttostundenverdienst nach Bundesland

Ausgabe: data/raw_salary_data.jsonl

Schema je Eintrag:
  {
    "region":              "DE-BY",            # ISO 3166-2 oder "DE"/"AT"/"CH"
    "technologie":         "Python",           # Sprache/Technologie oder "all"
    "stundensatz_median":  95.0,
    "stundensatz_p25":     76.0,
    "stundensatz_p75":     118.0,
    "quelle":              "stackoverflow_survey",
    "jahr":                2024
  }

Verwendung:
  python -m estimateiq.data.fetch_salary_data
  from estimateiq.data.fetch_salary_data import get_stundensatz
"""

import io
import json
import logging
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

RAW_DATA_DIR    = Path("data")
OUTPUT_FILE     = RAW_DATA_DIR / "raw_salary_data.jsonl"
CACHE_DIR       = RAW_DATA_DIR / "salary_cache"

USD_ZU_EUR      = 0.92
STUNDEN_PRO_JAHR = 1_800   # Produktive Jahresarbeitsstunden laut Aufgabenstellung
AKTUELLSTES_JAHR = 2024

# Stack Overflow Survey – Jahres-URLs (neueste zuerst)
# Aktueller CDN-Link für 2023-Survey (fetch_stackoverflow.py nutzt diesen auch)
SO_SURVEY_URLS = {
    2024: (
        "https://cdn.stackoverflow.co/files/jo7n4k8s/production/"
        "49915bfd46d0902c3564fd9a06b509d08a20488c.zip/"
        "stack-overflow-developer-survey-2024.zip"
    ),
    2023: (
        "https://cdn.stackoverflow.co/files/jo7n4k8s/production/"
        "49915bfd46d0902c3564fd9a06b509d08a20488c.zip/"
        "stack-overflow-developer-survey-2024.zip"
    ),
}

DACH_LAENDER_SO = {"Germany", "Austria", "Switzerland"}   # SO-Bezeichnungen
LAND_SO_ZU_ISO  = {"Germany": "DE", "Austria": "AT", "Switzerland": "CH"}

# Eurostat-Datensatz: Stundenverdienste (Structure of Earnings Survey)
EUROSTAT_URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/earn_ses_hourly"
    "?geo=DE&geo=AT"           # CH ist nicht in Eurostat enthalten (kein EU-Mitglied)
    "&nace_r2=J62&nace_r2=J63" # NACE: IT-Dienstleistungen & Informationsdienstleistungen
    "&sex=T"                   # Gesamt (Männer + Frauen)
    "&worktime=TOTAL"          # Alle Beschäftigungsformen
    "&sinceTimePeriod=2018"
)

# Destatis GENESIS – Verdiensterhebung (Bruttostundenverdienst nach Bundesland)
DESTATIS_URL = (
    "https://www-genesis.destatis.de/genesisWS/rest/2020/data/table"
    "?name=62321-0001&area=all&compress=false&transpose=false&format=ffcsv&language=de"
)

# ---------------------------------------------------------------------------
# Bundesland-Mapping und Referenzwerte
# ---------------------------------------------------------------------------

BUNDESLAND_ISO: dict[str, str] = {
    "Baden-Württemberg": "DE-BW",
    "Bayern":            "DE-BY",
    "Berlin":            "DE-BE",
    "Brandenburg":       "DE-BB",
    "Bremen":            "DE-HB",
    "Hamburg":           "DE-HH",
    "Hessen":            "DE-HE",
    "Mecklenburg-Vorpommern": "DE-MV",
    "Niedersachsen":     "DE-NI",
    "Nordrhein-Westfalen": "DE-NW",
    "Rheinland-Pfalz":   "DE-RP",
    "Saarland":          "DE-SL",
    "Sachsen":           "DE-SN",
    "Sachsen-Anhalt":    "DE-ST",
    "Schleswig-Holstein": "DE-SH",
    "Thüringen":         "DE-TH",
}

# Regionale Aufschläge auf den DACH-Durchschnitt (Quelle: Destatis VSE 2022, Bitkom 2023)
# Verwendung als Fallback wenn Destatis-API nicht verfügbar.
BUNDESLAND_MULTIPLIKATOR: dict[str, float] = {
    "DE-BW": 1.14,   # Baden-Württemberg – SAP/Bosch-Region
    "DE-BY": 1.13,   # Bayern – München/Ingolstadt
    "DE-HE": 1.11,   # Hessen – Frankfurt (Banken & Beratung)
    "DE-HH": 1.09,   # Hamburg
    "DE-BE": 1.06,   # Berlin – Startup-Ökosystem
    "DE-NW": 1.03,   # NRW – Köln/Düsseldorf
    "DE-RP": 0.97,
    "DE-SL": 0.95,
    "DE-HB": 0.97,
    "DE-SH": 0.96,
    "DE-NI": 0.96,
    "DE-BB": 0.83,   # Ostdeutschland
    "DE-MV": 0.81,
    "DE-ST": 0.80,
    "DE-SN": 0.84,
    "DE-TH": 0.82,
}

# Technologie-Stundensatz-Multiplikator ggü. DACH-Durchschnitt
# Quellen: SO Survey 2023/2024, Bitkom Gehaltsreport 2024
TECHNOLOGIE_MULTIPLIKATOR: dict[str, float] = {
    "Rust":         1.24,
    "Go":           1.22,
    "SAP":          1.28,
    "Kotlin":       1.18,
    "Python":       1.18,
    "Scala":        1.17,
    "TypeScript":   1.15,
    "Swift":        1.14,
    "Java":         1.10,
    "C++":          1.09,
    "C#":           1.08,
    "Bash/Shell (all shells)": 1.07,
    "PowerShell":   1.05,
    "JavaScript":   1.04,
    "SQL":          1.00,
    "Ruby":         0.99,
    "PHP":          0.90,
    "HTML/CSS":     0.88,
}

# DACH-Basiswerte (€/h) – Fallback wenn alle APIs scheitern
# Quellen: Destatis VSE 2022, Eurostat 2021, Bitkom 2024
DACH_BASIS_STUNDENSATZ: dict[str, float] = {
    "DE": 47.5,
    "AT": 43.0,
    "CH": 69.0,   # in EUR umgerechnet (CHF × 1.05 / 1.55 ≈ direkter Marktwert)
}


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _sicherer_download(url: str, timeout: float = 60.0) -> bytes | None:
    """Lädt URL mit Retry-Logik, gibt Bytes zurück oder None bei Fehler."""
    import time
    for versuch in range(3):
        try:
            resp = httpx.get(url, timeout=timeout, follow_redirects=True)
            if resp.status_code == 200:
                return resp.content
            logger.warning("[Salary] HTTP %d für %s", resp.status_code, url[:80])
            return None
        except Exception as exc:
            warte = 2 ** versuch
            logger.warning("[Salary] Fetch-Fehler (Versuch %d/3) %s: %s. Warte %d s.",
                           versuch + 1, url[:80], exc, warte)
            if versuch < 2:
                time.sleep(warte)
    return None


def _p25_p75_aus_median(median: float) -> tuple[float, float]:
    """Schätzt Quartile aus dem Median (Näherung für rechtsschiefe Gehaltsverteilung)."""
    return round(median * 0.80, 1), round(median * 1.26, 1)


# ---------------------------------------------------------------------------
# Quelle 1: Stack Overflow Developer Survey
# ---------------------------------------------------------------------------

def _lade_so_survey_csv(jahr: int) -> pd.DataFrame | None:
    """Lädt Survey-ZIP, extrahiert survey_results_public.csv."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_pfad = CACHE_DIR / f"so_survey_{jahr}.csv"

    # fetch_stackoverflow.py cached unter so_survey_2023.csv → mitnutzen
    gemeinsamer_cache = CACHE_DIR / "so_survey_2023.csv"
    if not cache_pfad.exists() and gemeinsamer_cache.exists() and gemeinsamer_cache.stat().st_size > 1_000_000:
        cache_pfad = gemeinsamer_cache

    if cache_pfad.exists() and cache_pfad.stat().st_size > 1_000_000:
        logger.info("[SO] Verwende gecachte Survey-Daten: %s", cache_pfad)
        return pd.read_csv(cache_pfad, low_memory=False)

    url = SO_SURVEY_URLS.get(jahr)
    if not url:
        return None

    logger.info("[SO] Lade Survey %d (~60–100 MB) von %s ...", jahr, url[:60])
    daten = _sicherer_download(url, timeout=120.0)
    if not daten:
        return None

    try:
        with zipfile.ZipFile(io.BytesIO(daten)) as zf:
            csv_name = next(
                (n for n in zf.namelist() if "results_public" in n.lower() and n.endswith(".csv")),
                None,
            )
            if not csv_name:
                logger.warning("[SO] Keine survey_results_public.csv im ZIP %d.", jahr)
                return None
            with zf.open(csv_name) as f:
                df = pd.read_csv(f, low_memory=False)

        df.to_csv(cache_pfad, index=False)
        logger.info("[SO] Survey %d geladen: %d Zeilen, gecacht in %s.", jahr, len(df), cache_pfad)
        return df

    except Exception as exc:
        logger.error("[SO] ZIP-Verarbeitung %d fehlgeschlagen: %s", jahr, exc)
        return None


def _normalisiere_so_spalten(df: pd.DataFrame) -> pd.DataFrame:
    """
    Bringt verschiedene Spaltennamen unterschiedlicher Jahrgänge auf einheitliche Namen.
    Gibt None zurück wenn Pflichtfelder fehlen.
    """
    # Verschiedene Schreibweisen über die Jahre
    umbenennung = {
        "ConvertedCompYearly": "comp_yearly_usd",
        "ConvertedSalary":     "comp_yearly_usd",
        "Salary":              "comp_yearly_usd",
        "Country":             "country",
        "DevType":             "dev_type",
        "LanguageHaveWorkedWith": "sprachen",
        "LanguageWorkedWith":  "sprachen",
        "HaveWorkedLanguage":  "sprachen",
        "MainBranch":          "main_branch",
    }
    for alt, neu in umbenennung.items():
        if alt in df.columns and neu not in df.columns:
            df = df.rename(columns={alt: neu})
    return df


def fetch_stackoverflow(jahr: int = AKTUELLSTES_JAHR) -> list[dict]:
    """Lädt SO-Survey und gibt normalisierte Stundensatz-Datensätze zurück."""
    for versuchs_jahr in [jahr, jahr - 1, jahr - 2]:
        df = _lade_so_survey_csv(versuchs_jahr)
        if df is not None:
            ergebnisse = _verarbeite_so_df(df, versuchs_jahr)
            if ergebnisse:
                return ergebnisse
            logger.warning("[SO] Jahr %d: keine verwertbaren DACH-Einträge.", versuchs_jahr)

    logger.warning("[SO] Kein Survey geladen – übersprungen.")
    return []


def _verarbeite_so_df(df: pd.DataFrame, jahr: int) -> list[dict]:
    df = _normalisiere_so_spalten(df)

    pflichtfelder = ["country", "comp_yearly_usd", "sprachen"]
    if any(f not in df.columns for f in pflichtfelder):
        fehlend = [f for f in pflichtfelder if f not in df.columns]
        logger.warning("[SO] Fehlende Spalten: %s. Übersprungen.", fehlend)
        return []

    # Filter: DACH + professional developers + plausibles Gehalt
    maske_land = df["country"].isin(DACH_LAENDER_SO)
    maske_gehalt = pd.to_numeric(df["comp_yearly_usd"], errors="coerce").between(15_000, 800_000)

    if "main_branch" in df.columns:
        maske_profi = df["main_branch"].str.contains("developer", case=False, na=False)
        df = df[maske_land & maske_gehalt & maske_profi].copy()
    else:
        df = df[maske_land & maske_gehalt].copy()

    if len(df) < 10:
        logger.warning("[SO] Zu wenig DACH-Einträge nach Filterung: %d", len(df))
        return []

    # Optional: DevType-Filter (Entwickler, Architekten, Engineers)
    if "dev_type" in df.columns:
        dev_filter = df["dev_type"].str.contains(
            r"[Dd]eveloper|[Ee]ngineer|[Aa]rchitect|[Ss]cientist", na=False
        )
        df = df[dev_filter].copy()

    df["comp_yearly_usd"] = pd.to_numeric(df["comp_yearly_usd"], errors="coerce")
    df["stundensatz_eur"] = (df["comp_yearly_usd"] * USD_ZU_EUR / STUNDEN_PRO_JAHR).round(2)
    df["iso_land"] = df["country"].map(LAND_SO_ZU_ISO)

    logger.info("[SO] %d DACH-Entwickler mit validem Gehalt im Jahrgang %d.", len(df), jahr)

    # Sprachen: Semicolon-separiert → explodieren
    df["sprachen"] = df["sprachen"].fillna("").astype(str)
    df_expl = df.assign(technologie=df["sprachen"].str.split(";")).explode("technologie")
    df_expl["technologie"] = df_expl["technologie"].str.strip()
    df_expl = df_expl[df_expl["technologie"].str.len() > 0]

    ergebnisse: list[dict] = []

    # Aggregat nach Land + Technologie
    for (iso_land, technologie), gruppe in df_expl.groupby(["iso_land", "technologie"]):
        werte = gruppe["stundensatz_eur"].dropna()
        if len(werte) < 5:
            continue
        median = float(werte.median())
        p25    = float(werte.quantile(0.25))
        p75    = float(werte.quantile(0.75))
        ergebnisse.append({
            "region":              str(iso_land),
            "technologie":         str(technologie),
            "stundensatz_median":  round(median, 1),
            "stundensatz_p25":     round(p25, 1),
            "stundensatz_p75":     round(p75, 1),
            "quelle":              "stackoverflow_survey",
            "jahr":                jahr,
            "n":                   int(len(werte)),
        })

    # Aggregat nach Land gesamt ("all")
    for iso_land, gruppe in df.groupby("iso_land"):
        werte = gruppe["stundensatz_eur"].dropna()
        if len(werte) < 5:
            continue
        ergebnisse.append({
            "region":              str(iso_land),
            "technologie":         "all",
            "stundensatz_median":  round(float(werte.median()), 1),
            "stundensatz_p25":     round(float(werte.quantile(0.25)), 1),
            "stundensatz_p75":     round(float(werte.quantile(0.75)), 1),
            "quelle":              "stackoverflow_survey",
            "jahr":                jahr,
            "n":                   int(len(werte)),
        })

    logger.info("[SO] %d Stundensatz-Datensätze erzeugt.", len(ergebnisse))
    return ergebnisse


# ---------------------------------------------------------------------------
# Quelle 2: Eurostat EARN_SES_HOURLY
# ---------------------------------------------------------------------------

def _parse_eurostat_jsonstat(data: dict) -> list[dict]:
    """
    Parst das JSON-stat Format der Eurostat-API.
    Gibt eine Liste von {geo, nace_r2, time, wert} zurück.
    """
    try:
        dims      = data.get("id", [])
        groessen  = data.get("size", [])
        dim_infos = data.get("dimension", {})
        werte_roh = data.get("value", {})

        if not dims or not werte_roh:
            logger.warning("[Eurostat] Leere JSON-stat Antwort.")
            return []

        # Strides für die Flat-Index-Berechnung
        strides = [1] * len(dims)
        for i in range(len(dims) - 2, -1, -1):
            strides[i] = strides[i + 1] * groessen[i + 1]

        # Kategorien je Dimension
        kategorien: dict[str, dict[str, int]] = {}
        kategorien_labels: dict[str, dict[str, str]] = {}
        for dim_name in dims:
            dim_info = dim_infos.get(dim_name, {})
            cat = dim_info.get("category", {})
            kategorien[dim_name]        = cat.get("index", {})
            kategorien_labels[dim_name] = cat.get("label", {})

        ergebnisse: list[dict] = []
        geo_idx   = dims.index("geo")  if "geo"   in dims else -1
        nace_idx  = dims.index("nace_r2") if "nace_r2" in dims else -1
        time_idx  = dims.index("time") if "time"  in dims else -1

        if geo_idx < 0 or time_idx < 0:
            logger.warning("[Eurostat] Dimensionen 'geo' oder 'time' fehlen in Antwort.")
            return []

        # Alle Werte iterieren
        werte = {int(k): float(v) for k, v in werte_roh.items() if v is not None}
        for flat_idx, wert in werte.items():
            if wert <= 0:
                continue

            # Koordinaten zurückrechnen
            koord: dict[str, str] = {}
            rest = flat_idx
            for i, dim_name in enumerate(dims):
                local_idx = (rest // strides[i]) % groessen[i]
                rest = rest % strides[i] if i < len(dims) - 1 else 0
                # Index → Code
                for code, idx in kategorien[dim_name].items():
                    if idx == local_idx:
                        koord[dim_name] = code
                        break

            geo  = koord.get("geo", "")
            nace = koord.get("nace_r2", "J62")
            jahr = koord.get("time", "2020")

            if not geo or len(geo) not in (2, 3):
                continue

            # Eurostat gibt mean hourly earnings direkt in €/h
            p25, p75 = _p25_p75_aus_median(wert)
            ergebnisse.append({
                "region":              geo.upper(),
                "technologie":         "all",
                "stundensatz_median":  round(wert, 2),
                "stundensatz_p25":     p25,
                "stundensatz_p75":     p75,
                "quelle":              "eurostat_ses",
                "jahr":                int(jahr[:4]) if jahr[:4].isdigit() else 2020,
                "nace":                nace,
            })

        logger.info("[Eurostat] %d Einträge aus JSON-stat geparsed.", len(ergebnisse))
        return ergebnisse

    except Exception as exc:
        logger.error("[Eurostat] Parsing-Fehler: %s", exc)
        return []


def fetch_eurostat() -> list[dict]:
    """Ruft Stundenverdienste aus Eurostat EARN_SES_HOURLY ab."""
    logger.info("[Eurostat] Rufe EARN_SES_HOURLY ab (IT-Sektor, DE + AT)...")
    daten = _sicherer_download(EUROSTAT_URL, timeout=30.0)

    if not daten:
        logger.warning("[Eurostat] Download fehlgeschlagen – übersprungen.")
        return []

    try:
        json_data = json.loads(daten.decode("utf-8"))
        ergebnisse = _parse_eurostat_jsonstat(json_data)
        if not ergebnisse:
            logger.warning("[Eurostat] Keine verwertbaren Daten in Antwort.")
        return ergebnisse
    except json.JSONDecodeError as exc:
        logger.error("[Eurostat] JSON-Parsing fehlgeschlagen: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Quelle 3: Destatis GENESIS – Bundesland-Verdienste
# ---------------------------------------------------------------------------

def _parse_destatis_ffcsv(text: str) -> list[dict]:
    """
    Parst das Destatis 'ffcsv'-Format (Flat File CSV mit Metadaten-Kopf).
    Sucht nach Zeilen mit WZ J (IT-Sektor) und Bruttostundenverdienst-Werten.
    """
    zeilen = text.splitlines()

    # Überspringe Metadaten-Kopf (führende Zeilen mit ; oder leer)
    daten_start = 0
    for i, zeile in enumerate(zeilen):
        if ";" in zeile and len(zeile.split(";")) > 3:
            daten_start = i
            break

    if daten_start == 0:
        logger.warning("[Destatis] Kein gültiges CSV-Format erkannt.")
        return []

    try:
        df = pd.read_csv(
            io.StringIO("\n".join(zeilen[daten_start:])),
            sep=";",
            decimal=",",
            encoding="utf-8",
            on_bad_lines="skip",
        )
    except Exception as exc:
        logger.warning("[Destatis] CSV-Parsing fehlgeschlagen: %s", exc)
        return []

    # Spaltensuche: Bundesland, Wirtschaftszweig, Verdienst, Jahr
    cols_lower = {c.lower().strip(): c for c in df.columns}

    bundesland_col = next((cols_lower[k] for k in cols_lower if "land" in k or "gebiet" in k), None)
    wert_col       = next(
        (cols_lower[k] for k in cols_lower if "stunde" in k or "verdienst" in k), None
    )
    wz_col         = next((cols_lower[k] for k in cols_lower if "wirtschaft" in k or "nace" in k or "wz" in k), None)
    zeit_col       = next((cols_lower[k] for k in cols_lower if "jahr" in k or "zeit" in k or "period" in k), None)

    if not bundesland_col or not wert_col:
        logger.warning("[Destatis] Pflicht-Spalten nicht erkannt. Spalten: %s", list(df.columns)[:8])
        return []

    # Filter auf IT-Wirtschaftszweig (WZ J / NACE J)
    if wz_col:
        it_filter = df[wz_col].astype(str).str.contains(r"J\s*6[23]|J\b.*Inform|Inform.*Technologie",
                                                          case=False, na=False, regex=True)
        df_it = df[it_filter].copy()
        if df_it.empty:
            logger.warning("[Destatis] Kein IT-Wirtschaftszweig (J62/J63) gefunden – verwende Gesamtdaten.")
            df_it = df.copy()
    else:
        df_it = df.copy()

    ergebnisse: list[dict] = []
    aktuellstes_jahr = 0

    for _, zeile in df_it.iterrows():
        bundesland_name = str(zeile.get(bundesland_col, "")).strip()
        iso_code = BUNDESLAND_ISO.get(bundesland_name)
        if not iso_code:
            continue

        wert_roh = pd.to_numeric(str(zeile.get(wert_col, "")).replace(",", "."), errors="coerce")
        if pd.isna(wert_roh) or wert_roh <= 0:
            continue

        jahr_roh = str(zeile.get(zeit_col, "2022")) if zeit_col else "2022"
        try:
            jahr = int(jahr_roh[:4])
        except ValueError:
            jahr = 2022
        aktuellstes_jahr = max(aktuellstes_jahr, jahr)

        p25, p75 = _p25_p75_aus_median(float(wert_roh))
        ergebnisse.append({
            "region":             iso_code,
            "technologie":        "all",
            "stundensatz_median": round(float(wert_roh), 2),
            "stundensatz_p25":    p25,
            "stundensatz_p75":    p75,
            "quelle":             "destatis",
            "jahr":               jahr,
        })

    logger.info("[Destatis] %d Bundesland-Einträge geparsed.", len(ergebnisse))
    return ergebnisse


def _destatis_fallback() -> list[dict]:
    """
    Synthethische Destatis-Daten aus bekannten Marktdaten (Fallback).
    Basiert auf: Destatis VSE 2022, Bitkom Gehaltsreport 2024.
    DACH-Basis: DE ≈ 47,5 €/h | AT ≈ 43,0 €/h | CH ≈ 69,0 €/h
    """
    logger.info("[Destatis] Verwende synthetische Regionalwerte (Fallback).")
    ergebnisse: list[dict] = []
    de_basis = DACH_BASIS_STUNDENSATZ["DE"]
    jahr = 2023

    for iso_code, faktor in BUNDESLAND_MULTIPLIKATOR.items():
        median = round(de_basis * faktor, 1)
        p25, p75 = _p25_p75_aus_median(median)
        ergebnisse.append({
            "region":             iso_code,
            "technologie":        "all",
            "stundensatz_median": median,
            "stundensatz_p25":    p25,
            "stundensatz_p75":    p75,
            "quelle":             "destatis_fallback",
            "jahr":               jahr,
        })

    return ergebnisse


def fetch_destatis() -> list[dict]:
    """Ruft Bundesland-Verdienste von Destatis GENESIS ab."""
    logger.info("[Destatis] Rufe Verdiensterhebung von GENESIS ab...")
    daten = _sicherer_download(DESTATIS_URL, timeout=30.0)

    if daten:
        try:
            text = daten.decode("utf-8", errors="replace")
            ergebnisse = _parse_destatis_ffcsv(text)
            if ergebnisse:
                return ergebnisse
            logger.warning("[Destatis] Parsing ergab keine Ergebnisse – Fallback.")
        except Exception as exc:
            logger.warning("[Destatis] Verarbeitungsfehler (%s) – Fallback.", exc)

    return _destatis_fallback()


# ---------------------------------------------------------------------------
# Kombinierter Fetch + Speichern
# ---------------------------------------------------------------------------

def _ergaenze_fehlende_laender(alle: list[dict]) -> list[dict]:
    """
    Ergänzt Länder/Technologien die durch keine Quelle abgedeckt wurden.
    Erstellt synthetische DACH-Basiswerte (AT, CH + Technologie-Multiplikatoren).
    """
    vorhandene_regionen = {r["region"] for r in alle}
    vorhandene_combos   = {(r["region"], r["technologie"]) for r in alle}
    zusatz: list[dict] = []
    jahr = AKTUELLSTES_JAHR

    # Land-Level Fallbacks (AT, CH falls nicht aus Eurostat/SO)
    for land, basis in DACH_BASIS_STUNDENSATZ.items():
        if land not in vorhandene_regionen:
            p25, p75 = _p25_p75_aus_median(basis)
            zusatz.append({
                "region":             land,
                "technologie":        "all",
                "stundensatz_median": basis,
                "stundensatz_p25":    p25,
                "stundensatz_p75":    p75,
                "quelle":             "dach_fallback",
                "jahr":               jahr,
            })

    # Technologie × Land kombiniert (falls nicht aus SO vorhanden)
    for land, basis in DACH_BASIS_STUNDENSATZ.items():
        for tech, multi in TECHNOLOGIE_MULTIPLIKATOR.items():
            if (land, tech) not in vorhandene_combos:
                median = round(basis * multi, 1)
                p25, p75 = _p25_p75_aus_median(median)
                zusatz.append({
                    "region":             land,
                    "technologie":        tech,
                    "stundensatz_median": median,
                    "stundensatz_p25":    p25,
                    "stundensatz_p75":    p75,
                    "quelle":             "technologie_multiplikator",
                    "jahr":               jahr,
                })

    if zusatz:
        logger.info("[Fallback] %d synthetische Einträge ergänzt.", len(zusatz))

    return zusatz


def fetch_all_salary_data(output_path: Path = OUTPUT_FILE) -> int:
    """
    Lädt alle drei Quellen und speichert kombinierte Stundensatz-Daten als JSONL.
    Quelle 1: Stack Overflow Survey (SO)
    Quelle 2: Eurostat EARN_SES_HOURLY
    Quelle 3: Destatis GENESIS Bundesland-Verdienste
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    alle: list[dict] = []

    so_daten = fetch_stackoverflow()
    logger.info("[Salary] SO: %d Datensätze", len(so_daten))
    alle.extend(so_daten)

    eurostat_daten = fetch_eurostat()
    logger.info("[Salary] Eurostat: %d Datensätze", len(eurostat_daten))
    alle.extend(eurostat_daten)

    destatis_daten = fetch_destatis()
    logger.info("[Salary] Destatis: %d Datensätze", len(destatis_daten))
    alle.extend(destatis_daten)

    # Lücken füllen
    alle.extend(_ergaenze_fehlende_laender(alle))

    with output_path.open("w", encoding="utf-8") as f:
        for ds in alle:
            f.write(json.dumps(ds, ensure_ascii=False) + "\n")

    quellen_stats = {}
    for ds in alle:
        q = ds.get("quelle", "unbekannt")
        quellen_stats[q] = quellen_stats.get(q, 0) + 1

    logger.info("[Salary] Gesamt: %d Datensätze → %s", len(alle), output_path)
    logger.info("[Salary] Quellen: %s", quellen_stats)
    return len(alle)


# ---------------------------------------------------------------------------
# Lookup-Klasse und get_stundensatz()
# ---------------------------------------------------------------------------

class StundensatzLookup:
    """
    In-Memory-Index für schnelle Stundensatz-Abfragen mit Fallback-Hierarchie.

    Fallback-Kaskade:
      1. Exakter Match:    region + technologie
      2. Übergeordnetes Land + Technologie: "DE-BY" → "DE" + technologie
      3. Region + "all":  region (beliebige Technologie)
      4. "all" + Tech:    DACH-Durchschnitt für diese Technologie
      5. DACH-Median:     globaler Fallback
    """

    def __init__(self, jsonl_pfad: Path = OUTPUT_FILE):
        self._pfad = jsonl_pfad
        self._df: pd.DataFrame | None = None
        self._lade_daten()

    def _lade_daten(self) -> None:
        if not self._pfad.exists():
            logger.warning(
                "[StundensatzLookup] Keine Daten unter %s. "
                "Bitte zuerst: python -m estimateiq.data.fetch_salary_data",
                self._pfad,
            )
            self._df = pd.DataFrame(columns=[
                "region", "technologie", "stundensatz_median",
                "stundensatz_p25", "stundensatz_p75", "quelle", "jahr",
            ])
            return

        zeilen: list[dict] = []
        with self._pfad.open(encoding="utf-8") as f:
            for zeile in f:
                zeile = zeile.strip()
                if zeile:
                    try:
                        zeilen.append(json.loads(zeile))
                    except json.JSONDecodeError:
                        pass

        self._df = pd.DataFrame(zeilen)
        # Neueste Daten je Region+Technologie bevorzugen
        if "jahr" in self._df.columns and len(self._df) > 0:
            self._df = (
                self._df
                .sort_values("jahr", ascending=False)
                .drop_duplicates(subset=["region", "technologie"], keep="first")
                .reset_index(drop=True)
            )
        logger.info("[StundensatzLookup] %d Stundensatz-Einträge geladen.", len(self._df))

    def _suche(self, region: str | None, technologie: str | None) -> dict | None:
        """Sucht exakten Match in DataFrame."""
        if self._df is None or len(self._df) == 0:
            return None

        maske = pd.Series([True] * len(self._df))
        if region and region != "all":
            maske &= self._df["region"] == region
        else:
            maske &= self._df["region"].isin(list(DACH_BASIS_STUNDENSATZ.keys()))

        if technologie and technologie != "all":
            maske &= self._df["technologie"] == technologie
        else:
            maske &= self._df["technologie"] == "all"

        treffer = self._df[maske]
        if len(treffer) == 0:
            return None

        # Priorisierung: stackoverflow > eurostat > destatis > fallback
        prio = {"stackoverflow_survey": 0, "eurostat_ses": 1,
                "destatis": 2, "destatis_fallback": 3,
                "technologie_multiplikator": 4, "dach_fallback": 5}
        treffer = treffer.copy()
        treffer["prio"] = treffer["quelle"].map(prio).fillna(9)
        beste = treffer.sort_values("prio").iloc[0]

        return {
            "region":             beste["region"],
            "technologie":        beste.get("technologie", "all"),
            "stundensatz_median": float(beste["stundensatz_median"]),
            "stundensatz_p25":    float(beste["stundensatz_p25"]),
            "stundensatz_p75":    float(beste["stundensatz_p75"]),
            "quelle":             str(beste["quelle"]),
            "jahr":               int(beste.get("jahr", 2023)),
        }

    def get_stundensatz(self, region: str = "DE", technologie: str = "all") -> dict:
        """
        Hauptabfrage mit 5-stufiger Fallback-Hierarchie.

        Args:
            region:      ISO 3166-2 ("DE", "AT", "CH", "DE-BY", "DE-BW", ...)
            technologie: Technologie-Bezeichnung ("Python", "Java", "SAP", ...) oder "all"

        Returns:
            dict mit stundensatz_median, stundensatz_p25, stundensatz_p75, quelle, jahr
        """
        # Normalisierung
        region = (region or "DE").upper().strip()
        technologie = (technologie or "all").strip()

        # 1) Exakter Match
        treffer = self._suche(region, technologie)
        if treffer:
            return treffer

        # 2) Übergeordnetes Land (DE-BY → DE)
        if "-" in region:
            oberland = region.split("-")[0]
            treffer = self._suche(oberland, technologie)
            if treffer:
                # Skaliere mit bekanntem Bundesland-Multiplikator
                faktor = BUNDESLAND_MULTIPLIKATOR.get(region, 1.0)
                treffer = treffer.copy()
                for key in ("stundensatz_median", "stundensatz_p25", "stundensatz_p75"):
                    treffer[key] = round(treffer[key] * faktor, 1)
                treffer["region"] = region
                treffer["quelle"] = treffer["quelle"] + "+regional_faktor"
                return treffer

        # 3) Gleiche Region, beliebige Technologie (technologie → "all")
        treffer = self._suche(region, "all")
        if treffer:
            faktor = TECHNOLOGIE_MULTIPLIKATOR.get(technologie, 1.0)
            treffer = treffer.copy()
            for key in ("stundensatz_median", "stundensatz_p25", "stundensatz_p75"):
                treffer[key] = round(treffer[key] * faktor, 1)
            treffer["technologie"] = technologie
            treffer["quelle"] = treffer["quelle"] + "+tech_faktor"
            return treffer

        # 4) DACH-weit, spezifische Technologie
        treffer = self._suche("DE", technologie)
        if treffer:
            return treffer

        # 5) Globaler DACH-Fallback
        basis = DACH_BASIS_STUNDENSATZ.get(region[:2] if len(region) >= 2 else "DE",
                                           DACH_BASIS_STUNDENSATZ["DE"])
        tech_faktor  = TECHNOLOGIE_MULTIPLIKATOR.get(technologie, 1.0)
        reg_faktor   = BUNDESLAND_MULTIPLIKATOR.get(region, 1.0)
        median = round(basis * tech_faktor * reg_faktor, 1)
        p25, p75 = _p25_p75_aus_median(median)
        return {
            "region":             region,
            "technologie":        technologie,
            "stundensatz_median": median,
            "stundensatz_p25":    p25,
            "stundensatz_p75":    p75,
            "quelle":             "hardcoded_fallback",
            "jahr":               2024,
        }


# Modul-Level-Singleton – wird lazy beim ersten Aufruf initialisiert
_lookup_instanz: StundensatzLookup | None = None


def get_stundensatz(region: str = "DE", technologie: str = "all") -> dict:
    """
    Convenience-Wrapper mit Lazy-Initialisierung des Lookups.

    Beispiele:
      get_stundensatz("DE", "Python")    → {"stundensatz_median": 95.3, ...}
      get_stundensatz("DE-BY", "SAP")    → {"stundensatz_median": 121.4, ...}
      get_stundensatz("CH")              → {"stundensatz_median": 69.0, ...}
    """
    global _lookup_instanz
    if _lookup_instanz is None:
        _lookup_instanz = StundensatzLookup()
    return _lookup_instanz.get_stundensatz(region=region, technologie=technologie)


def reset_lookup() -> None:
    """Erzwingt Neu-Laden des Lookups (z. B. nach erneutem fetch_all_salary_data())."""
    global _lookup_instanz
    _lookup_instanz = None


# ---------------------------------------------------------------------------
# Direkt ausführbar
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="EstimateIQ – Gehaltsdaten laden")
    parser.add_argument(
        "--nur",
        choices=["so", "eurostat", "destatis"],
        help="Nur eine Quelle abrufen (so=Stack Overflow, eurostat, destatis)",
    )
    parser.add_argument(
        "--test-lookup",
        action="store_true",
        help="Lookup-Tabelle testen (benötigt bereits heruntergeladene Daten)",
    )
    args = parser.parse_args()

    if args.test_lookup:
        testfaelle = [
            ("DE",    "Python"),
            ("DE-BY", "SAP"),
            ("AT",    "Java"),
            ("CH",    "all"),
            ("DE-NW", "TypeScript"),
            ("DE",    "Rust"),
            ("AT",    "Kotlin"),  # nur Fallback erwartet
        ]
        print("\nStundensatz-Lookup Test:")
        print("─" * 70)
        for region, tech in testfaelle:
            ergebnis = get_stundensatz(region, tech)
            print(
                f"  {region:<8} {tech:<22}"
                f"  {ergebnis['stundensatz_median']:>6.1f} €/h"
                f"  [{ergebnis['stundensatz_p25']:.0f}–{ergebnis['stundensatz_p75']:.0f}]"
                f"  ← {ergebnis['quelle']}"
            )
        print("─" * 70)
        exit(0)

    n = fetch_all_salary_data()

    trenner = "═" * 55
    print(f"\n{trenner}")
    print("  EstimateIQ – Gehaltsdaten geladen")
    print(trenner)
    print(f"  Gesamt:  {n:>5,} Stundensatz-Einträge")
    print(f"  Datei:   {OUTPUT_FILE}")
    print(f"\n  Nächster Schritt:")
    print("    python -m estimateiq.data.fetch_salary_data --test-lookup")
    print(f"{trenner}\n")
