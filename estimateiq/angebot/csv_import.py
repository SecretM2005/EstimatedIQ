"""
CSV/Excel-Import historischer Leistungspositionen.
Erkennt Spalten automatisch (deutsch + englisch).
"""

from __future__ import annotations
import io
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_BESCHREIBUNG = {"beschreibung", "description", "titel", "title", "position", "leistung", "text", "aufgabe"}
_ROLLE        = {"rolle", "role", "funktion", "function", "profil", "typ"}
_SOLL         = {"soll_stunden", "soll", "schätzung", "schaetzung", "geplant", "estimated_hours",
                 "hours", "stunden", "aufwand_soll", "plan_hours", "planned"}
_IST          = {"ist_stunden", "ist", "actual", "actual_hours", "aufwand_ist", "verbraucht",
                 "real_hours", "tatsaechlich", "tatsächlich"}


def _find_col(df: pd.DataFrame, aliases: set[str]) -> str | None:
    for col in df.columns:
        if col.strip().lower().replace(" ", "_") in aliases:
            return col
    return None


def parse_upload(data: bytes, filename: str) -> dict:
    """
    Parst CSV oder Excel.
    Gibt zurück: {"positionen": [...], "fehler": [...], "stats": {...}}
    """
    suffix = Path(filename).suffix.lower()
    df = None
    try:
        if suffix in {".xlsx", ".xls"}:
            df = pd.read_excel(io.BytesIO(data))
        else:
            for sep in (",", ";", "\t"):
                try:
                    candidate = pd.read_csv(io.BytesIO(data), sep=sep)
                    if len(candidate.columns) > 1:
                        df = candidate
                        break
                except Exception:
                    continue
            if df is None:
                df = pd.read_csv(io.BytesIO(data))
    except Exception as e:
        return {"positionen": [], "fehler": [str(e)], "stats": {"gesamt": 0, "akzeptiert": 0, "abgelehnt": 0}}

    col_beschreibung = _find_col(df, _BESCHREIBUNG)
    col_rolle        = _find_col(df, _ROLLE)
    col_soll         = _find_col(df, _SOLL)
    col_ist          = _find_col(df, _IST)

    if col_beschreibung is None or col_soll is None:
        missing = []
        if col_beschreibung is None:
            missing.append("Beschreibung")
        if col_soll is None:
            missing.append("Soll-Stunden")
        return {
            "positionen": [],
            "fehler": [f"Pflicht-Spalten fehlen: {', '.join(missing)}. Erkannte Spalten: {list(df.columns)}"],
            "stats": {"gesamt": len(df), "akzeptiert": 0, "abgelehnt": len(df)},
        }

    positionen = []
    fehler     = []

    for i, row in df.iterrows():
        beschreibung = str(row.get(col_beschreibung, "") or "").strip()
        if not beschreibung or len(beschreibung) < 3:
            fehler.append(f"Zeile {i+2}: Beschreibung zu kurz oder leer")
            continue

        try:
            soll = float(str(row[col_soll]).replace(",", "."))
            if soll <= 0:
                raise ValueError("Stunden müssen > 0 sein")
        except (ValueError, TypeError) as e:
            fehler.append(f"Zeile {i+2}: Ungültige Soll-Stunden – {e}")
            continue

        ist = None
        if col_ist and pd.notna(row.get(col_ist)):
            try:
                ist_val = float(str(row[col_ist]).replace(",", "."))
                if ist_val > 0:
                    ist = ist_val
            except (ValueError, TypeError):
                pass

        rolle_name = None
        if col_rolle and pd.notna(row.get(col_rolle)):
            rolle_name = str(row[col_rolle]).strip() or None

        positionen.append({
            "beschreibung_text": beschreibung,
            "soll_stunden":      soll,
            "ist_stunden":       ist,
            "rolle_name":        rolle_name,
        })

    return {
        "positionen": positionen,
        "fehler":     fehler,
        "stats": {
            "gesamt":     len(df),
            "akzeptiert": len(positionen),
            "abgelehnt":  len(df) - len(positionen),
            "spalten": {
                "beschreibung": col_beschreibung,
                "rolle":        col_rolle,
                "soll_stunden": col_soll,
                "ist_stunden":  col_ist,
            },
        },
    }
