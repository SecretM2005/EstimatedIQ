"""
Stack Overflow Developer Survey 2023 – DACH Stundensatz-Analyse.

Extrahiert DACH-Entwicklergehälter aus dem öffentlichen SO Survey und
aggregiert sie zu einer Stundensatz-Lookup-Tabelle für EstimateIQ.

Features:
  - DACH-Filter (Germany, Austria, Switzerland)
  - Freelancer-Aufschlag × 1.4 (trägt Sozialabgaben selbst)
  - Technologie-Mapping auf EstimateIQ-Kategorien
  - Aggregation nach Region × Technologie (Median, P25, P75)
  - Vertrauenswürdigkeits-Flag: n ≥ 10

Ausgabe: data/stundensaetze_stackoverflow.json

Verwendung:
  python -m estimateiq.data.fetch_stackoverflow
  from estimateiq.data.fetch_stackoverflow import lade_stundensaetze, lookup
"""

import io
import json
import logging
import zipfile
from datetime import date
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

OUTPUT_JSON  = Path("data/stundensaetze_stackoverflow.json")
CACHE_DIR    = Path("data/salary_cache")
CACHE_CSV    = CACHE_DIR / "so_survey_2023.csv"

SO_URL = (
    "https://cdn.stackoverflow.co/files/jo7n4k8s/production/"
    "49915bfd46d0902c3564fd9a06b509d08a20488c.zip/"
    "stack-overflow-developer-survey-2024.zip"  # Enthält 2023-Daten
)

CHF_ZU_EUR         = 0.97
USD_ZU_EUR         = 0.92
STUNDEN_PRO_JAHR   = 1_800
FREELANCER_AUFSCHLAG = 1.40   # Sozialabgaben + Ausfallrisiko
MIN_VERTRAUENSWUERDIG = 10    # Mindest-n für vertrauenswürdige Werte

DACH_LAENDER = {"Germany": "DE", "Austria": "AT", "Switzerland": "CH"}

ERLAUBTE_EMPLOYMENT = {
    "Employed, full-time",
    "Independent contractor, freelancer, or self-employed",
    "Employed, part-time",
}

# ---------------------------------------------------------------------------
# Technologie-Mapping (SO-Bezeichnung → EstimateIQ-Kategorie)
# ---------------------------------------------------------------------------

TECH_MAPPING: dict[str, str] = {
    # Python/ML
    "Python":          "Python/ML",
    "Jupyter Notebook":"Python/ML",
    "R":               "Python/ML",
    # JavaScript (inkl. TypeScript)
    "JavaScript":      "JavaScript",
    "TypeScript":      "JavaScript",
    "Node.js":         "JavaScript",
    # Java
    "Java":            "Java",
    "Groovy":          "Java",
    "Scala":           "Java",
    "Kotlin":          "Java",   # wird auch als Mobile genutzt, aber Java-JVM
    # .NET
    "C#":              ".NET",
    "VB.NET":          ".NET",
    "F#":              ".NET",
    # PHP
    "PHP":             "PHP",
    # Mobile
    "Swift":           "Mobile",
    "Dart":            "Mobile",
    "Objective-C":     "Mobile",
    # Backend-Systemsprachen
    "Go":              "Backend",
    "Rust":            "Backend",
    "C":               "Backend",
    "C++":             "Backend",
    "Bash/Shell":      "Backend",
    "PowerShell":      "Backend",
    # SAP (selten in SO, aber relevant für DACH)
    "ABAP":            "SAP",
}


def _tech_kategorie(sprachen_raw: str) -> str:
    """Gibt die erste erkannte EstimateIQ-Technologiekategorie zurück."""
    if not sprachen_raw or pd.isna(sprachen_raw):
        return "Allgemein"
    sprachen = [s.strip() for s in str(sprachen_raw).split(";")]
    for sprache in sprachen:
        if sprache in TECH_MAPPING:
            return TECH_MAPPING[sprache]
    return "Allgemein"


def _ist_freelancer(employment: str) -> bool:
    if not employment or pd.isna(employment):
        return False
    return "contractor" in str(employment).lower() or "freelancer" in str(employment).lower()


def _waehrung_zu_eur_faktor(waehrung_raw: str) -> float | None:
    """Gibt den EUR-Konversionsfaktor für eine Währungsangabe zurück."""
    if not waehrung_raw or pd.isna(waehrung_raw):
        return None
    w = str(waehrung_raw).strip().upper()
    if w.startswith("EUR"):
        return 1.0
    if w.startswith("CHF"):
        return CHF_ZU_EUR
    if w.startswith("USD"):
        return USD_ZU_EUR
    return None


# ---------------------------------------------------------------------------
# Download + Parsing
# ---------------------------------------------------------------------------

def _lade_csv() -> pd.DataFrame:
    """Lädt die Survey-CSV (gecacht nach erstem Download)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if CACHE_CSV.exists() and CACHE_CSV.stat().st_size > 500_000:
        logger.info("[SO] Verwende gecachte CSV: %s", CACHE_CSV)
        return pd.read_csv(CACHE_CSV, low_memory=False)

    logger.info("[SO] Lade Survey-ZIP (~20 MB) von Stack Overflow...")
    try:
        resp = httpx.get(SO_URL, timeout=180.0, follow_redirects=True)
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"Download fehlgeschlagen: {exc}") from exc

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        csv_name = next(
            (n for n in zf.namelist() if "results_public" in n.lower() and n.endswith(".csv")),
            None,
        )
        if not csv_name:
            raise RuntimeError(f"Keine survey_results_public.csv im ZIP. Dateien: {zf.namelist()}")
        with zf.open(csv_name) as f:
            df = pd.read_csv(f, low_memory=False)

    df.to_csv(CACHE_CSV, index=False)
    logger.info("[SO] Survey geladen: %d Zeilen, gecacht in %s.", len(df), CACHE_CSV)
    return df


def _bereinige_df(df: pd.DataFrame) -> pd.DataFrame:
    """Filtert und konvertiert den Roh-DataFrame."""
    n_start = len(df)

    # DACH-Filter
    df = df[df["Country"].isin(DACH_LAENDER)].copy()
    logger.info("[SO] DACH-Filter: %d / %d Zeilen", len(df), n_start)

    # Employment-Filter
    df["_is_valid_employment"] = df["Employment"].apply(
        lambda e: any(erlaubt in str(e) for erlaubt in ERLAUBTE_EMPLOYMENT)
        if pd.notna(e) else False
    )
    df = df[df["_is_valid_employment"]].copy()

    # Jahresgehalt (ConvertedCompYearly ist bereits in USD normalisiert vom SO)
    df["_comp_usd"] = pd.to_numeric(df["ConvertedCompYearly"], errors="coerce")
    df = df[df["_comp_usd"].between(15_000, 500_000)].copy()

    # Währung → EUR-Faktor (benutze Currency-Spalte für direkte Umrechnung)
    df["_eur_faktor"] = df["Currency"].apply(_waehrung_zu_eur_faktor)
    # Bei fehlendem Faktor: USD-Konversion aus ConvertedCompYearly
    df["_eur_faktor"] = df["_eur_faktor"].fillna(USD_ZU_EUR)

    # Jahresgehalt in EUR
    df["_comp_eur"] = df["_comp_usd"] * df["_eur_faktor"] / USD_ZU_EUR

    # Freelancer-Aufschlag
    df["_ist_freelancer"] = df["Employment"].apply(_ist_freelancer)
    df["_comp_eur_adj"] = df["_comp_eur"] * df["_ist_freelancer"].map(
        {True: FREELANCER_AUFSCHLAG, False: 1.0}
    )

    # Stundensatz
    df["stundensatz_eur"] = (df["_comp_eur_adj"] / STUNDEN_PRO_JAHR).round(2)
    df["stundensatz_eur"] = df["stundensatz_eur"].clip(lower=10.0, upper=400.0)

    # ISO-Ländercode
    df["iso_land"] = df["Country"].map(DACH_LAENDER)

    # Technologie-Kategorie
    df["tech_kategorie"] = df["LanguageHaveWorkedWith"].apply(_tech_kategorie)

    logger.info("[SO] Nach Bereinigung: %d Einträge (%.0f%% mit Gehalt)",
                len(df), 100 * len(df) / max(1, n_start))
    return df


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _aggregiere(df: pd.DataFrame) -> dict:
    """Baut die verschachtelte Stundensatz-Lookup-Tabelle."""
    ergebnis: dict = {}
    n_gesamt = len(df)

    # ── Pro Region × Technologie ──────────────────────────────────────────
    for (land, tech), gruppe in df.groupby(["iso_land", "tech_kategorie"]):
        werte = gruppe["stundensatz_eur"].dropna()
        n = len(werte)
        if n < 3:
            continue
        land_str = str(land)
        tech_str = str(tech)
        if land_str not in ergebnis:
            ergebnis[land_str] = {}

        ergebnis[land_str][tech_str] = {
            "median":            round(float(werte.median()), 1),
            "p25":               round(float(werte.quantile(0.25)), 1),
            "p75":               round(float(werte.quantile(0.75)), 1),
            "n":                 n,
            "vertrauenswuerdig": n >= MIN_VERTRAUENSWUERDIG,
        }

    # ── Gesamt-Aggregat je Land ("Allgemein") ─────────────────────────────
    for land, gruppe in df.groupby("iso_land"):
        werte = gruppe["stundensatz_eur"].dropna()
        n = len(werte)
        if n < 3:
            continue
        land_str = str(land)
        if land_str not in ergebnis:
            ergebnis[land_str] = {}

        ergebnis[land_str]["Allgemein"] = {
            "median":            round(float(werte.median()), 1),
            "p25":               round(float(werte.quantile(0.25)), 1),
            "p75":               round(float(werte.quantile(0.75)), 1),
            "n":                 n,
            "vertrauenswuerdig": n >= MIN_VERTRAUENSWUERDIG,
        }

    ergebnis["quelle"]       = "stackoverflow_survey_2023"
    ergebnis["aktualisiert"] = str(date.today())
    ergebnis["n_gesamt"]     = n_gesamt

    return ergebnis


# ---------------------------------------------------------------------------
# Statistik-Ausgabe
# ---------------------------------------------------------------------------

def _zeige_statistik(df: pd.DataFrame, lookup: dict) -> None:
    """Gibt Übersichts-Statistik und Tabelle für DE aus."""
    trenner = "─" * 62

    print(f"\n{trenner}")
    print("  Stack Overflow Survey 2023 – DACH Statistik")
    print(trenner)
    print(f"\n  Responses gesamt: {lookup['n_gesamt']:>6,}")
    for land in ["DE", "AT", "CH"]:
        n = df[df["iso_land"] == land]["stundensatz_eur"].notna().sum()
        if n:
            print(f"  {land}:              {n:>6,}")

    print(f"\n  Stundensatz-Verteilung DACH:")
    werte = df["stundensatz_eur"].dropna()
    print(f"    Min:    {werte.min():.0f} €/h")
    print(f"    P25:    {werte.quantile(0.25):.0f} €/h")
    print(f"    Median: {werte.median():.0f} €/h")
    print(f"    P75:    {werte.quantile(0.75):.0f} €/h")
    print(f"    Max:    {werte.max():.0f} €/h")

    print(f"\n  Stundensätze DE (Top Technologien):")
    print(f"  {'Technologie':<22} {'n':>5}  {'P25':>5}  {'Median':>6}  {'P75':>5}  {'OK':>3}")
    print(f"  {'─'*22}  {'─'*5}  {'─'*5}  {'─'*6}  {'─'*5}  {'─'*3}")

    de_data = lookup.get("DE", {})
    # Sortiere nach n
    tech_items = [(tech, v) for tech, v in de_data.items()
                  if tech not in ("Allgemein",) and isinstance(v, dict)]
    for tech, v in sorted(tech_items, key=lambda x: -x[1]["n"]):
        ok = "✓" if v["vertrauenswuerdig"] else "~"
        print(f"  {tech:<22}  {v['n']:>5}  {v['p25']:>4.0f}€  {v['median']:>5.0f}€  {v['p75']:>4.0f}€  {ok:>3}")

    # Allgemein separat
    if "Allgemein" in de_data:
        v = de_data["Allgemein"]
        print(f"  {'─'*22}  {'─'*5}  {'─'*5}  {'─'*6}  {'─'*5}  {'─'*3}")
        ok = "✓" if v["vertrauenswuerdig"] else "~"
        print(f"  {'Allgemein (DE)':<22}  {v['n']:>5}  {v['p25']:>4.0f}€  {v['median']:>5.0f}€  {v['p75']:>4.0f}€  {ok:>3}")

    # Vergleich mit Hardcoded-Fallback
    HARTCODIERT: dict[str, float] = {
        "Python/ML":  63.3,
        "JavaScript": 54.0,
        "Java":       57.5,
        ".NET":       55.0,
        "PHP":        43.0,
        "Mobile":     60.0,
        "Backend":    62.0,
        "SAP":        76.0,
        "Allgemein":  47.5,
    }
    print(f"\n  Vergleich mit bisherigen Fallback-Werten (DE):")
    print(f"  {'Technologie':<22} {'Alt':>6}  {'SO Median':>9}  {'Δ':>6}")
    print(f"  {'─'*22}  {'─'*6}  {'─'*9}  {'─'*6}")
    for tech, alt in HARTCODIERT.items():
        if tech in de_data:
            neu = de_data[tech]["median"]
            delta = (neu / alt - 1) * 100
            flag = " !" if abs(delta) > 15 else ""
            print(f"  {tech:<22}  {alt:>5.0f}€  {neu:>8.0f}€  {delta:>+5.0f}%{flag}")
    print(f"\n{trenner}\n")


# ---------------------------------------------------------------------------
# Haupt-Export
# ---------------------------------------------------------------------------

def fetch_and_process(output_path: Path = OUTPUT_JSON) -> dict:
    """Lädt SO Survey, verarbeitet DACH-Daten und speichert JSON-Lookup."""
    df_roh = _lade_csv()
    df     = _bereinige_df(df_roh)
    lookup = _aggregiere(df)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(lookup, f, ensure_ascii=False, indent=2)

    logger.info("[SO] Stundensatz-Lookup gespeichert: %s (%d Einträge)",
                output_path, lookup["n_gesamt"])
    return lookup


def lade_stundensaetze(pfad: Path = OUTPUT_JSON) -> dict | None:
    """Lädt den JSON-Lookup (None wenn nicht vorhanden)."""
    if not pfad.exists():
        return None
    with pfad.open(encoding="utf-8") as f:
        return json.load(f)


def lookup(region: str, technologie: str) -> dict:
    """
    Gibt Stundensatz-Daten zurück mit 4-stufigem Fallback:
      1. region + technologie (exakt)
      2. Oberland (DE-BY → DE) + technologie
      3. region + "Allgemein"
      4. DE + "Allgemein"
    """
    FALLBACK_STUNDENSATZ: dict[str, dict[str, float]] = {
        "DE": {"median": 55.0, "p25": 42.0, "p75": 72.0},
        "AT": {"median": 50.0, "p25": 38.0, "p75": 65.0},
        "CH": {"median": 76.0, "p25": 60.0, "p75": 98.0},
    }

    daten = lade_stundensaetze()
    if not daten:
        land   = region[:2].upper() if len(region) >= 2 else "DE"
        fb     = FALLBACK_STUNDENSATZ.get(land, FALLBACK_STUNDENSATZ["DE"])
        return {**fb, "n": 0, "vertrauenswuerdig": False, "quelle": "hardcoded_fallback"}

    region_upper = region.upper().strip()
    tech_norm    = technologie.strip()

    def _suche(reg: str, tech: str) -> dict | None:
        reg_data = daten.get(reg, {})
        if tech in reg_data and isinstance(reg_data[tech], dict):
            e = reg_data[tech]
            return {
                "median": e["median"], "p25": e["p25"], "p75": e["p75"],
                "n": e["n"], "vertrauenswuerdig": e["vertrauenswuerdig"],
                "quelle": "stackoverflow_survey_2023",
            }
        return None

    # 1. Exakt
    treffer = _suche(region_upper, tech_norm)
    if treffer:
        return treffer

    # 2. Oberland
    if "-" in region_upper:
        oberland = region_upper.split("-")[0]
        treffer  = _suche(oberland, tech_norm)
        if treffer:
            return treffer

    # 3. Region + Allgemein
    treffer = _suche(region_upper, "Allgemein")
    if treffer:
        return treffer

    # 4. DE + Allgemein
    treffer = _suche("DE", "Allgemein")
    if treffer:
        return treffer

    # 5. Hardcoded
    land = region_upper[:2]
    fb   = FALLBACK_STUNDENSATZ.get(land, FALLBACK_STUNDENSATZ["DE"])
    return {**fb, "n": 0, "vertrauenswuerdig": False, "quelle": "hardcoded_fallback"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Stack Overflow Survey – DACH Stundensätze")
    parser.add_argument("--nur-statistik", action="store_true",
                        help="Nur Statistik aus vorhandenem JSON anzeigen (kein Download)")
    args = parser.parse_args()

    print("\nStack Overflow Developer Survey Loader")
    print("Survey-Jahr: 2023 (aktuellste verfügbare Version)")
    print("Nächstes Update erwartet: Mai 2025")
    print("URL: survey.stackoverflow.co/datasets\n")

    if args.nur_statistik:
        daten = lade_stundensaetze()
        if not daten:
            print(f"Keine Daten unter {OUTPUT_JSON}. Bitte zuerst ohne --nur-statistik ausführen.")
        else:
            print(f"n_gesamt: {daten['n_gesamt']}, Quelle: {daten['quelle']}")
    else:
        df_roh = _lade_csv()
        df_clean = _bereinige_df(df_roh)
        lkp = fetch_and_process()
        _zeige_statistik(df_clean, lkp)
        print(f"JSON gespeichert: {OUTPUT_JSON}")
