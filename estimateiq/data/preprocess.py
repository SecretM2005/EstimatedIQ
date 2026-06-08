"""
Datenvorverarbeitung: Lädt rohe TED-Notices, bereinigt sie und gibt einen sauberen DataFrame zurück.
"""

import json
import logging
import re
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Schwellenwert: Ausschreibungen unter diesem Wert werden als Ausreißer verworfen
MIN_VALUE_EUR = 5_000
MAX_VALUE_EUR = 500_000_000

# Bekannte Währungsumrechnungsfaktoren zu EUR (näherungsweise, Stand 2024)
FX_TO_EUR = {
    "EUR": 1.0,
    "CHF": 1.05,
    "DKK": 0.134,
    "PLN": 0.232,
    "SEK": 0.088,
    "GBP": 1.17,
    "USD": 0.93,
    "NOK": 0.086,
    "CZK": 0.040,
    "HUF": 0.0026,
}

# CPV-Untergruppen für Feature Engineering
CPV_CATEGORIES = {
    "software": range(72200000, 72300000),
    "beratung": range(72300000, 72400000),
    "infrastruktur": range(72400000, 72500000),
    "sicherheit": range(72700000, 72800000),
    "wartung": range(72500000, 72600000),
    "sonstiges_it": range(72000000, 72200000),
}


def load_jsonl(path: str | Path) -> list[dict]:
    """Lädt eine JSON-Lines-Datei in eine Liste von Dicts."""
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    logger.info("Geladen: %d Rohdatensätze aus %s", len(records), path)
    return records


def _normalize_value(value: float | None, currency: str | None) -> float | None:
    """Wandelt einen Auftragswert in EUR um."""
    if value is None:
        return None
    factor = FX_TO_EUR.get((currency or "EUR").upper(), None)
    if factor is None:
        return None  # Unbekannte Währung → verwerfen
    return round(value * factor, 2)


def _parse_cpv(cpv_raw: str | None) -> int | None:
    """Extrahiert den numerischen CPV-Code aus Strings wie '72200000-9'."""
    if not cpv_raw:
        return None
    match = re.match(r"(\d{8})", str(cpv_raw).strip())
    return int(match.group(1)) if match else None


def _classify_cpv(cpv_code: int | None) -> str:
    """Ordnet einen CPV-Code einer inhaltlichen Kategorie zu."""
    if cpv_code is None:
        return "unbekannt"
    for category, rng in CPV_CATEGORIES.items():
        if cpv_code in rng:
            return category
    return "sonstiges_it"


def _clean_text(text: str | None) -> str:
    """Entfernt HTML-Tags, überflüssige Leerzeichen und Steuerzeichen."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_duration_days(date_str: str | None, pub_date_str: str | None) -> int | None:
    """Berechnet Laufzeit in Tagen aus End- und Publikationsdatum (Format: YYYYMMDD)."""
    if not date_str or not pub_date_str:
        return None
    try:
        end = pd.to_datetime(date_str, format="%Y%m%d", errors="coerce")
        start = pd.to_datetime(pub_date_str, format="%Y%m%d", errors="coerce")
        if pd.isna(end) or pd.isna(start):
            return None
        delta = (end - start).days
        return delta if 0 < delta < 3650 else None  # Max. 10 Jahre
    except Exception:
        return None


def build_dataframe(records: list[dict]) -> pd.DataFrame:
    """
    Bereinigt und strukturiert rohe TED-Notice-Dicts zu einem ML-bereiten DataFrame.

    Spalten des Ergebnis-DataFrames:
        document_id, publication_date, title_clean, description_clean,
        cpv_code, cpv_category, estimated_value_eur, country, nuts_code,
        contract_type, procedure_type, authority_type, award_criteria,
        duration_days, has_value, text_combined
    """
    rows = []

    for rec in records:
        cpv_raw = rec.get("cpv_code")
        cpv_code = _parse_cpv(cpv_raw)

        # Nur IT-CPV-Bereich behalten
        if cpv_code is None or not (72_000_000 <= cpv_code <= 72_900_000):
            continue

        value_eur = _normalize_value(rec.get("estimated_value"), rec.get("currency"))

        # Extremwerte herausfiltern
        if value_eur is not None and not (MIN_VALUE_EUR <= value_eur <= MAX_VALUE_EUR):
            value_eur = None

        title = _clean_text(rec.get("title"))
        description = _clean_text(rec.get("description"))

        duration = _extract_duration_days(
            rec.get("duration_end"),
            rec.get("publication_date"),
        )

        rows.append({
            "document_id": rec.get("document_id", ""),
            "publication_date": rec.get("publication_date"),
            "title_clean": title,
            "description_clean": description,
            "cpv_code": cpv_code,
            "cpv_category": _classify_cpv(cpv_code),
            "estimated_value_eur": value_eur,
            "country": (rec.get("country") or "").upper(),
            "nuts_code": rec.get("nuts_code"),
            "contract_type": rec.get("contract_type"),
            "procedure_type": rec.get("procedure_type"),
            "authority_type": rec.get("contracting_authority_type"),
            "award_criteria": rec.get("award_criteria"),
            "duration_days": duration,
            "has_value": value_eur is not None,
            # Kombinierter Text für BERT-Feature-Extraction
            "text_combined": f"{title} {description}".strip(),
        })

    df = pd.DataFrame(rows)

    if df.empty:
        logger.warning("Kein gültiger Datensatz nach Bereinigung übrig.")
        return df

    # Duplikate entfernen
    df = df.drop_duplicates(subset=["document_id"])

    # Datum parsen
    df["publication_date"] = pd.to_datetime(df["publication_date"], format="%Y%m%d", errors="coerce")

    # Kategoriale Spalten effizient kodieren
    for col in ["cpv_category", "country", "contract_type", "procedure_type", "authority_type", "award_criteria"]:
        df[col] = df[col].astype("category")

    logger.info(
        "DataFrame erstellt: %d Zeilen, davon %d mit Auftragswert (%.1f%%)",
        len(df),
        df["has_value"].sum(),
        100 * df["has_value"].mean(),
    )
    return df


def preprocess_pipeline(
    input_path: str = "data/raw_notices.jsonl",
    output_path: str = "data/processed_notices.parquet",
) -> pd.DataFrame:
    """
    Vollständige Pipeline: Laden → Bereinigen → Speichern als Parquet.
    Gibt den fertigen DataFrame zurück.
    """
    records = load_jsonl(input_path)
    df = build_dataframe(records)

    if not df.empty:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(output_path, index=False)
        logger.info("Gespeichert: %s (%d MB)", output_path, Path(output_path).stat().st_size // 1024 // 1024)

    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    df = preprocess_pipeline()
    print(df.describe())
    print(df.dtypes)
