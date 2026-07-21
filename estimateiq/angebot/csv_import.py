"""
CSV/Excel-Import historischer Leistungspositionen.
Erkennt Spalten automatisch (deutsch + englisch).
Wenn eine Projekt-Spalte vorhanden ist, werden Positionen nach Projekt gruppiert.
"""

from __future__ import annotations
import io
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_PROJEKT      = {"projekt", "projektname", "project", "project_name", "auftrag", "vorhaben"}
_BESCHREIBUNG = {"beschreibung", "description", "titel", "title", "position", "leistung", "text", "aufgabe"}
_ROLLE        = {"rolle", "role", "funktion", "function", "profil", "typ"}
_SOLL         = {"soll_stunden", "soll", "schätzung", "schaetzung", "geplant", "estimated_hours",
                 "hours", "stunden", "aufwand_soll", "plan_hours", "planned"}
_IST          = {"ist_stunden", "ist", "actual", "actual_hours", "aufwand_ist", "verbraucht",
                 "real_hours", "tatsaechlich", "tatsächlich"}
_STUNDENSATZ  = {"stundensatz", "stundensatz_eur", "satz", "rate", "hourly_rate", "preis",
                 "price", "tagessatz", "stundenpreis"}


def _find_col(df: pd.DataFrame, aliases: set[str]) -> str | None:
    for col in df.columns:
        if col.strip().lower().replace(" ", "_") in aliases:
            return col
    return None


def _dekodiere_csv(data: bytes) -> str:
    """
    Dekodiert CSV-Bytes robust: UTF-8 (mit/ohne BOM) zuerst, dann cp1252
    (Standard bei deutschen Excel-Exporten). latin-1 als letzter Fallback
    kann nie fehlschlagen.
    """
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def parse_upload(data: bytes, filename: str) -> dict:
    """
    Parst CSV oder Excel.

    Rückgabe:
      {
        "projekte": [{"name": str, "positionen": [...]}],   # wenn Projekt-Spalte vorhanden
        "einzelpositionen": [...],                           # wenn keine Projekt-Spalte
        "fehler": [...],
        "stats": {...},
        "hat_projekt_spalte": bool,
      }
    """
    suffix = Path(filename).suffix.lower()
    df = None
    try:
        if suffix in {".xlsx", ".xls"}:
            df = pd.read_excel(io.BytesIO(data))
        else:
            text = _dekodiere_csv(data)
            for sep in (",", ";", "\t"):
                try:
                    candidate = pd.read_csv(io.StringIO(text), sep=sep)
                    if len(candidate.columns) > 1:
                        df = candidate
                        break
                except Exception:
                    continue
            if df is None:
                df = pd.read_csv(io.StringIO(text))
    except Exception as e:
        return {
            "projekte": [], "einzelpositionen": [], "fehler": [str(e)],
            "stats": {"gesamt": 0, "akzeptiert": 0, "abgelehnt": 0},
            "hat_projekt_spalte": False,
        }

    col_projekt      = _find_col(df, _PROJEKT)
    col_beschreibung = _find_col(df, _BESCHREIBUNG)
    col_rolle        = _find_col(df, _ROLLE)
    col_soll         = _find_col(df, _SOLL)
    col_ist          = _find_col(df, _IST)
    col_stundensatz  = _find_col(df, _STUNDENSATZ)

    if col_beschreibung is None or col_soll is None:
        missing = []
        if col_beschreibung is None:
            missing.append("Beschreibung")
        if col_soll is None:
            missing.append("Soll-Stunden")
        return {
            "projekte": [], "einzelpositionen": [],
            "fehler": [f"Pflicht-Spalten fehlen: {', '.join(missing)}. Erkannte Spalten: {list(df.columns)}"],
            "stats": {"gesamt": len(df), "akzeptiert": 0, "abgelehnt": len(df)},
            "hat_projekt_spalte": col_projekt is not None,
        }

    positionen_roh = []
    fehler         = []

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

        projekt_name = None
        if col_projekt and pd.notna(row.get(col_projekt)):
            projekt_name = str(row[col_projekt]).strip() or None

        stundensatz = None
        if col_stundensatz and pd.notna(row.get(col_stundensatz)):
            try:
                sz_val = float(str(row[col_stundensatz]).replace(",", "."))
                if sz_val > 0:
                    stundensatz = sz_val
            except (ValueError, TypeError):
                pass

        positionen_roh.append({
            "beschreibung_text":  beschreibung,
            "soll_stunden":       soll,
            "ist_stunden":        ist,
            "rolle_name":         rolle_name,
            "projekt_name":       projekt_name,
            "stundensatz_snapshot": stundensatz,
        })

    stats = {
        "gesamt":     len(df),
        "akzeptiert": len(positionen_roh),
        "abgelehnt":  len(df) - len(positionen_roh),
        "spalten": {
            "projekt":      col_projekt,
            "beschreibung": col_beschreibung,
            "rolle":        col_rolle,
            "soll_stunden": col_soll,
            "ist_stunden":  col_ist,
            "stundensatz":  col_stundensatz,
        },
    }

    if col_projekt:
        # Nach Projekt gruppieren
        projekte_map: dict[str, list[dict]] = {}
        for p in positionen_roh:
            key = p["projekt_name"] or "__unbekannt__"
            projekte_map.setdefault(key, []).append(p)
        projekte = [{"name": name, "positionen": pos} for name, pos in projekte_map.items()]
        return {
            "projekte":           projekte,
            "einzelpositionen":   [],
            "fehler":             fehler,
            "stats":              {**stats, "projekte": len(projekte)},
            "hat_projekt_spalte": True,
        }
    else:
        return {
            "projekte":           [],
            "einzelpositionen":   positionen_roh,
            "fehler":             fehler,
            "stats":              stats,
            "hat_projekt_spalte": False,
        }
