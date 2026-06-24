"""
Datenvorverarbeitung für EstimateIQ.

Pipeline:
  1. Rohdaten aus fetch_ted.py laden (JSON Lines)
  2. Texte bereinigen (HTML, Whitespace)
  3. CPV-Code parsen & Projekttyp ableiten
  4. Budget zu EUR normalisieren
  5. Laufzeit in Tagen berechnen
  6. Ausreißer & fehlende Pflichtfelder behandeln
  7. Als CSV + Parquet unter data/processed/ speichern
  8. Statistik ausgeben
"""

import json
import logging
import re
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

BUDGET_MIN_EUR = 5_000        # Ausreißer-Untergrenze
BUDGET_MAX_EUR = 500_000_000  # Ausreißer-Obergrenze
DAUER_MIN_TAGE = 3            # Kürzeste sinnvolle Laufzeit (kleine Projekte: ab 3 Tagen)
DAUER_MAX_TAGE = 3_650        # Längste sinnvolle Laufzeit (10 Jahre)
TITEL_MIN_ZEICHEN = 10
BESCHREIBUNG_MIN_ZEICHEN = 30

# Jahresdurchschnittskurse 2024 (näherungsweise), alle → EUR
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
    "HUF": 0.0026,
    "RON": 0.201,
    "BGN": 0.511,
    "HRK": 0.133,
    "TRY": 0.029,
    "RSD": 0.0085,
}

# CPV-Bereich → Projekttyp-Label
# Reihenfolge: spezifischste Ranges zuerst
CPV_PROJEKTTYPEN: list[tuple[range, str]] = [
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


# ---------------------------------------------------------------------------
# Schritt 1 – Laden
# ---------------------------------------------------------------------------

def lade_rohdaten(pfad: str | Path | None = None) -> list[dict]:
    """
    Lädt JSON-Lines-Dateien.

    - pfad=None oder pfad="data/": liest alle data/raw_notices_*.jsonl
      (Mehrjahresdaten), mit Fallback auf data/raw_notices.jsonl
    - pfad=spezifische Datei: liest nur diese eine Datei
    """
    from glob import glob

    pfade: list[Path] = []

    if pfad is None or Path(str(pfad)).is_dir():
        verzeichnis = Path(pfad) if pfad else Path("data")
        # TED-Daten: raw_notices_*.jsonl (CN + CAN)
        jahresdateien = sorted(verzeichnis.glob("raw_notices_*.jsonl"))
        if jahresdateien:
            pfade = jahresdateien
            cn_dateien  = [p for p in pfade if "awards" not in p.name]
            can_dateien = [p for p in pfade if "awards" in p.name]
            logger.info(
                "[Laden] %d CN-Dateien + %d CAN-Dateien: %s",
                len(cn_dateien), len(can_dateien),
                ", ".join(p.name for p in pfade),
            )
        else:
            # Rückfall auf alte Einzeldatei
            alt = verzeichnis / "raw_notices.jsonl"
            if alt.exists():
                pfade = [alt]
                logger.info("[Laden] Verwende Legacy-Datei: %s", alt)
            else:
                raise FileNotFoundError(
                    f"Keine Rohdaten in {verzeichnis}. "
                    "Bitte zuerst: python -m estimateiq.data.fetch_ted"
                )

        # Zusatzquellen: PROMISE, GitHub, COSMIC, IndieHackers, ISBSG (automatisch geladen wenn vorhanden)
        # raw_user_csv.jsonl ist veraltet – wird durch estimateiq_trainingsdaten_2000.csv ersetzt
        for zusatz_name in ["raw_promise.jsonl", "raw_github_projects.jsonl", "raw_cosmic.jsonl", "raw_indiehackers.jsonl", "raw_isbsg.jsonl"]:
            zusatz_pfad = verzeichnis / zusatz_name
            if zusatz_pfad.exists():
                pfade.append(zusatz_pfad)
                logger.info("[Laden] Zusatzquelle erkannt: %s", zusatz_pfad.name)
    else:
        pfad = Path(pfad)
        if not pfad.exists():
            raise FileNotFoundError(f"Rohdaten nicht gefunden: {pfad}")
        pfade = [pfad]

    datensaetze: list[dict] = []
    fehlerhafte_zeilen = 0

    for quelldatei in pfade:
        datei_count = 0
        with quelldatei.open(encoding="utf-8") as f:
            for i, zeile in enumerate(f, start=1):
                zeile = zeile.strip()
                if not zeile:
                    continue
                try:
                    datensaetze.append(json.loads(zeile))
                    datei_count += 1
                except json.JSONDecodeError:
                    fehlerhafte_zeilen += 1
                    logger.warning("%s Zeile %d: ungültiges JSON, übersprungen.",
                                   quelldatei.name, i)
        logger.info("[Laden] %s: %d Datensätze", quelldatei.name, datei_count)

    # Synthetische Trainingsdaten (CSV mit echten Grössenklassen-Labels)
    if pfad is None or Path(str(pfad)).is_dir():
        verz = Path(pfad) if pfad else Path("data")
        csv_pfad = verz / "estimateiq_trainingsdaten_2000.csv"
        if csv_pfad.exists():
            csv_datensaetze = _lade_csv_trainingsdaten(csv_pfad)
            datensaetze.extend(csv_datensaetze)
            logger.info("[Laden] Synthetische CSV: %d Datensätze", len(csv_datensaetze))

    logger.info(
        "[Laden] Gesamt: %d Datensätze aus %d Datei(en), %d fehlerhafte Zeilen.",
        len(datensaetze), len(pfade), fehlerhafte_zeilen,
    )
    return datensaetze


def _lade_csv_trainingsdaten(pfad: Path) -> list[dict]:
    """
    Lädt synthetische DACH-IT-Trainingsdaten aus CSV.
    Erhält das Grössenklassen-Label (groesse_label) für den Grössenklassifikator.
    """
    try:
        df = pd.read_csv(pfad)
    except Exception as exc:
        logger.warning("[Laden] CSV '%s' konnte nicht gelesen werden: %s", pfad, exc)
        return []

    gueltige_groessen = {"klein", "mittel", "gross"}
    ergebnisse: list[dict] = []

    for i, zeile in df.iterrows():
        beschreibung = str(zeile.get("beschreibung") or "").strip()
        if not beschreibung:
            continue

        budget_raw = zeile.get("budget_eur")
        dauer_raw  = zeile.get("dauer_tage")
        jahr_raw   = zeile.get("jahr")
        land_raw   = str(zeile.get("land") or "DE").upper().strip()[:2]
        region_raw = str(zeile.get("region") or land_raw)
        tech_raw   = str(zeile.get("technologie") or "").strip() or None
        team_raw   = zeile.get("teamgroesse")
        groesse    = str(zeile.get("groesse") or "").strip().lower()

        try:
            budget = float(budget_raw) if pd.notna(budget_raw) else None
        except (ValueError, TypeError):
            budget = None
        try:
            dauer = int(float(dauer_raw)) if pd.notna(dauer_raw) else None
        except (ValueError, TypeError):
            dauer = None
        try:
            jahr = int(float(jahr_raw)) if pd.notna(jahr_raw) else None
        except (ValueError, TypeError):
            jahr = None
        try:
            team = int(float(team_raw)) if pd.notna(team_raw) else None
        except (ValueError, TypeError):
            team = None

        ergebnisse.append({
            "document_id":       f"synthetic_{i}",
            "publication_date":  f"{jahr}0101" if jahr else "20230101",
            "title":             beschreibung[:80],
            "description":       beschreibung,
            "cpv_code":          "72200000",
            "estimated_value":   budget,
            "currency":          "EUR",
            "country":           land_raw,
            "duration_end":      None,
            "dauer_tage_direkt": dauer,
            "notice_type":       "synthetic",
            "datenquelle":       "synthetic_estimateiq",
            "technologie":       tech_raw,
            "teamgroesse":       team,
            "groesse_label":     groesse if groesse in gueltige_groessen else None,
            "raw":               {},
        })

    return ergebnisse


# ---------------------------------------------------------------------------
# Schritt 2 – Hilfsfunktionen für Einzelfelder
# ---------------------------------------------------------------------------

def _bereinige_text(text: str | None) -> str:
    """Entfernt HTML-Tags, dekodiert Entitäten, normalisiert Whitespace."""
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


def _parse_cpv(cpv_roh: str | None) -> str | None:
    """
    Extrahiert den 8-stelligen CPV-Code als nullgefüllten String.
    Akzeptiert: '72263000', '72263000-9', 'CPV 72263000', 72263000 (int).
    """
    if cpv_roh is None:
        return None
    treffer = re.search(r"\b(\d{8})\b", str(cpv_roh))
    if not treffer:
        return None
    code = int(treffer.group(1))
    # Nur IT-Bereich durchlassen
    if not (72_000_000 <= code <= 72_999_999):
        return None
    return f"{code:08d}"


def _cpv_zu_projekttyp(cpv_str: str | None) -> str:
    """Leitet den Projekttyp anhand des CPV-Codes ab."""
    if not cpv_str:
        return "Sonstige IT"
    try:
        code = int(cpv_str)
    except ValueError:
        return "Sonstige IT"
    for bereich, label in CPV_PROJEKTTYPEN:
        if code in bereich:
            return label
    return "Sonstige IT"


def _budget_zu_eur(wert: float | None, waehrung: str | None) -> float | None:
    """Konvertiert einen Betrag zur Zielwährung EUR. None bei unbekannter Währung."""
    if wert is None or wert <= 0:
        return None
    kuerzel = (waehrung or "EUR").strip().upper()
    faktor = FX_ZU_EUR.get(kuerzel)
    if faktor is None:
        logger.debug("Unbekannte Währung '%s' ignoriert.", kuerzel)
        return None
    return round(wert * faktor, 2)


def _berechne_dauer(datum_ende: str | None, datum_pub: str | None) -> int | None:
    """
    Berechnet Laufzeit in Tagen (Ende − Publikation).
    Eingabeformat: YYYYMMDD (TED-Standard). Gibt None bei ungültigen Werten zurück.
    """
    if not datum_ende or not datum_pub:
        return None
    try:
        ende = pd.to_datetime(str(datum_ende), format="%Y%m%d", errors="coerce")
        start = pd.to_datetime(str(datum_pub), format="%Y%m%d", errors="coerce")
        if pd.isna(ende) or pd.isna(start):
            return None
        delta = int((ende - start).days)
        return delta if DAUER_MIN_TAGE <= delta <= DAUER_MAX_TAGE else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Schritt 3 – Datensätze zu DataFrame konvertieren
# ---------------------------------------------------------------------------

def _konvertiere_zu_dataframe(datensaetze: list[dict]) -> pd.DataFrame:
    """
    Wandelt rohe TedNotice-Dicts in Zeilen um.
    Verwirft Datensätze mit fehlendem CPV, doppelter ID oder zu kurzem Text.
    Loggt jeden Verwerfungsgrund separat.
    """
    zeilen: list[dict] = []
    gesehen_ids: set[str] = set()

    zaehler = {
        "kein_cpv": 0,
        "duplikat": 0,
        "text_zu_kurz": 0,
        "akzeptiert": 0,
    }

    for rec in datensaetze:
        # CPV parsen – Zeilen ohne IT-CPV verwerfen
        cpv_code = _parse_cpv(rec.get("cpv_code"))
        if cpv_code is None:
            zaehler["kein_cpv"] += 1
            continue

        # Duplikate über document_id erkennen
        doc_id = str(rec.get("document_id") or "")
        if doc_id and doc_id in gesehen_ids:
            zaehler["duplikat"] += 1
            continue
        if doc_id:
            gesehen_ids.add(doc_id)

        # Texte bereinigen und Mindestlänge prüfen
        titel = _bereinige_text(rec.get("title"))
        beschreibung = _bereinige_text(rec.get("description"))
        if len(titel) < TITEL_MIN_ZEICHEN or len(beschreibung) < BESCHREIBUNG_MIN_ZEICHEN:
            zaehler["text_zu_kurz"] += 1
            continue

        # Laufzeit: direktes Feld (PROMISE/GitHub/IndieHackers) hat Vorrang vor Datumsberechnung
        dauer = rec.get("dauer_tage_direkt") or _berechne_dauer(
            rec.get("duration_end"), rec.get("publication_date")
        )

        # Jahr aus Publikationsdatum
        pub_date_str = str(rec.get("publication_date") or "")
        try:
            jahr = int(pub_date_str[:4]) if pub_date_str and pub_date_str[:4].isdigit() else None
            if jahr and not (2000 <= jahr <= 2030):
                jahr = None
        except (ValueError, TypeError):
            jahr = None

        # Technologie (GitHub-Sprache, COSMIC-Typ, IH-Tags)
        technologie = (rec.get("technologie") or "").strip() or None

        groesse_label = str(rec.get("groesse_label") or "").strip().lower() or None
        if groesse_label not in (None, "klein", "mittel", "gross"):
            groesse_label = None

        zeilen.append({
            "titel":         titel,
            "beschreibung":  beschreibung,
            "budget_eur":    _budget_zu_eur(rec.get("estimated_value"), rec.get("currency")),
            "dauer_tage":    dauer,
            "land":          (rec.get("country") or "").upper().strip() or None,
            "cpv_code":      cpv_code,
            "projekttyp":    _cpv_zu_projekttyp(cpv_code),
            "datenquelle":   rec.get("datenquelle", "ted"),
            "technologie":   technologie,
            "jahr":          jahr,
            "groesse_label": groesse_label,
        })
        zaehler["akzeptiert"] += 1

    logger.info(
        "[Konvertierung] Ergebnis:\n"
        "  %-22s %d\n"
        "  %-22s %d verworfen\n"
        "  %-22s %d entfernt\n"
        "  %-22s %d verworfen\n"
        "  %-22s %d",
        "Eingabe:", len(datensaetze),
        "Kein IT-CPV:", zaehler["kein_cpv"],
        "Duplikate:", zaehler["duplikat"],
        "Text zu kurz:", zaehler["text_zu_kurz"],
        "Akzeptiert:", zaehler["akzeptiert"],
    )

    return pd.DataFrame(zeilen)


# ---------------------------------------------------------------------------
# Schritt 4 – Ausreißer bereinigen
# ---------------------------------------------------------------------------

def _bereinige_budget(df: pd.DataFrame) -> pd.DataFrame:
    """
    Setzt Budget-Ausreißer auf NaN (Datensatz bleibt erhalten).
    Loggt Anzahl betroffener Zeilen.
    """
    vorher_nan = df["budget_eur"].isna().sum()
    maske_ausreisser = df["budget_eur"].notna() & (
        (df["budget_eur"] < BUDGET_MIN_EUR) | (df["budget_eur"] > BUDGET_MAX_EUR)
    )
    df.loc[maske_ausreisser, "budget_eur"] = pd.NA

    neue_nan = df["budget_eur"].isna().sum() - vorher_nan
    logger.info(
        "[Budget] %d Ausreißer auf NaN gesetzt (< %s € oder > %s €).",
        neue_nan,
        f"{BUDGET_MIN_EUR:,}",
        f"{BUDGET_MAX_EUR:,}",
    )
    return df


def _bereinige_dauer(df: pd.DataFrame) -> pd.DataFrame:
    """
    Setzt Laufzeit-Ausreißer auf NaN (Datensatz bleibt erhalten).
    Loggt Anzahl betroffener Zeilen.
    """
    vorher_nan = df["dauer_tage"].isna().sum()
    maske_ausreisser = df["dauer_tage"].notna() & (
        (df["dauer_tage"] < DAUER_MIN_TAGE) | (df["dauer_tage"] > DAUER_MAX_TAGE)
    )
    df.loc[maske_ausreisser, "dauer_tage"] = pd.NA

    neue_nan = df["dauer_tage"].isna().sum() - vorher_nan
    logger.info(
        "[Dauer] %d Ausreißer auf NaN gesetzt (< %d Tage oder > %d Tage).",
        neue_nan, DAUER_MIN_TAGE, DAUER_MAX_TAGE,
    )
    return df


# ---------------------------------------------------------------------------
# Schritt 5 – Datentypen finalisieren
# ---------------------------------------------------------------------------

def _finalisiere_typen(df: pd.DataFrame) -> pd.DataFrame:
    """Setzt finale pandas-Datentypen für Speichereffizienz."""
    df["budget_eur"]  = pd.to_numeric(df["budget_eur"], errors="coerce").astype("float64")
    df["dauer_tage"]  = pd.to_numeric(df["dauer_tage"], errors="coerce").astype("Int64")
    df["cpv_code"]    = df["cpv_code"].astype("string")
    df["land"]        = df["land"].astype("category")
    df["projekttyp"]  = df["projekttyp"].astype("category")
    df["datenquelle"] = df["datenquelle"].astype("category")
    df["technologie"] = df["technologie"].astype("string")
    df["jahr"]        = pd.to_numeric(df["jahr"], errors="coerce").astype("Int64")
    if "groesse_label" in df.columns:
        df["groesse_label"] = df["groesse_label"].astype("string")
    logger.info("[Typen] Datentypen finalisiert.")
    return df


# ---------------------------------------------------------------------------
# Schritt 6 – Speichern
# ---------------------------------------------------------------------------

def speichere_ergebnisse(df: pd.DataFrame, verzeichnis: str | Path = "data/processed") -> dict[str, Path]:
    """
    Speichert den DataFrame als Parquet und CSV.
    Gibt ein Dict mit den tatsächlichen Pfaden zurück.
    """
    verzeichnis = Path(verzeichnis)
    verzeichnis.mkdir(parents=True, exist_ok=True)

    pfad_parquet = verzeichnis / "notices.parquet"
    pfad_csv     = verzeichnis / "notices.csv"

    df.to_parquet(pfad_parquet, index=False)
    df.to_csv(pfad_csv, index=False, encoding="utf-8")

    logger.info(
        "[Speichern] Parquet: %s (%.0f KB) | CSV: %s (%.0f KB)",
        pfad_parquet, pfad_parquet.stat().st_size / 1024,
        pfad_csv,     pfad_csv.stat().st_size / 1024,
    )
    return {"parquet": pfad_parquet, "csv": pfad_csv}


# ---------------------------------------------------------------------------
# Schritt 7 – Statistik
# ---------------------------------------------------------------------------

def zeige_statistik(df: pd.DataFrame) -> None:
    """Gibt eine kompakte Übersicht über den bereinigten Datensatz aus."""
    n_gesamt       = len(df)
    n_mit_budget   = df["budget_eur"].notna().sum()
    n_mit_dauer    = df["dauer_tage"].notna().sum()
    n_ohne_budget  = n_gesamt - n_mit_budget

    budget = df["budget_eur"].dropna()
    dauer  = df["dauer_tage"].dropna()

    trenner = "─" * 50

    print(f"\n{trenner}")
    print("  EstimateIQ – Datensatz-Statistik")
    print(trenner)

    print(f"\n  Anzahl Projekte gesamt:   {n_gesamt:>8,}")
    print(f"  Davon mit Budget (EUR):   {n_mit_budget:>8,}  ({100*n_mit_budget/n_gesamt:.0f}%)")
    print(f"  Davon ohne Budget:        {n_ohne_budget:>8,}  ({100*n_ohne_budget/n_gesamt:.0f}%)")
    print(f"  Davon mit Laufzeit:       {n_mit_dauer:>8,}  ({100*n_mit_dauer/n_gesamt:.0f}%)")

    if not budget.empty:
        print(f"\n  Budget-Verteilung (EUR):")
        print(f"    Minimum:   {budget.min():>15,.0f} €")
        print(f"    Median:    {budget.median():>15,.0f} €")
        print(f"    Ø Mittel:  {budget.mean():>15,.0f} €")
        print(f"    90. Pztl:  {budget.quantile(0.90):>15,.0f} €")
        print(f"    Maximum:   {budget.max():>15,.0f} €")

    if not dauer.empty:
        print(f"\n  Laufzeit-Verteilung (Tage):")
        print(f"    Minimum:   {int(dauer.min()):>8,}")
        print(f"    Median:    {int(dauer.median()):>8,}")
        print(f"    Maximum:   {int(dauer.max()):>8,}")

    print(f"\n  Häufigste Projekttypen:")
    for typ, anzahl in df["projekttyp"].value_counts().head(8).items():
        balken = "█" * int(40 * anzahl / n_gesamt)
        print(f"    {typ:<35} {anzahl:>5,}  {balken}")

    print(f"\n  Top-Länder:")
    for land, anzahl in df["land"].value_counts().head(6).items():
        print(f"    {land:<6} {anzahl:>6,}")

    if "datenquelle" in df.columns:
        print(f"\n  Datenquellen:")
        for quelle, anzahl in df["datenquelle"].value_counts().items():
            mit_budget = df[df["datenquelle"] == quelle]["budget_eur"].notna().sum()
            print(f"    {str(quelle):<10} {anzahl:>6,} Projekte  ({mit_budget:,} mit Budget)")

    print(f"\n{trenner}\n")


# ---------------------------------------------------------------------------
# Haupt-Pipeline
# ---------------------------------------------------------------------------

def preprocess_pipeline(
    eingabe_pfad: str | Path | None = None,
    ausgabe_verzeichnis: str | Path = "data/processed",
) -> pd.DataFrame:
    """
    Vollständige Pipeline:
      Laden → Konvertieren → Ausreißer bereinigen → Typen setzen → Speichern → Statistik

    Args:
        eingabe_pfad:        Pfad zu Rohdaten; None = automatisch alle data/raw_notices_*.jsonl
        ausgabe_verzeichnis: Zielordner für notices.parquet und notices.csv
    """
    logger.info("=== EstimateIQ Preprocessing gestartet ===")

    # 1. Laden
    datensaetze = lade_rohdaten(eingabe_pfad)

    # 2. Konvertieren & Pflichtfelder prüfen
    df = _konvertiere_zu_dataframe(datensaetze)
    if df.empty:
        logger.warning("Kein gültiger Datensatz nach Konvertierung – Abbruch.")
        return df

    # 3. Ausreißer behandeln
    df = _bereinige_budget(df)
    df = _bereinige_dauer(df)

    # 4. Datentypen finalisieren
    df = _finalisiere_typen(df)

    # 5. Speichern
    speichere_ergebnisse(df, ausgabe_verzeichnis)

    logger.info("=== Preprocessing abgeschlossen: %d Zeilen, 10 Spalten ===", len(df))
    return df


# ---------------------------------------------------------------------------
# Direkt ausführbar: python -m estimateiq.data.preprocess
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    df = preprocess_pipeline()

    if not df.empty:
        zeige_statistik(df)
