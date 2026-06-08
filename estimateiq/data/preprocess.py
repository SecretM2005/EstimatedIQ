"""
Datenvorverarbeitung: Lädt rohe TED-Notices aus fetch_ted.py,
bereinigt sie und gibt einen sauberen DataFrame mit genau 6 Spalten zurück:

    titel, beschreibung, budget_eur, dauer_tage, land, cpv_code
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

# Budgetgrenzen: Ausreißer außerhalb dieses Bereichs werden auf NaN gesetzt
BUDGET_MIN_EUR = 5_000
BUDGET_MAX_EUR = 500_000_000

# Laufzeitgrenzen in Tagen (1 Woche bis 10 Jahre)
DAUER_MIN_TAGE = 7
DAUER_MAX_TAGE = 3_650

# Währungsumrechnungskurse zu EUR (Jahresdurchschnitt 2024, näherungsweise)
FX_ZU_EUR: dict[str, float] = {
    "EUR": 1.000,
    "CHF": 1.050,
    "DKK": 0.134,
    "SEK": 0.088,
    "NOK": 0.086,
    "PLN": 0.232,
    "CZK": 0.040,
    "HUF": 0.0026,
    "GBP": 1.170,
    "USD": 0.930,
    "RON": 0.201,
    "BGN": 0.511,
    "HRK": 0.133,
}

# Mindestlängen für Text-Felder (kürzere Einträge sind zu dünn für BERT)
TITEL_MIN_ZEICHEN = 10
BESCHREIBUNG_MIN_ZEICHEN = 30


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _bereinige_text(text: str | None) -> str:
    """Entfernt HTML-Tags, normalisiert Whitespace, trimmt."""
    if not text:
        return ""
    # HTML-Tags entfernen
    text = re.sub(r"<[^>]+>", " ", text)
    # HTML-Entitäten dekodieren (einfachste Fälle)
    text = (
        text
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&nbsp;", " ")
        .replace("&quot;", '"')
    )
    # Mehrfach-Whitespace auf ein Leerzeichen reduzieren
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_cpv(cpv_roh: str | None) -> int | None:
    """
    Extrahiert den 8-stelligen CPV-Code als Integer.
    Akzeptiert Formate wie '72263000', '72263000-9', 'CPV 72263000'.
    """
    if not cpv_roh:
        return None
    treffer = re.search(r"\b(\d{8})\b", str(cpv_roh))
    return int(treffer.group(1)) if treffer else None


def _budget_zu_eur(wert: float | None, waehrung: str | None) -> float | None:
    """
    Rechnet einen Betrag in die Zielwährung EUR um.
    Gibt None zurück wenn Währung unbekannt oder Wert fehlt.
    """
    if wert is None or wert <= 0:
        return None
    kuerzel = (waehrung or "EUR").strip().upper()
    faktor = FX_ZU_EUR.get(kuerzel)
    if faktor is None:
        logger.debug("Unbekannte Währung '%s' – Datensatz wird verworfen.", kuerzel)
        return None
    return round(wert * faktor, 2)


def _berechne_dauer(datum_ende: str | None, datum_pub: str | None) -> int | None:
    """
    Berechnet die Laufzeit in Tagen aus End- und Veröffentlichungsdatum.
    Eingabeformat: YYYYMMDD als String (TED-Standard).
    """
    if not datum_ende or not datum_pub:
        return None
    try:
        ende = pd.to_datetime(datum_ende, format="%Y%m%d", errors="coerce")
        start = pd.to_datetime(datum_pub, format="%Y%m%d", errors="coerce")
        if pd.isna(ende) or pd.isna(start):
            return None
        delta = (ende - start).days
        return int(delta) if DAUER_MIN_TAGE <= delta <= DAUER_MAX_TAGE else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Kernfunktionen
# ---------------------------------------------------------------------------

def lade_jsonl(pfad: str | Path) -> list[dict]:
    """Lädt eine JSON-Lines-Datei zeilenweise in eine Liste."""
    datensaetze: list[dict] = []
    with open(pfad, encoding="utf-8") as f:
        for zeile in f:
            zeile = zeile.strip()
            if zeile:
                datensaetze.append(json.loads(zeile))
    logger.info("Geladen: %d Rohdatensätze aus %s", len(datensaetze), pfad)
    return datensaetze


def erstelle_dataframe(datensaetze: list[dict]) -> pd.DataFrame:
    """
    Bereinigt rohe TED-Notice-Dicts und gibt einen strukturierten DataFrame zurück.

    Ausgabe-Spalten:
        titel          (str)   – bereinigter Ausschreibungstitel
        beschreibung   (str)   – bereinigter Volltext
        budget_eur     (float) – Auftragswert in EUR, NaN wenn nicht verfügbar
        dauer_tage     (int)   – Laufzeit in Tagen, NaN wenn nicht berechenbar
        land           (str)   – ISO-Ländercode (DE, AT, CH, ...)
        cpv_code       (int)   – 8-stelliger CPV-Code

    Qualitätsstufen (werden protokolliert):
        1. CPV außerhalb IT-Bereich → verworfen
        2. Duplikate (gleiche document_id) → dedupliziert
        3. Titel oder Beschreibung zu kurz → verworfen
        4. Budgets außerhalb [5k, 500M] EUR → auf NaN gesetzt (Zeile bleibt)
        5. Laufzeit außerhalb [7, 3650] Tage → auf NaN gesetzt (Zeile bleibt)
    """
    roh_anzahl = len(datensaetze)
    zeilen: list[dict] = []
    gesehen_ids: set[str] = set()

    kein_cpv = 0
    kein_it_cpv = 0
    duplikat = 0
    zu_kurzer_text = 0

    for rec in datensaetze:
        # --- CPV validieren ---
        cpv_code = _parse_cpv(rec.get("cpv_code"))
        if cpv_code is None:
            kein_cpv += 1
            continue
        if not (72_000_000 <= cpv_code <= 72_900_000):
            kein_it_cpv += 1
            continue

        # --- Duplikate entfernen ---
        doc_id = rec.get("document_id", "")
        if doc_id and doc_id in gesehen_ids:
            duplikat += 1
            continue
        if doc_id:
            gesehen_ids.add(doc_id)

        # --- Texte bereinigen ---
        titel = _bereinige_text(rec.get("title"))
        beschreibung = _bereinige_text(rec.get("description"))

        if len(titel) < TITEL_MIN_ZEICHEN or len(beschreibung) < BESCHREIBUNG_MIN_ZEICHEN:
            zu_kurzer_text += 1
            continue

        # --- Budget umrechnen (NaN wenn nicht verfügbar, Zeile bleibt) ---
        budget_eur = _budget_zu_eur(rec.get("estimated_value"), rec.get("currency"))
        if budget_eur is not None and not (BUDGET_MIN_EUR <= budget_eur <= BUDGET_MAX_EUR):
            budget_eur = None  # Extremwert → NaN, Datensatz behalten

        # --- Laufzeit berechnen (NaN wenn nicht berechenbar) ---
        dauer_tage = _berechne_dauer(
            rec.get("duration_end"),
            rec.get("publication_date"),
        )

        zeilen.append({
            "titel": titel,
            "beschreibung": beschreibung,
            "budget_eur": budget_eur,
            "dauer_tage": dauer_tage,
            "land": (rec.get("country") or "").upper().strip(),
            "cpv_code": cpv_code,
        })

    # --- DataFrame aufbauen ---
    df = pd.DataFrame(zeilen)

    if df.empty:
        logger.warning("Kein gültiger Datensatz nach Bereinigung übrig.")
        return df

    # --- Datentypen finalisieren ---
    df["budget_eur"] = pd.to_numeric(df["budget_eur"], errors="coerce")
    df["dauer_tage"] = pd.to_numeric(df["dauer_tage"], errors="coerce").astype("Int64")
    df["cpv_code"] = df["cpv_code"].astype("int32")
    df["land"] = df["land"].astype("category")

    # --- Qualitätsbericht ---
    n_mit_budget = df["budget_eur"].notna().sum()
    n_mit_dauer = df["dauer_tage"].notna().sum()

    logger.info(
        "Bereinigung abgeschlossen:\n"
        "  Eingabe:            %d\n"
        "  Kein CPV:           %d verworfen\n"
        "  Kein IT-CPV:        %d verworfen\n"
        "  Duplikate:          %d entfernt\n"
        "  Text zu kurz:       %d verworfen\n"
        "  ─────────────────────────────────\n"
        "  Ausgabe:            %d Zeilen\n"
        "  Mit Budget (EUR):   %d (%.0f%%)\n"
        "  Mit Laufzeit:       %d (%.0f%%)",
        roh_anzahl,
        kein_cpv, kein_it_cpv, duplikat, zu_kurzer_text,
        len(df),
        n_mit_budget, 100 * n_mit_budget / len(df),
        n_mit_dauer, 100 * n_mit_dauer / len(df),
    )

    return df


def preprocess_pipeline(
    eingabe_pfad: str = "data/raw_notices.jsonl",
    ausgabe_pfad: str = "data/processed_notices.parquet",
) -> pd.DataFrame:
    """
    Vollständige Pipeline: Laden → Bereinigen → Speichern als Parquet.
    Gibt den fertigen DataFrame zurück.
    """
    datensaetze = lade_jsonl(eingabe_pfad)
    df = erstelle_dataframe(datensaetze)

    if not df.empty:
        Path(ausgabe_pfad).parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(ausgabe_pfad, index=False)
        groesse_kb = Path(ausgabe_pfad).stat().st_size // 1024
        logger.info("Gespeichert: %s (%d KB)", ausgabe_pfad, groesse_kb)

    return df


# ---------------------------------------------------------------------------
# Direkt ausführbar
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    df = preprocess_pipeline()

    if not df.empty:
        print("\n── Spaltenübersicht ──────────────────────")
        print(df.dtypes.to_string())
        print("\n── Numerische Statistiken ────────────────")
        print(df[["budget_eur", "dauer_tage"]].describe().to_string())
        print("\n── Fehlende Werte ────────────────────────")
        print(df.isna().sum().to_string())
        print("\n── Top-Länder ────────────────────────────")
        print(df["land"].value_counts().head(10).to_string())
