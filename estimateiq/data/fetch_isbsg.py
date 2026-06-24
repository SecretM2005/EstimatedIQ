"""
ISBSG-Importer – liest lokale ISBSG-CSV-Datei und konvertiert in EstimateIQ-Format.

Die ISBSG-Daten müssen manuell heruntergeladen werden:
  1. Registrierung auf https://www.isbsg.org/data-downloads/
  2. Kostenlose "Research Release" beantragen (~500 Projekte)
     ODER kostenpflichtige Vollversion (~8.000 Projekte) kaufen
  3. Heruntergeladene CSV-Datei nach data/isbsg_research.csv legen
  4. python -m estimateiq.data.fetch_isbsg

ISBSG-Felder (Research Release):
  Data Domain: Entwicklungsart (New Development, Enhancement, Re-development)
  Primary Programming Language: Programmiersprache
  Project Elapsed Time: Laufzeit in Monaten
  Summary Work Effort: Gesamtaufwand in Stunden
  Industry Sector: Branche
  Development Type: Projekttyp
  Application Type: Anwendungstyp
  Team Size: Teamgröße (wenn verfügbar)
  Year of Project: Erscheinungsjahr

Output: data/raw_isbsg.jsonl (kompatibel mit preprocess.py)
"""

import json
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

ISBSG_CSV        = Path("data/isbsg_research.csv")
OUTPUT_FILE      = Path("data/raw_isbsg.jsonl")
STUNDENSATZ_DACH = 85.0
STUNDEN_PRO_MONAT = 152

# Mögliche Spaltennamen je ISBSG-Release-Version
EFFORT_KANDIDATEN  = ["Summary Work Effort", "Work Effort (Hours)", "Normalised Level 1 PDR",
                      "Summary_Work_Effort", "Work_Effort"]
DAUER_KANDIDATEN   = ["Project Elapsed Time", "Project_Elapsed_Time", "Elapsed Time",
                      "Duration (Months)", "Duration"]
SPRACHE_KANDIDATEN = ["Primary Programming Language", "Primary_Programming_Language",
                      "Programming Language"]
SEKTOR_KANDIDATEN  = ["Industry Sector", "Industry_Sector", "Sector"]
TYP_KANDIDATEN     = ["Application Type", "Application_Type", "ApplicationType"]
DEVTYP_KANDIDATEN  = ["Development Type", "Development_Type", "Data Domain"]
TEAM_KANDIDATEN    = ["Team Size", "Team_Size", "Max Team Size"]
JAHR_KANDIDATEN    = ["Year of Project", "Year_of_Project", "Year Completed"]

# ISBSG Sektor → CPV
SEKTOR_ZU_CPV: dict[str, str] = {
    "banking":        "72300000",
    "finance":        "72300000",
    "insurance":      "72300000",
    "government":     "72200000",
    "defence":        "72200000",
    "defense":        "72200000",
    "manufacturing":  "72200000",
    "telecom":        "72700000",
    "telecommunication": "72700000",
    "retail":         "72200000",
    "utilities":      "72400000",
    "health":         "72200000",
    "transport":      "72200000",
}

# ISBSG Sprache → Technologie-Label
SPRACHE_ZU_TECH: dict[str, str] = {
    "java":       "Java",
    "c#":         ".NET",
    "vb.net":     ".NET",
    "c++":        "Backend",
    "python":     "Python/ML",
    "php":        "PHP",
    "javascript": "JavaScript",
    "typescript": "JavaScript",
    "swift":      "Mobile",
    "kotlin":     "Mobile",
    "abap":       "SAP",
    "cobol":      "Backend",
}


def _suche_spalte(df: pd.DataFrame, kandidaten: list[str]) -> str | None:
    low = {c.lower(): c for c in df.columns}
    for k in kandidaten:
        if k.lower() in low:
            return low[k.lower()]
    return None


def _sprache_zu_tech(sprache: str | None) -> str:
    if not sprache:
        return "Allgemein"
    s = str(sprache).lower().strip()
    for schluessel, tech in SPRACHE_ZU_TECH.items():
        if schluessel in s:
            return tech
    return "Allgemein"


def _sektor_zu_cpv(sektor: str | None) -> str:
    if not sektor:
        return "72200000"
    s = str(sektor).lower()
    for schluessel, cpv in SEKTOR_ZU_CPV.items():
        if schluessel in s:
            return cpv
    return "72200000"


def _baue_beschreibung(zeile: dict, technologie: str, sektor: str | None,
                       devtyp: str | None, apptyp: str | None) -> str:
    teile = ["Softwareprojekt"]
    if devtyp and str(devtyp).lower() not in ("nan", "none", ""):
        teile.append(str(devtyp))
    if apptyp and str(apptyp).lower() not in ("nan", "none", ""):
        teile.append(str(apptyp))
    if sektor and str(sektor).lower() not in ("nan", "none", ""):
        teile.append(f"Branche: {sektor}")
    if technologie and technologie != "Allgemein":
        teile.append(f"Technologie: {technologie}")
    return " – ".join(teile) + "."


def importiere_isbsg(csv_pfad: Path = ISBSG_CSV,
                     output_pfad: Path = OUTPUT_FILE) -> int:
    """Liest ISBSG-CSV und schreibt kompatibles JSONL."""
    if not csv_pfad.exists():
        logger.error(
            "[ISBSG] Datei nicht gefunden: %s\n"
            "  Bitte kostenlose Research Release herunterladen:\n"
            "  https://www.isbsg.org/data-downloads/\n"
            "  → Datei speichern als: %s", csv_pfad, csv_pfad
        )
        return 0

    # Trennzeichen automatisch erkennen (Komma oder Semikolon)
    raw = csv_pfad.read_text(encoding="utf-8-sig", errors="replace")
    sep = ";" if raw.count(";") > raw.count(",") else ","
    df  = pd.read_csv(csv_pfad, sep=sep, encoding="utf-8-sig", low_memory=False)
    logger.info("[ISBSG] %d Zeilen, %d Spalten geladen.", len(df), len(df.columns))
    logger.debug("[ISBSG] Spalten: %s", df.columns.tolist())

    effort_col  = _suche_spalte(df, EFFORT_KANDIDATEN)
    dauer_col   = _suche_spalte(df, DAUER_KANDIDATEN)
    sprache_col = _suche_spalte(df, SPRACHE_KANDIDATEN)
    sektor_col  = _suche_spalte(df, SEKTOR_KANDIDATEN)
    typ_col     = _suche_spalte(df, TYP_KANDIDATEN)
    devtyp_col  = _suche_spalte(df, DEVTYP_KANDIDATEN)
    team_col    = _suche_spalte(df, TEAM_KANDIDATEN)
    jahr_col    = _suche_spalte(df, JAHR_KANDIDATEN)

    if not effort_col:
        logger.error("[ISBSG] Keine Effort-Spalte gefunden. Verfügbare Spalten: %s", df.columns.tolist())
        return 0

    logger.info("[ISBSG] Spalten erkannt: effort=%s, dauer=%s, sprache=%s, sektor=%s",
                effort_col, dauer_col, sprache_col, sektor_col)

    ergebnisse: list[dict] = []
    for idx, zeile in df.iterrows():
        effort_raw = pd.to_numeric(zeile.get(effort_col), errors="coerce")
        if pd.isna(effort_raw) or effort_raw <= 0:
            continue

        # Aufwand → Stunden → Budget
        effort_h   = float(effort_raw)  # ISBSG gibt Stunden an
        budget_eur = round(effort_h * STUNDENSATZ_DACH, 2)
        if not (5_000 <= budget_eur <= 500_000_000):
            continue

        # Laufzeit
        dauer_tage = None
        if dauer_col:
            d = pd.to_numeric(zeile.get(dauer_col), errors="coerce")
            if not pd.isna(d) and d > 0:
                tage = int(float(d) * 30.44)  # Monate → Tage
                dauer_tage = tage if 7 <= tage <= 3_650 else None

        # Technologie, Sektor, Typ
        sprache    = zeile.get(sprache_col) if sprache_col else None
        sektor     = zeile.get(sektor_col)  if sektor_col  else None
        apptyp     = zeile.get(typ_col)     if typ_col     else None
        devtyp     = zeile.get(devtyp_col)  if devtyp_col  else None
        technologie = _sprache_zu_tech(sprache)
        cpv        = _sektor_zu_cpv(sektor)

        # Team
        teamgroesse = None
        if team_col:
            t = pd.to_numeric(zeile.get(team_col), errors="coerce")
            if not pd.isna(t) and t > 0:
                teamgroesse = int(float(t))

        # Jahr
        jahr = None
        if jahr_col:
            j = pd.to_numeric(zeile.get(jahr_col), errors="coerce")
            if not pd.isna(j) and 1990 <= j <= 2030:
                jahr = int(j)

        beschreibung = _baue_beschreibung(
            zeile.to_dict(), technologie,
            str(sektor) if sektor and pd.notna(sektor) else None,
            str(devtyp) if devtyp and pd.notna(devtyp) else None,
            str(apptyp) if apptyp and pd.notna(apptyp) else None,
        )

        ergebnisse.append({
            "document_id":      f"isbsg_{idx}",
            "publication_date": f"{jahr}0101" if jahr else "20100101",
            "title":            f"ISBSG Projekt {idx}",
            "description":      beschreibung,
            "cpv_code":         cpv,
            "estimated_value":  budget_eur,
            "currency":         "EUR",
            "country":          "DE",
            "duration_end":     None,
            "dauer_tage_direkt": dauer_tage,
            "notice_type":      "isbsg",
            "datenquelle":      "isbsg",
            "teamgroesse":      teamgroesse,
            "jahr":             jahr,
            "technologie":      technologie,
            "raw":              {},
        })

    output_pfad.parent.mkdir(parents=True, exist_ok=True)
    with output_pfad.open("w", encoding="utf-8") as f:
        for ds in ergebnisse:
            f.write(json.dumps(ds, ensure_ascii=False) + "\n")

    logger.info("[ISBSG] %d / %d Projekte gespeichert → %s", len(ergebnisse), len(df), output_pfad)
    return len(ergebnisse)


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="ISBSG-Daten importieren")
    parser.add_argument("--csv", type=Path, default=ISBSG_CSV,
                        help=f"Pfad zur ISBSG-CSV-Datei (Standard: {ISBSG_CSV})")
    args = parser.parse_args()

    n = importiere_isbsg(csv_pfad=args.csv)
    if n == 0:
        print("\n📋 So bekommst du die ISBSG-Daten (kostenlos):")
        print("  1. https://www.isbsg.org/data-downloads/ aufrufen")
        print('  2. "Research Only Data Release" beantragen')
        print(f"  3. CSV-Datei speichern als: {ISBSG_CSV}")
        print("  4. Nochmal ausführen: python -m estimateiq.data.fetch_isbsg")
    else:
        print(f"\nISBSG-Projekte importiert: {n}")
