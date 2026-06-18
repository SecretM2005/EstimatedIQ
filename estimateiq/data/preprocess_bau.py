"""
Datenvorverarbeitung für EstimateIQ Bau.

Pipeline:
  1. Rohdaten aus fetch_ted_bau.py laden (JSON Lines)
  2. Texte bereinigen & filtern
  3. CPV → Gewerk & Projekttyp ableiten
  4. Budget zu EUR normalisieren
  5. Laufzeit in Tagen berechnen
  6. Geocoding via geo_features.py
  7. BBSR-Baupreisindex aus fetch_bbsr.py
  8. Speichern als Parquet + CSV
  9. Statistik ausgeben
"""

import json
import logging
import re
from pathlib import Path

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

BUDGET_MIN_EUR  = 5_000
BUDGET_MAX_EUR  = 50_000_000
DAUER_MIN_TAGE  = 7
DAUER_MAX_TAGE  = 1_825    # 5 Jahre
BESCHREIBUNG_MIN_ZEICHEN = 30

# Jahresdurchschnittskurse → EUR
FX_ZU_EUR: dict[str, float] = {
    "EUR": 1.000,
    "CHF": 1.050,
    "GBP": 1.170,
    "USD": 0.930,
    "DKK": 0.134,
    "SEK": 0.088,
    "NOK": 0.086,
    "PLN": 0.232,
    "CZK": 0.040,
}

# CPV-Code → Gewerk (Prefix-Matching, längster Match gewinnt)
CPV_GEWERK: dict[str, str] = {
    # Elektro
    "453100": "Elektro",
    "453110": "Elektro",
    "453120": "Elektro",
    "453130": "Aufzüge/Rolltreppen",
    "453140": "Kommunikationsanlagen",
    "453150": "Elektroinstallation",
    "453160": "Beleuchtung",
    "453170": "Elektrische Ausrüstung",
    # Sanitär / Heizung
    "453300": "Sanitär/Heizung",
    "453310": "Heizung/Lüftung/Klima",
    "453320": "Sanitär",
    "453330": "Gasinstallation",
    "453340": "Zäune/Sicherung",
    "453350": "Maschinentechnik",
    # Maler / Fassade
    "454400": "Maler",
    "454410": "Verglasung",
    "454420": "Malerarbeiten",
    "454430": "Fassade",
    # Fliesen / Boden
    "454300": "Fliesen/Boden",
    "454310": "Fliesen",
    "454320": "Bodenbelag",
    # Zimmerer / Tischler
    "454200": "Zimmerer/Tischler",
    "454210": "Zimmerei/Tischler",
    "454220": "Holzbau",
    # Hochbau / Neubau
    "452100": "Hochbau/Neubau",
    "452110": "Wohngebäude",
    "452120": "Freizeit/Sport",
    "452130": "Gewerbegebäude",
    "452140": "Schulen",
    "452150": "Gesundheitsgebäude",
    "452160": "Sicherheitsgebäude",
    "452200": "Ingenieurhochbau",
    "452300": "Tiefbau/Straße",
    "452400": "Wasserbau",
    "452500": "Industrie/Bergbau",
    "452600": "Dach/Klempner",
    "452610": "Dach",
    "452620": "Spezialtiefbau",
    # Ausbau
    "454100": "Putz/Stuck",
    "454500": "Ausbau sonstig",
    "454000": "Ausbau allgemein",
    # Gebäudetechnik
    "453000": "Gebäudetechnik",
    # Vorbereitung
    "451000": "Bauvorbereitung",
    "451100": "Abbruch/Freilegung",
    # Allgemein
    "452000": "Hoch- und Tiefbau",
    "450000": "Bauarbeiten allgemein",
}

# CPV → Projekttyp (grobe Kategorien)
CPV_PROJEKTTYP: dict[str, str] = {
    "452": "Hoch- und Tiefbau",
    "451": "Bauvorbereitung",
    "453": "Technische Gebäudeausrüstung",
    "454": "Ausbauarbeiten",
    "450": "Bauarbeiten allgemein",
}


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _bereinige_text(text: str | None) -> str:
    """Entfernt HTML, normalisiert Whitespace."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&nbsp;", " ")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return re.sub(r"\s+", " ", text).strip()


def _parse_cpv_bau(cpv_roh: str | None) -> str | None:
    """Extrahiert 8-stelligen Bau-CPV-Code (45xxxxxx)."""
    if cpv_roh is None:
        return None
    treffer = re.search(r"\b(\d{8})\b", str(cpv_roh))
    if not treffer:
        return None
    code = int(treffer.group(1))
    if not (45_000_000 <= code <= 45_999_999):
        return None
    return f"{code:08d}"


def _cpv_zu_gewerk(cpv_str: str | None) -> str:
    """Leitet das Gewerk aus dem CPV-Code ab (längster Prefix-Match)."""
    if not cpv_str or len(cpv_str) < 6:
        return "Sonstiges"
    # Prefix von lang nach kurz
    for laenge in (6, 5, 4, 3):
        prefix = cpv_str[:laenge]
        if prefix in CPV_GEWERK:
            return CPV_GEWERK[prefix]
    return "Sonstiges"


def _cpv_zu_projekttyp(cpv_str: str | None) -> str:
    """Leitet den groben Projekttyp aus den ersten 3 CPV-Stellen ab."""
    if not cpv_str or len(cpv_str) < 3:
        return "Bauarbeiten allgemein"
    prefix = cpv_str[:3]
    return CPV_PROJEKTTYP.get(prefix, "Bauarbeiten allgemein")


def _budget_zu_eur(wert: float | None, waehrung: str | None) -> float | None:
    """Konvertiert Betrag → EUR."""
    if wert is None or wert <= 0:
        return None
    kuerzel = (waehrung or "EUR").strip().upper()
    faktor  = FX_ZU_EUR.get(kuerzel)
    if faktor is None:
        return None
    return round(wert * faktor, 2)


def _berechne_dauer(datum_ende: str | None, datum_pub: str | None) -> int | None:
    """Berechnet Laufzeit in Tagen (YYYYMMDD-Format)."""
    if not datum_ende or not datum_pub:
        return None
    try:
        ende  = pd.to_datetime(str(datum_ende), format="%Y%m%d", errors="coerce")
        start = pd.to_datetime(str(datum_pub),  format="%Y%m%d", errors="coerce")
        if pd.isna(ende) or pd.isna(start):
            return None
        delta = int((ende - start).days)
        return delta if DAUER_MIN_TAGE <= delta <= DAUER_MAX_TAGE else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Laden
# ---------------------------------------------------------------------------

def lade_rohdaten_bau(verzeichnis: Path = Path("data")) -> list[dict]:
    """
    Lädt alle raw_notices_bau_*.jsonl Dateien aus dem Verzeichnis.
    """
    muster = list(sorted(verzeichnis.glob("raw_notices_bau_*.jsonl")))
    if not muster:
        raise FileNotFoundError(
            f"Keine Bau-Rohdaten in {verzeichnis}. "
            "Bitte zuerst: python -m estimateiq.data.fetch_ted_bau"
        )

    datensaetze: list[dict] = []
    fehler = 0

    for pfad in muster:
        datei_count = 0
        with pfad.open(encoding="utf-8") as f:
            for i, zeile in enumerate(f, 1):
                zeile = zeile.strip()
                if not zeile:
                    continue
                try:
                    datensaetze.append(json.loads(zeile))
                    datei_count += 1
                except json.JSONDecodeError:
                    fehler += 1
                    logger.warning("%s Zeile %d: JSON-Fehler.", pfad.name, i)
        logger.info("[Laden] %s: %d Datensätze", pfad.name, datei_count)

    logger.info("[Laden] Gesamt: %d Datensätze (%d fehlerhafte Zeilen)", len(datensaetze), fehler)
    return datensaetze


# ---------------------------------------------------------------------------
# Konvertierung
# ---------------------------------------------------------------------------

def _extrahiere_titel_text(titel: str) -> str:
    """
    Bereinigt TED-Titel im Format "Land-Stadt: Beschreibung" → "Beschreibung".
    Entfernt den geographischen Prefix wie "Deutschland-München: ".
    """
    if not titel:
        return ""
    # Format: "Deutschland-München: Bauarbeiten" → "Bauarbeiten"
    if ": " in titel:
        return titel.split(": ", 1)[1].strip()
    return titel.strip()


def _konvertiere_zu_dataframe(datensaetze: list[dict]) -> pd.DataFrame:
    """
    Wandelt rohe TedBauNotice-Dicts in einen bereinigten DataFrame um.

    CPV ist OPTIONAL – da alle Notices via PC=45* abgefragt wurden,
    sind sie per Definition Bauprojekte. Fehlende CPVs bekommen den
    Defaultwert "45000000" (Bauarbeiten allgemein).

    Für alte Notices (pre-2023, altes TED-Format): Titel als Fallback-Beschreibung.
    """
    zeilen: list[dict] = []
    gesehen_ids: set[str] = set()

    zaehler = {
        "duplikat":     0,
        "text_zu_kurz": 0,
        "kein_cpv":     0,  # nur für Statistik, kein Filterkriterium
        "akzeptiert":   0,
        "synthetisch":  0,  # Zähler für synthetische Datensätze
    }

    for rec in datensaetze:
        doc_id = str(rec.get("document_id") or "")
        if doc_id and doc_id in gesehen_ids:
            zaehler["duplikat"] += 1
            continue
        if doc_id:
            gesehen_ids.add(doc_id)

        # CPV: optional (alle sind Bau durch PC=45* Filter)
        cpv = _parse_cpv_bau(rec.get("cpv_code"))
        if cpv is None:
            zaehler["kein_cpv"] += 1
            cpv = "45000000"  # Default: Bauarbeiten allgemein

        # Text: description (eForms) oder Titel-Suffix (altes Format)
        beschreibung_roh = _bereinige_text(rec.get("description"))
        titel_roh        = _bereinige_text(rec.get("title"))
        titel_kurz       = _extrahiere_titel_text(titel_roh)

        # Bevorzuge ausführliche Beschreibung, Fallback: Titel
        if beschreibung_roh:
            kombi = f"{titel_kurz} {beschreibung_roh}".strip()
        else:
            kombi = titel_kurz

        ist_synthetisch = rec.get("datenquelle") == "synthetic_small"
        if len(kombi) < BESCHREIBUNG_MIN_ZEICHEN and not ist_synthetisch:
            zaehler["text_zu_kurz"] += 1
            continue

        # Dauer: aus direktem Feld oder Datumsberechnung
        dauer = rec.get("duration_days") or _berechne_dauer(
            rec.get("duration_end"), rec.get("publication_date")
        )

        pub_date_str = str(rec.get("publication_date") or "")
        try:
            jahr = int(pub_date_str[:4]) if pub_date_str and pub_date_str[:4].isdigit() else None
            if jahr and not (2000 <= jahr <= 2030):
                jahr = None
        except (ValueError, TypeError):
            jahr = None

        land = (rec.get("country") or "").upper().strip() or None

        datenquelle = rec.get("datenquelle", "ted_bau")
        zeilen.append({
            "beschreibung":      kombi,
            "budget_eur":        _budget_zu_eur(rec.get("estimated_value"), rec.get("currency")),
            "dauer_tage":        dauer,
            "cpv_code":          cpv,
            "gewerk":            _cpv_zu_gewerk(cpv),
            "projekttyp":        _cpv_zu_projekttyp(cpv),
            "land":              land,
            "auftraggeber_ort":  rec.get("auftraggeber_ort"),
            "auftraggeber_plz":  rec.get("auftraggeber_plz"),
            "datenquelle":       datenquelle,
            "jahr":              jahr,
        })
        zaehler["akzeptiert"] += 1
        if datenquelle == "synthetic_small":
            zaehler["synthetisch"] += 1

    logger.info(
        "[Konvertierung] Eingabe: %d | Duplikat: %d | Text zu kurz: %d | Kein CPV (→Default): %d | Akzeptiert: %d (davon synthetisch: %d)",
        len(datensaetze), zaehler["duplikat"],
        zaehler["text_zu_kurz"], zaehler["kein_cpv"], zaehler["akzeptiert"], zaehler["synthetisch"],
    )

    return pd.DataFrame(zeilen)


# ---------------------------------------------------------------------------
# Ausreißer
# ---------------------------------------------------------------------------

def _bereinige_budget(df: pd.DataFrame) -> pd.DataFrame:
    vorher = df["budget_eur"].isna().sum()
    maske  = df["budget_eur"].notna() & (
        (df["budget_eur"] < BUDGET_MIN_EUR) | (df["budget_eur"] > BUDGET_MAX_EUR)
    )
    df.loc[maske, "budget_eur"] = pd.NA
    neue = df["budget_eur"].isna().sum() - vorher
    logger.info("[Budget] %d Ausreißer entfernt (< %s € oder > %s €).",
                neue, f"{BUDGET_MIN_EUR:,}", f"{BUDGET_MAX_EUR:,}")
    return df


def _bereinige_dauer(df: pd.DataFrame) -> pd.DataFrame:
    vorher = df["dauer_tage"].isna().sum()
    maske  = df["dauer_tage"].notna() & (
        (df["dauer_tage"] < DAUER_MIN_TAGE) | (df["dauer_tage"] > DAUER_MAX_TAGE)
    )
    df.loc[maske, "dauer_tage"] = pd.NA
    neue = df["dauer_tage"].isna().sum() - vorher
    logger.info("[Dauer] %d Ausreißer entfernt (< %d oder > %d Tage).",
                neue, DAUER_MIN_TAGE, DAUER_MAX_TAGE)
    return df


# ---------------------------------------------------------------------------
# Geocoding + BBSR-Index
# ---------------------------------------------------------------------------

def _anreichern_mit_geo(df: pd.DataFrame, mit_geocoding: bool = True) -> pd.DataFrame:
    """Fügt Geo-Features aus geo_features.py hinzu."""
    if not mit_geocoding:
        for col in ["latitude", "longitude", "bundesland", "landkreis",
                    "ist_metropole", "ist_grossstadt"]:
            df[col] = None
        return df

    from estimateiq.data.geo_features import enrich_with_geo
    return enrich_with_geo(df)


def _anreichern_mit_bbsr(df: pd.DataFrame) -> pd.DataFrame:
    """Fügt BBSR-Baupreisindex pro Zeile hinzu."""
    from estimateiq.data.fetch_bbsr import get_bbsr_index

    def _get_index(row) -> float:
        bl   = row.get("bundesland") or row.get("land")
        # NaN-Schutz: pandas liefert float NaN für fehlende Geo-Werte
        if bl is None or (isinstance(bl, float) and pd.isna(bl)):
            bl = None
        jahr = row.get("jahr")
        if jahr is not None and (isinstance(jahr, float) and pd.isna(jahr)):
            jahr = None
        return get_bbsr_index(bl, jahr)

    df["bbsr_index"] = df.apply(_get_index, axis=1)
    logger.info("[BBSR] Index-Spalte hinzugefügt. Mittelwert: %.1f", df["bbsr_index"].mean())
    return df


# ---------------------------------------------------------------------------
# Speichern
# ---------------------------------------------------------------------------

def speichere_ergebnisse(df: pd.DataFrame, verzeichnis: Path = Path("data/processed")) -> dict[str, Path]:
    verzeichnis.mkdir(parents=True, exist_ok=True)

    pfad_parquet = verzeichnis / "notices_bau.parquet"
    pfad_csv     = verzeichnis / "notices_bau.csv"

    # Spalten für Parquet final typisieren
    df_speichern = df.copy()

    # Geo-Spalten: sicherstellen dass sie numerisch sind
    for col in ["latitude", "longitude", "bbsr_index"]:
        if col in df_speichern.columns:
            df_speichern[col] = pd.to_numeric(df_speichern[col], errors="coerce")

    for col in ["ist_metropole", "ist_grossstadt"]:
        if col in df_speichern.columns:
            df_speichern[col] = df_speichern[col].fillna(False).astype(bool)

    df_speichern["budget_eur"]  = pd.to_numeric(df_speichern["budget_eur"], errors="coerce")
    df_speichern["dauer_tage"]  = pd.to_numeric(df_speichern["dauer_tage"], errors="coerce").astype("Int64")
    df_speichern["jahr"]        = pd.to_numeric(df_speichern["jahr"], errors="coerce").astype("Int64")

    df_speichern.to_parquet(pfad_parquet, index=False)
    df_speichern.to_csv(pfad_csv, index=False, encoding="utf-8")

    logger.info("[Speichern] %s (%.0f KB) | %s (%.0f KB)",
                pfad_parquet, pfad_parquet.stat().st_size / 1024,
                pfad_csv,     pfad_csv.stat().st_size / 1024)
    return {"parquet": pfad_parquet, "csv": pfad_csv}


# ---------------------------------------------------------------------------
# Statistik
# ---------------------------------------------------------------------------

def zeige_statistik(df: pd.DataFrame) -> None:
    """Kompakte Übersicht über den Bau-Datensatz."""
    n      = len(df)
    n_bud  = df["budget_eur"].notna().sum()
    n_dau  = df["dauer_tage"].notna().sum()
    n_geo  = df["latitude"].notna().sum() if "latitude" in df.columns else 0

    trenner = "─" * 54

    print(f"\n{trenner}")
    print("  EstimateIQ Bau – Datensatz-Statistik")
    print(trenner)

    print(f"\n  Projekte gesamt:        {n:>8,}")
    print(f"  Mit Budget (EUR):       {n_bud:>8,}  ({100*n_bud/n:.0f}%)" if n else "")
    print(f"  Mit Laufzeit (Tage):    {n_dau:>8,}  ({100*n_dau/n:.0f}%)" if n else "")
    print(f"  Mit Geo-Daten:          {n_geo:>8,}  ({100*n_geo/n:.0f}%)" if n else "")

    budget = df["budget_eur"].dropna()
    if not budget.empty:
        print(f"\n  Budget-Verteilung (EUR):")
        print(f"    Minimum:   {budget.min():>15,.0f} €")
        print(f"    5. Pztl:   {budget.quantile(0.05):>15,.0f} €")
        print(f"    Median:    {budget.median():>15,.0f} €")
        print(f"    Mittel:    {budget.mean():>15,.0f} €")
        print(f"    95. Pztl:  {budget.quantile(0.95):>15,.0f} €")
        print(f"    Maximum:   {budget.max():>15,.0f} €")

    dauer = df["dauer_tage"].dropna()
    if not dauer.empty:
        print(f"\n  Laufzeit-Verteilung (Tage):")
        print(f"    Median:    {int(dauer.median()):>8,}")
        print(f"    Mittel:    {int(dauer.mean()):>8,}")
        print(f"    Maximum:   {int(dauer.max()):>8,}")

    if "gewerk" in df.columns:
        print(f"\n  Top Gewerke:")
        for gew, n_gew in df["gewerk"].value_counts().head(10).items():
            balken = "█" * int(30 * n_gew / n)
            print(f"    {str(gew):<30} {n_gew:>6,}  {balken}")

    if "bundesland" in df.columns:
        bl_counts = df["bundesland"].value_counts()
        if not bl_counts.empty:
            print(f"\n  Top Bundesländer:")
            for bl, n_bl in bl_counts.head(8).items():
                print(f"    {str(bl):<30} {n_bl:>6,}")

    if "bbsr_index" in df.columns:
        idx = df["bbsr_index"].dropna()
        if not idx.empty:
            print(f"\n  BBSR-Index: Mittel={idx.mean():.1f}, Min={idx.min():.1f}, Max={idx.max():.1f}")

    print(f"\n{trenner}\n")


# ---------------------------------------------------------------------------
# Haupt-Pipeline
# ---------------------------------------------------------------------------

def preprocess_bau_pipeline(
    eingabe_dir:         Path | str = Path("data"),
    ausgabe_verzeichnis: Path | str = Path("data/processed"),
    mit_geocoding:       bool = True,
) -> pd.DataFrame:
    """
    Vollständige Bau-Preprocessing-Pipeline.

    Args:
        eingabe_dir:         Verzeichnis mit raw_notices_bau_*.jsonl
        ausgabe_verzeichnis: Zielordner für notices_bau.parquet/.csv
        mit_geocoding:       False = Geocoding überspringen (für Tests)
    """
    logger.info("=== EstimateIQ Bau Preprocessing gestartet ===")

    datensaetze = lade_rohdaten_bau(Path(eingabe_dir))

    df = _konvertiere_zu_dataframe(datensaetze)
    if df.empty:
        logger.warning("Keine gültigen Datensätze nach Konvertierung.")
        return df

    df = _bereinige_budget(df)
    df = _bereinige_dauer(df)

    df = _anreichern_mit_geo(df, mit_geocoding=mit_geocoding)
    df = _anreichern_mit_bbsr(df)

    speichere_ergebnisse(df, Path(ausgabe_verzeichnis))

    logger.info("=== Preprocessing abgeschlossen: %d Zeilen ===", len(df))
    return df


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

    parser = argparse.ArgumentParser(description="Bau-Daten vorverarbeiten")
    parser.add_argument(
        "--kein-geocoding", action="store_true",
        help="Geocoding überspringen (schneller, für erste Datensichtung)",
    )
    args = parser.parse_args()

    df = preprocess_bau_pipeline(mit_geocoding=not args.kein_geocoding)

    if not df.empty:
        zeige_statistik(df)
