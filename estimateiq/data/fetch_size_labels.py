"""
Sammelt und labelt Trainingsdaten für den Grössenklassifikator.

Quellen:
  1. data/raw_github_projects.jsonl  – Label nach dauer_tage
  2. data/processed/notices.parquet  – Label nach budget_eur (TED-Daten)
  3. data/manual_size_labels.json    – Manuelle Beispiele

Regeln:
  GitHub: dauer_tage < 90  → klein  |  90–365 → mittel  |  > 365 → gross
  TED:    budget_eur < 50k → klein  |  50k–300k → mittel  |  > 300k → gross
  Manuell: groesse direkt übernehmen

Output: data/size_labels.jsonl (Felder: beschreibung, groesse, quelle, dauer_tage, budget_eur)

Verwendung:
  python -m estimateiq.data.fetch_size_labels
"""

import json
import logging
import sys
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Pfade relativ zum Projektverzeichnis
GITHUB_JSONL    = Path("data/raw_github_projects.jsonl")
TED_PARQUET     = Path("data/processed/notices.parquet")
MANUELL_JSON    = Path("data/manual_size_labels.json")
SYNTHETIC_CSV   = Path("data/estimateiq_trainingsdaten_2000.csv")
OUTPUT_JSONL    = Path("data/size_labels.jsonl")

# Schwellenwerte für GitHub-Labels (Tage)
GITHUB_KLEIN_MAX  = 90
GITHUB_MITTEL_MAX = 365

# Schwellenwerte für TED-Labels (EUR)
TED_KLEIN_MAX  = 50_000
TED_MITTEL_MAX = 300_000

GUELTIGE_GROESSEN = {"klein", "mittel", "gross"}
MIN_BESCHREIBUNG_LAENGE = 10


def _label_github(dauer_tage: float) -> str:
    """Vergab Grössenklasse basierend auf Projektlaufzeit in Tagen."""
    if dauer_tage < GITHUB_KLEIN_MAX:
        return "klein"
    elif dauer_tage <= GITHUB_MITTEL_MAX:
        return "mittel"
    return "gross"


def _label_ted(budget_eur: float) -> str:
    """Vergab Grössenklasse basierend auf Budget in EUR."""
    if budget_eur < TED_KLEIN_MAX:
        return "klein"
    elif budget_eur <= TED_MITTEL_MAX:
        return "mittel"
    return "gross"


def _lade_github_labels() -> list[dict]:
    """Lädt GitHub-Projekte und labelt nach Laufzeit."""
    if not GITHUB_JSONL.exists():
        logger.warning("[SizeLabels] GitHub-Daten nicht gefunden: %s – übersprungen.", GITHUB_JSONL)
        return []

    eintraege: list[dict] = []
    uebersprungen = 0

    with GITHUB_JSONL.open("r", encoding="utf-8") as f:
        for zeile in f:
            zeile = zeile.strip()
            if not zeile:
                continue
            try:
                obj = json.loads(zeile)
            except json.JSONDecodeError:
                continue

            beschreibung = str(obj.get("beschreibung") or obj.get("description") or "").strip()
            if len(beschreibung) < MIN_BESCHREIBUNG_LAENGE:
                uebersprungen += 1
                continue

            dauer_roh = obj.get("dauer_tage")
            if dauer_roh is None:
                uebersprungen += 1
                continue

            try:
                dauer = float(dauer_roh)
            except (ValueError, TypeError):
                uebersprungen += 1
                continue

            if dauer <= 0:
                uebersprungen += 1
                continue

            groesse = _label_github(dauer)
            eintraege.append({
                "beschreibung": beschreibung,
                "groesse":      groesse,
                "quelle":       "github",
                "dauer_tage":   dauer,
                "budget_eur":   None,
            })

    logger.info(
        "[SizeLabels] GitHub: %d Einträge geladen, %d übersprungen.",
        len(eintraege), uebersprungen,
    )
    return eintraege


def _lade_ted_labels() -> list[dict]:
    """Lädt TED-Parquet und labelt nach Budget."""
    if not TED_PARQUET.exists():
        logger.warning("[SizeLabels] TED-Parquet nicht gefunden: %s – übersprungen.", TED_PARQUET)
        return []

    try:
        df = pd.read_parquet(TED_PARQUET)
    except Exception as exc:
        logger.warning("[SizeLabels] TED-Parquet konnte nicht gelesen werden: %s", exc)
        return []

    # Nach TED-Datenquelle filtern falls Spalte vorhanden
    if "datenquelle" in df.columns:
        df = df[df["datenquelle"] == "ted"].copy()

    # Nur Zeilen mit Budget
    if "budget_eur" not in df.columns:
        logger.warning("[SizeLabels] Spalte 'budget_eur' nicht in TED-Daten – übersprungen.")
        return []

    df = df[df["budget_eur"].notna()].copy()
    df["budget_eur"] = pd.to_numeric(df["budget_eur"], errors="coerce")
    df = df[df["budget_eur"] > 0].copy()

    if "beschreibung" not in df.columns:
        logger.warning("[SizeLabels] Spalte 'beschreibung' nicht in TED-Daten – übersprungen.")
        return []

    eintraege: list[dict] = []
    uebersprungen = 0

    for _, zeile in df.iterrows():
        beschreibung = str(zeile.get("beschreibung") or "").strip()
        if len(beschreibung) < MIN_BESCHREIBUNG_LAENGE:
            uebersprungen += 1
            continue

        budget = float(zeile["budget_eur"])
        groesse = _label_ted(budget)

        dauer_roh = zeile.get("dauer_tage")
        dauer = float(dauer_roh) if pd.notna(dauer_roh) else None

        eintraege.append({
            "beschreibung": beschreibung,
            "groesse":      groesse,
            "quelle":       "ted",
            "dauer_tage":   dauer,
            "budget_eur":   budget,
        })

    logger.info(
        "[SizeLabels] TED: %d Einträge geladen, %d übersprungen.",
        len(eintraege), uebersprungen,
    )
    return eintraege


def _lade_synthetic_labels() -> list[dict]:
    """Lädt synthetische DACH-Trainingsdaten mit echten Grössenklassen-Labels aus CSV."""
    if not SYNTHETIC_CSV.exists():
        logger.warning("[SizeLabels] Synthetische CSV nicht gefunden: %s – übersprungen.", SYNTHETIC_CSV)
        return []

    try:
        df = pd.read_csv(SYNTHETIC_CSV)
    except Exception as exc:
        logger.warning("[SizeLabels] CSV konnte nicht gelesen werden: %s", exc)
        return []

    eintraege: list[dict] = []
    uebersprungen = 0

    for _, zeile in df.iterrows():
        beschreibung = str(zeile.get("beschreibung") or "").strip()
        if len(beschreibung) < MIN_BESCHREIBUNG_LAENGE:
            uebersprungen += 1
            continue

        groesse = str(zeile.get("groesse") or "").strip().lower()
        if groesse not in GUELTIGE_GROESSEN:
            uebersprungen += 1
            continue

        dauer_roh = zeile.get("dauer_tage")
        try:
            dauer = float(dauer_roh) if pd.notna(dauer_roh) else None
        except (ValueError, TypeError):
            dauer = None

        budget_roh = zeile.get("budget_eur")
        try:
            budget = float(budget_roh) if pd.notna(budget_roh) else None
        except (ValueError, TypeError):
            budget = None

        eintraege.append({
            "beschreibung": beschreibung,
            "groesse":      groesse,
            "quelle":       "synthetic_estimateiq",
            "dauer_tage":   dauer,
            "budget_eur":   budget,
        })

    logger.info(
        "[SizeLabels] Synthetisch: %d Einträge geladen, %d übersprungen.",
        len(eintraege), uebersprungen,
    )
    return eintraege


def _lade_manuelle_labels() -> list[dict]:
    """Lädt manuelle Beispiele aus JSON-Datei."""
    if not MANUELL_JSON.exists():
        logger.warning("[SizeLabels] Manuelle Labels nicht gefunden: %s – übersprungen.", MANUELL_JSON)
        return []

    try:
        with MANUELL_JSON.open("r", encoding="utf-8") as f:
            daten = json.load(f)
    except Exception as exc:
        logger.warning("[SizeLabels] Manuelle Labels konnten nicht gelesen werden: %s", exc)
        return []

    eintraege: list[dict] = []
    uebersprungen = 0

    for eintrag in daten:
        beschreibung = str(eintrag.get("beschreibung") or "").strip()
        if len(beschreibung) < MIN_BESCHREIBUNG_LAENGE:
            uebersprungen += 1
            continue

        groesse = str(eintrag.get("groesse") or "").strip().lower()
        if groesse not in GUELTIGE_GROESSEN:
            logger.debug("[SizeLabels] Unbekannte Größe '%s' – übersprungen.", groesse)
            uebersprungen += 1
            continue

        eintraege.append({
            "beschreibung": beschreibung,
            "groesse":      groesse,
            "quelle":       "manuell",
            "dauer_tage":   None,
            "budget_eur":   None,
        })

    logger.info(
        "[SizeLabels] Manuell: %d Einträge geladen, %d übersprungen.",
        len(eintraege), uebersprungen,
    )
    return eintraege


def _dedupliziere(eintraege: list[dict]) -> list[dict]:
    """Dedupliziert nach den ersten 80 Zeichen der Beschreibung (Groß-/Kleinschreibung ignoriert)."""
    gesehen: set[str] = set()
    ergebnis: list[dict] = []
    for eintrag in eintraege:
        schluessel = eintrag["beschreibung"][:80].lower()
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        ergebnis.append(eintrag)
    return ergebnis


def erstelle_labels() -> list[dict]:
    """
    Sammelt Labels aus allen Quellen, dedupliziert und gibt eine Liste zurück.
    Schreibt dabei auch nach OUTPUT_JSONL.

    Priorität (Dedup bevorzugt frühere Einträge):
      1. synthetic_estimateiq – echte Labels (höchste Qualität)
      2. github               – Laufzeit-basierte Labels
      3. manuell              – manuell annotiert
      4. ted                  – Budget-Proxy (niedrigste Qualität)
    """
    alle: list[dict] = []
    alle.extend(_lade_synthetic_labels())  # Zuerst – höchste Priorität bei Dedup
    alle.extend(_lade_github_labels())
    alle.extend(_lade_manuelle_labels())
    alle.extend(_lade_ted_labels())

    # Deduplizierung
    vor_dedup = len(alle)
    alle = _dedupliziere(alle)
    nach_dedup = len(alle)
    if vor_dedup != nach_dedup:
        logger.info("[SizeLabels] Deduplizierung: %d → %d Einträge (%d Duplikate entfernt).",
                    vor_dedup, nach_dedup, vor_dedup - nach_dedup)

    # Statistiken ausgeben
    stats_quelle: dict[str, int] = {}
    stats_groesse: dict[str, int] = {}
    for e in alle:
        stats_quelle[e["quelle"]] = stats_quelle.get(e["quelle"], 0) + 1
        stats_groesse[e["groesse"]] = stats_groesse.get(e["groesse"], 0) + 1

    print(f"\n[SizeLabels] Gesamte Labels: {len(alle)}")
    print("  Nach Quelle:")
    for q, n in sorted(stats_quelle.items()):
        print(f"    {q:<12}: {n:>5}")
    print("  Nach Größe:")
    for g in ["klein", "mittel", "gross"]:
        n = stats_groesse.get(g, 0)
        print(f"    {g:<12}: {n:>5}")

    # Ausgabe schreiben
    OUTPUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_JSONL.open("w", encoding="utf-8") as f:
        for eintrag in alle:
            f.write(json.dumps(eintrag, ensure_ascii=False) + "\n")

    logger.info("[SizeLabels] Geschrieben: %s (%d Einträge)", OUTPUT_JSONL, len(alle))
    return alle


def lade_size_labels() -> pd.DataFrame:
    """
    Lädt size_labels.jsonl als pandas DataFrame.
    Falls die Datei nicht existiert, werden die Labels zuerst erstellt.

    Returns:
        DataFrame mit Spalten: beschreibung, groesse, quelle, dauer_tage, budget_eur
    """
    if not OUTPUT_JSONL.exists():
        logger.info("[SizeLabels] %s nicht gefunden – erstelle Labels...", OUTPUT_JSONL)
        erstelle_labels()

    eintraege: list[dict] = []
    with OUTPUT_JSONL.open("r", encoding="utf-8") as f:
        for zeile in f:
            zeile = zeile.strip()
            if not zeile:
                continue
            try:
                eintraege.append(json.loads(zeile))
            except json.JSONDecodeError:
                continue

    df = pd.DataFrame(eintraege)
    if df.empty:
        logger.warning("[SizeLabels] Keine Einträge in %s gefunden.", OUTPUT_JSONL)
        return pd.DataFrame(columns=["beschreibung", "groesse", "quelle", "dauer_tage", "budget_eur"])

    # Typen sicherstellen
    df["beschreibung"] = df["beschreibung"].astype(str)
    df["groesse"]      = df["groesse"].astype(str)
    df["quelle"]       = df["quelle"].astype(str)
    df["dauer_tage"]   = pd.to_numeric(df.get("dauer_tage", pd.Series(dtype=float)), errors="coerce")
    df["budget_eur"]   = pd.to_numeric(df.get("budget_eur",  pd.Series(dtype=float)), errors="coerce")

    logger.info("[SizeLabels] %d Labels geladen.", len(df))
    return df


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )
    erstelle_labels()
