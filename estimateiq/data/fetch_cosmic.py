"""
COSMIC Dataset Connector – lädt öffentlich verfügbare COSMIC-Benchmark-Daten.

Öffentliche Quellen (automatisch):
  1. ISBSG COSMIC Datensatz – Zenodo Record #268482 (ARFF, Aufwand in Stunden)
  2. Valdes-Souto COSMIC CSV – Derek Jones GitHub (57 Projekte, Person-Stunden)

Optionaler Manuell-Import (Originaldatensatz aus dem Paper):
  Das Dataset zu DOI 10.1016/j.jss.2025.112602 (Yürüm/Ünlü/Demirörs, JSS 2025)
  ist nicht öffentlich zugänglich. Falls Zugang über Elsevier besteht, die
  supplementary CSV-Datei herunterladen und so einlesen:

    python -m estimateiq.data.fetch_cosmic --lokal <pfad_zur_datei.csv>

  Erwartetes Schema:
    projekt_id, beschreibung, effort_personenmonate,
    groesse_cosmic_fp, typ, land

Konvertierung:
  Wenn Aufwand in Personenmonaten (--lokal):
    budget_eur = effort_personenmonate × 152 h/Monat × 85 €/h
  Wenn Aufwand in Stunden (Zenodo/Valdes-Souto):
    budget_eur = effort_stunden × 85 €/h

Ausgabe: data/raw_cosmic.jsonl (kompatibel mit preprocess.py)
"""

import argparse
import json
import logging
import time
from io import StringIO
from pathlib import Path

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

STUNDENSATZ_DACH: float = 85.0
STUNDEN_PRO_MONAT: int  = 152

RAW_DATA_DIR   = Path("data")
OUTPUT_FILE    = RAW_DATA_DIR / "raw_cosmic.jsonl"

ZENODO_API_URL    = "https://zenodo.org/api/records/268482"
DEREK_JONES_BASE  = "https://raw.githubusercontent.com/Derek-Jones/Software-estimation-datasets/master"
VALDES_SOUTO_URL  = f"{DEREK_JONES_BASE}/Valdes-Souto.csv"

# ---------------------------------------------------------------------------
# Anwendungstyp → CPV-Mapping
# ---------------------------------------------------------------------------

TYP_ZU_CPV: dict[str, str] = {
    "business":       "72200000",
    "finance":        "72300000",
    "financial":      "72300000",
    "banking":        "72300000",
    "embedded":       "72200000",
    "real-time":      "72200000",
    "real time":      "72200000",
    "infrastructure": "72700000",
    "management":     "72200000",
    "information":    "72300000",
    "operational":    "72500000",
    "military":       "72200000",
    "scientific":     "72300000",
    "database":       "72300000",
    "data":           "72300000",
    "telecommunication": "72700000",
    "support":        "72500000",
    "web":            "72400000",
    "internet":       "72400000",
    "erp":            "72200000",
    "sap":            "72200000",
}


def _cpv_fuer_typ(typ: str | None) -> str:
    if not typ:
        return "72200000"
    text = str(typ).lower()
    for schluessel, cpv in TYP_ZU_CPV.items():
        if schluessel in text:
            return cpv
    return "72200000"


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _finde_spalte(df: pd.DataFrame, kandidaten: list[str]) -> str | None:
    """Sucht die erste passende Spalte (case-insensitive)."""
    niedrig = {c.lower().strip(): c for c in df.columns}
    for k in kandidaten:
        if k.lower() in niedrig:
            return niedrig[k.lower()]
    return None


def _parse_arff(text: str) -> pd.DataFrame:
    """
    Einfacher ARFF-Parser (Weka-Format).
    Unterstützt numerische und nominale Attribute, '?' als fehlender Wert.
    """
    attribute_names: list[str] = []
    daten_zeilen: list[str] = []
    in_daten = False

    for zeile in text.splitlines():
        z = zeile.strip()
        if not z or z.startswith("%"):
            continue
        if z.upper().startswith("@ATTRIBUTE"):
            teile = z.split(None, 2)
            if len(teile) >= 2:
                attribute_names.append(teile[1].strip("'\""))
        elif z.upper().startswith("@DATA"):
            in_daten = True
        elif in_daten:
            daten_zeilen.append(z)

    if not attribute_names or not daten_zeilen:
        return pd.DataFrame()

    n = len(attribute_names)
    zeilen_geteilt: list[list] = []
    for z in daten_zeilen:
        werte: list = []
        in_quotes = False
        aktuell: list[str] = []
        for ch in z + ",":
            if ch in ("'", '"'):
                in_quotes = not in_quotes
            elif ch == "," and not in_quotes:
                wert = "".join(aktuell).strip().strip("'\"")
                werte.append(None if wert in ("?", "") else wert)
                aktuell = []
            else:
                aktuell.append(ch)
        zeilen_geteilt.append((werte + [None] * n)[:n])

    return pd.DataFrame(zeilen_geteilt, columns=attribute_names)


# ---------------------------------------------------------------------------
# Quelle 1: Zenodo ISBSG COSMIC (Record #268482)
# ---------------------------------------------------------------------------

def _lade_zenodo_cosmic() -> list[dict]:
    """Lädt ISBSG COSMIC-Datensatz von Zenodo (Record #268482)."""
    logger.info("[COSMIC/Zenodo] Rufe Dateiliste ab (Record 268482)...")
    try:
        resp = httpx.get(ZENODO_API_URL, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
        record = resp.json()
    except Exception as exc:
        logger.warning("[COSMIC/Zenodo] API-Fehler: %s", exc)
        return []

    # Zenodo liefert Dateien je nach API-Version unterschiedlich
    dateien = record.get("files") or record.get("metadata", {}).get("resource_type", [])
    if not dateien:
        logger.warning("[COSMIC/Zenodo] Keine Dateien im Record gefunden. Antwort-Keys: %s",
                       list(record.keys()))
        return []

    alle: list[dict] = []
    for datei_info in dateien:
        dateiname = datei_info.get("filename") or datei_info.get("key", "")
        download_url = (
            datei_info.get("links", {}).get("download")
            or datei_info.get("links", {}).get("self", "")
        )
        if not download_url or not dateiname:
            continue

        ext = Path(dateiname).suffix.lower()
        logger.info("[COSMIC/Zenodo] Lade %s ...", dateiname)
        try:
            dresp = httpx.get(download_url, timeout=120.0, follow_redirects=True)
            dresp.raise_for_status()

            if ext == ".arff":
                df = _parse_arff(dresp.text)
            elif ext in (".csv", ".tsv"):
                sep = "\t" if ext == ".tsv" else ","
                df = pd.read_csv(StringIO(dresp.text), sep=sep, on_bad_lines="skip")
            elif ext in (".xlsx", ".xls"):
                df = pd.read_excel(dresp.content)
            else:
                logger.debug("[COSMIC/Zenodo] Format nicht unterstützt: %s", dateiname)
                continue

            projekte = _konvertiere_isbsg_cosmic(dateiname, df)
            logger.info("[COSMIC/Zenodo] %s → %d Projekte.", dateiname, len(projekte))
            alle.extend(projekte)
            time.sleep(0.5)

        except Exception as exc:
            logger.warning("[COSMIC/Zenodo] Fehler bei %s: %s", dateiname, exc)

    return alle


def _konvertiere_isbsg_cosmic(dateiname: str, df: pd.DataFrame) -> list[dict]:
    """Konvertiert einen ISBSG/COSMIC DataFrame in das EstimateIQ-Format."""
    if df.empty:
        return []

    logger.info("[COSMIC] Spalten in %s: %s", dateiname, list(df.columns)[:15])

    # Aufwand in Stunden
    effort_sp = _finde_spalte(df, [
        "Normalised.Work.Effort", "Work.Effort.Level.1", "Actual.Work.Effort",
        "Sum.of.Work.Effort", "ActualEffort", "actual_effort",
        "Effort", "effort", "HH", "Hours",
    ])
    # COSMIC Function Points
    groesse_sp = _finde_spalte(df, [
        "FP", "AFP", "COSMIC_FP", "cosmic_fp", "CFP", "Functional.Size",
        "COSMIC.Size", "Size", "Normalised.Level.1.PDR",
    ])
    typ_sp    = _finde_spalte(df, ["Application.Type", "AppType", "Type", "Domain", "application_type"])
    land_sp   = _finde_spalte(df, ["Country", "country", "Land"])
    id_sp     = _finde_spalte(df, ["Project.ID", "ProjectID", "ID", "Projct", "Number"])
    dauer_sp  = _finde_spalte(df, ["Project.Elapsed.Time", "Elapsed.Time", "Duration", "ElapsedTime"])

    if not effort_sp:
        logger.warning("[COSMIC] Keine Effort-Spalte in %s – übersprungen.", dateiname)
        return []

    dataset_label = Path(dateiname).stem
    ergebnisse: list[dict] = []

    for idx, zeile in df.iterrows():
        effort_roh = pd.to_numeric(zeile.get(effort_sp), errors="coerce")
        if pd.isna(effort_roh) or effort_roh <= 0:
            continue

        effort_stunden  = float(effort_roh)
        effort_monate   = effort_stunden / STUNDEN_PRO_MONAT
        budget_eur      = round(effort_stunden * STUNDENSATZ_DACH, 2)

        if not (5_000 <= budget_eur <= 500_000_000):
            continue

        cosmic_fp = None
        if groesse_sp:
            fp_roh = pd.to_numeric(zeile.get(groesse_sp), errors="coerce")
            if not pd.isna(fp_roh) and fp_roh > 0:
                cosmic_fp = float(fp_roh)

        typ_text  = str(zeile[typ_sp]).strip()  if typ_sp  and pd.notna(zeile.get(typ_sp))  else None
        land_text = str(zeile[land_sp]).strip() if land_sp and pd.notna(zeile.get(land_sp)) else None
        proj_id   = str(zeile[id_sp])           if id_sp   and pd.notna(zeile.get(id_sp))   else str(idx)

        dauer_tage = None
        if dauer_sp:
            d = pd.to_numeric(zeile.get(dauer_sp), errors="coerce")
            if not pd.isna(d) and d > 0:
                tage = int(float(d) * 30.44)
                dauer_tage = tage if 7 <= tage <= 3_650 else None

        beschreibung_teile = [f"COSMIC-Softwareprojekt {dataset_label}: {proj_id}."]
        if typ_text:
            beschreibung_teile.append(f"Anwendungstyp: {typ_text}.")
        if cosmic_fp:
            beschreibung_teile.append(f"Funktionsgröße: {cosmic_fp:.0f} COSMIC Function Points.")
        beschreibung_teile.append(
            f"Aufwand: {effort_monate:.1f} Personenmonate ({effort_stunden:.0f} Stunden). "
            f"Geschätztes Budget: {budget_eur:,.0f} EUR (DACH-Satz {STUNDENSATZ_DACH:.0f} €/h)."
        )

        ergebnisse.append({
            "document_id":           f"cosmic_{dataset_label}_{proj_id}",
            "publication_date":      "20240101",
            "title":                 f"COSMIC {dataset_label}: {proj_id}"
                                     + (f" ({typ_text})" if typ_text else ""),
            "description":           " ".join(beschreibung_teile),
            "cpv_code":              _cpv_fuer_typ(typ_text),
            "estimated_value":       budget_eur,
            "currency":              "EUR",
            "country":               (land_text[:2].upper() if land_text else "DE"),
            "duration_end":          None,
            "dauer_tage_direkt":     dauer_tage,
            "notice_type":           "cosmic",
            "datenquelle":           "cosmic",
            "groesse_cosmic_fp":     cosmic_fp,
            "effort_personenmonate": round(effort_monate, 2),
            "raw":                   {},
        })

    return ergebnisse


# ---------------------------------------------------------------------------
# Quelle 2: Valdes-Souto (Derek Jones GitHub)
# ---------------------------------------------------------------------------

def _lade_valdes_souto() -> list[dict]:
    """Lädt den Valdes-Souto COSMIC-Datensatz von Derek Jones' GitHub."""
    logger.info("[COSMIC/Valdes-Souto] Lade CSV von GitHub...")
    try:
        resp = httpx.get(VALDES_SOUTO_URL, timeout=30.0, follow_redirects=True)
        if resp.status_code == 404:
            logger.warning("[COSMIC/Valdes-Souto] Datei nicht gefunden.")
            return []
        resp.raise_for_status()
        df = pd.read_csv(StringIO(resp.text))
        logger.info("[COSMIC/Valdes-Souto] %d Zeilen geladen, Spalten: %s",
                    len(df), list(df.columns))
    except Exception as exc:
        logger.warning("[COSMIC/Valdes-Souto] Fehler: %s", exc)
        return []

    effort_sp  = _finde_spalte(df, ["Effort", "HH", "Hours", "PersonHours", "Work"])
    fp_sp      = _finde_spalte(df, ["COSMIC_FP", "CFP", "FP", "BASE"])
    id_sp      = _finde_spalte(df, ["Projct", "ID", "Project", "Name", "Number"])

    if not effort_sp:
        logger.warning("[COSMIC/Valdes-Souto] Keine Effort-Spalte gefunden.")
        return []

    ergebnisse: list[dict] = []
    for idx, zeile in df.iterrows():
        effort_roh = pd.to_numeric(zeile.get(effort_sp), errors="coerce")
        if pd.isna(effort_roh) or effort_roh <= 0:
            continue

        # Valdes-Souto: Aufwand in Person-Stunden
        effort_stunden = float(effort_roh)
        effort_monate  = effort_stunden / STUNDEN_PRO_MONAT
        budget_eur     = round(effort_stunden * STUNDENSATZ_DACH, 2)

        if not (5_000 <= budget_eur <= 500_000_000):
            continue

        cosmic_fp = None
        if fp_sp:
            fp_roh = pd.to_numeric(zeile.get(fp_sp), errors="coerce")
            if not pd.isna(fp_roh) and fp_roh > 0:
                cosmic_fp = float(fp_roh)

        proj_id = str(zeile[id_sp]) if id_sp and pd.notna(zeile.get(id_sp)) else str(idx)

        beschreibung_teile = [
            f"COSMIC-Softwareprojekt Valdes-Souto-Datensatz: Projekt {proj_id}.",
            "Quelle: Mexikanische IT-Projekte mit COSMIC-Messungen (AMMS-Repository).",
        ]
        if cosmic_fp:
            beschreibung_teile.append(f"Funktionsgröße: {cosmic_fp:.0f} COSMIC Function Points.")
        beschreibung_teile.append(
            f"Aufwand: {effort_monate:.1f} Personenmonate ({effort_stunden:.0f} Stunden). "
            f"Geschätztes Budget: {budget_eur:,.0f} EUR (DACH-Satz {STUNDENSATZ_DACH:.0f} €/h)."
        )

        ergebnisse.append({
            "document_id":           f"cosmic_valdes_souto_{proj_id}",
            "publication_date":      "20200101",
            "title":                 f"COSMIC Valdes-Souto: Projekt {proj_id}",
            "description":           " ".join(beschreibung_teile),
            "cpv_code":              "72200000",
            "estimated_value":       budget_eur,
            "currency":              "EUR",
            "country":               "MX",
            "duration_end":          None,
            "dauer_tage_direkt":     None,
            "notice_type":           "cosmic",
            "datenquelle":           "cosmic",
            "groesse_cosmic_fp":     cosmic_fp,
            "effort_personenmonate": round(effort_monate, 2),
            "raw":                   {},
        })

    logger.info("[COSMIC/Valdes-Souto] %d Projekte extrahiert.", len(ergebnisse))
    return ergebnisse


# ---------------------------------------------------------------------------
# Quelle 3: Lokale Datei (Originaldatensatz aus dem Paper)
# ---------------------------------------------------------------------------

def _lade_lokal(pfad: Path) -> list[dict]:
    """
    Lädt den COSMIC-Datensatz aus einer lokalen CSV/Excel-Datei.

    Erwartetes Schema (DOI 10.1016/j.jss.2025.112602):
      projekt_id, beschreibung, effort_personenmonate,
      groesse_cosmic_fp, typ, land
    """
    logger.info("[COSMIC/Lokal] Lade %s ...", pfad)
    ext = pfad.suffix.lower()

    try:
        if ext in (".xlsx", ".xls"):
            df = pd.read_excel(pfad)
        else:
            # CSV: Trennzeichen automatisch erkennen
            for sep in (",", ";", "\t"):
                df = pd.read_csv(pfad, sep=sep, encoding="utf-8-sig", on_bad_lines="skip")
                if len(df.columns) > 1:
                    break
    except Exception as exc:
        logger.error("[COSMIC/Lokal] Lesefehler: %s", exc)
        return []

    logger.info("[COSMIC/Lokal] %d Zeilen geladen, Spalten: %s", len(df), list(df.columns))

    id_sp     = _finde_spalte(df, ["projekt_id", "project_id", "ID", "ProjectID", "Nr"])
    beschr_sp = _finde_spalte(df, ["beschreibung", "description", "Description", "Name"])
    effort_sp = _finde_spalte(df, [
        "effort_personenmonate", "PersonMonths", "PM", "person_months",
        "Effort", "effort",
    ])
    fp_sp     = _finde_spalte(df, [
        "groesse_cosmic_fp", "cosmic_fp", "COSMIC_FP", "CFP", "FP", "Size",
    ])
    typ_sp    = _finde_spalte(df, ["typ", "type", "Type", "ApplicationType", "Domain"])
    land_sp   = _finde_spalte(df, ["land", "country", "Country", "Land"])

    if not effort_sp:
        logger.error("[COSMIC/Lokal] Pflichtfeld 'effort_personenmonate' nicht gefunden. "
                     "Vorhandene Spalten: %s", list(df.columns))
        return []

    ergebnisse: list[dict] = []
    for idx, zeile in df.iterrows():
        effort_roh = pd.to_numeric(zeile.get(effort_sp), errors="coerce")
        if pd.isna(effort_roh) or effort_roh <= 0:
            continue

        # Aufwand in Personenmonaten → Budget
        effort_monate = float(effort_roh)
        budget_eur    = round(effort_monate * STUNDEN_PRO_MONAT * STUNDENSATZ_DACH, 2)

        if not (5_000 <= budget_eur <= 500_000_000):
            continue

        cosmic_fp = None
        if fp_sp:
            fp_roh = pd.to_numeric(zeile.get(fp_sp), errors="coerce")
            if not pd.isna(fp_roh) and fp_roh > 0:
                cosmic_fp = float(fp_roh)

        typ_text  = str(zeile[typ_sp]).strip()  if typ_sp  and pd.notna(zeile.get(typ_sp))  else None
        land_text = str(zeile[land_sp]).strip() if land_sp and pd.notna(zeile.get(land_sp)) else "DE"
        proj_id   = str(zeile[id_sp])           if id_sp   and pd.notna(zeile.get(id_sp))   else str(idx)

        # Beschreibung aus Datei oder generiert
        if beschr_sp and pd.notna(zeile.get(beschr_sp)) and str(zeile[beschr_sp]).strip():
            beschreibung = str(zeile[beschr_sp]).strip()
        else:
            teile = [f"COSMIC-Softwareprojekt (Paper DOI 10.1016/j.jss.2025.112602): {proj_id}."]
            if typ_text:
                teile.append(f"Anwendungstyp: {typ_text}.")
            if cosmic_fp:
                teile.append(f"Funktionsgröße: {cosmic_fp:.0f} COSMIC Function Points.")
            teile.append(
                f"Aufwand: {effort_monate:.1f} Personenmonate → "
                f"Budget: {budget_eur:,.0f} EUR."
            )
            beschreibung = " ".join(teile)

        ergebnisse.append({
            "document_id":           f"cosmic_paper_{proj_id}",
            "publication_date":      "20250101",
            "title":                 f"COSMIC Paper {proj_id}"
                                     + (f" ({typ_text})" if typ_text else ""),
            "description":           beschreibung,
            "cpv_code":              _cpv_fuer_typ(typ_text),
            "estimated_value":       budget_eur,
            "currency":              "EUR",
            "country":               land_text[:2].upper() if len(land_text) >= 2 else "DE",
            "duration_end":          None,
            "dauer_tage_direkt":     None,
            "notice_type":           "cosmic",
            "datenquelle":           "cosmic",
            "groesse_cosmic_fp":     cosmic_fp,
            "effort_personenmonate": round(effort_monate, 2),
            "raw":                   {},
        })

    logger.info("[COSMIC/Lokal] %d / %d Zeilen übernommen.", len(ergebnisse), len(df))
    return ergebnisse


# ---------------------------------------------------------------------------
# Haupt-Exportfunktion
# ---------------------------------------------------------------------------

def fetch_cosmic_data(
    output_path: Path = OUTPUT_FILE,
    lokal: Path | None = None,
) -> int:
    """Lädt alle COSMIC-Datensätze und speichert als JSONL."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    alle: list[dict] = []

    if lokal:
        alle.extend(_lade_lokal(lokal))
    else:
        alle.extend(_lade_zenodo_cosmic())
        time.sleep(0.3)
        alle.extend(_lade_valdes_souto())

    # Duplikate über document_id entfernen
    gesehen: set[str] = set()
    eindeutig: list[dict] = []
    for ds in alle:
        did = ds["document_id"]
        if did not in gesehen:
            gesehen.add(did)
            eindeutig.append(ds)

    with output_path.open("w", encoding="utf-8") as f:
        for ds in eindeutig:
            f.write(json.dumps(ds, ensure_ascii=False) + "\n")

    logger.info("[COSMIC] Gesamt: %d Datensätze → %s", len(eindeutig), output_path)
    return len(eindeutig)


# ---------------------------------------------------------------------------
# Direkt ausführbar
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="COSMIC Dataset Connector – lädt öffentliche COSMIC-Benchmark-Daten"
    )
    parser.add_argument(
        "--lokal", type=Path, default=None,
        metavar="DATEI",
        help=(
            "Pfad zur lokalen CSV/Excel-Datei des Originaldatensatzes "
            "(DOI 10.1016/j.jss.2025.112602). "
            "Schema: projekt_id, beschreibung, effort_personenmonate, "
            "groesse_cosmic_fp, typ, land"
        ),
    )
    args = parser.parse_args()

    n = fetch_cosmic_data(lokal=args.lokal)
    print(f"\nCOSMIC-Datensätze gespeichert: {n}")
    if n == 0:
        print(
            "\nHinweis: Der Originaldatensatz (DOI 10.1016/j.jss.2025.112602) ist nicht\n"
            "öffentlich zugänglich. Bei Elsevier-Zugang die supplementary CSV herunterladen\n"
            "und mit --lokal <datei.csv> einlesen.\n"
        )
