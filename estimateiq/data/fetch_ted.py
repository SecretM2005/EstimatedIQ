"""
TED Europa API Connector – v3 (api.ted.europa.eu)
Ruft öffentliche EU-Ausschreibungen ab und filtert auf IT-relevante CPV-Codes (72*).

Zwei Abruf-Modi:
  CN  (Contract Notices)       – Vorabbekanntmachungen, ggf. Schätzwert
  CAN (Contract Award Notices) – Vergabebekanntmachungen, stets mit Auftragswert

Dokumentation: https://docs.ted.europa.eu/api/latest/index.html
"""

import time
import logging
from pathlib import Path
from typing import Iterator

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# API-Konfiguration
# ---------------------------------------------------------------------------

TED_API_BASE       = "https://api.ted.europa.eu/v3"
TED_SEARCH_URL     = f"{TED_API_BASE}/notices/search"
PAGE_SIZE_MAX      = 100

DACH_QUERY_CODES   = ["DEU", "AUT", "CHE"]
COUNTRY_3_TO_2     = {"DEU": "DE", "AUT": "AT", "CHE": "CH"}

RAW_DATA_DIR       = Path("data")
JAHRE_DEFAULT      = [2022, 2023, 2024]

# TED Notice-Typen für Vergabebekanntmachungen (CAN)
# NT=can* deckt alle Untervarianten ab (Standard, Sozial, Sektoren, Verteidigung).
# veat = freiwillige Ex-ante-Transparenzbekanntmachung (enthält ebenfalls Auftragswert).
CAN_TYPEN = [
    "can-standard",
    "can-social",
    "can-defu",
    "can-utilities",
    "can-cm",
    "veat",
]

# ---------------------------------------------------------------------------
# Felder, die aus der API abgerufen werden (eForms-Feldnamen)
# ---------------------------------------------------------------------------

FIELDS = [
    "publication-number",            # Bekanntmachungsnummer (z. B. "324247-2024")
    "publication-date",              # Veröffentlichungsdatum  (ISO-8601)
    "notice-type",                   # Typ: cn-standard | can-standard | ...
    "notice-title",                  # Mehrspr. Dict; wir lesen ["deu"]
    "description-lot",               # Beschreibung auf Los-Ebene  {"deu": [...]}
    "description-part",              # Beschreibung auf Teil-Ebene {"deu": [...]}
    "description-proc",              # Kurzbezeichnung Verfahren   {"deu": ...}
    "main-classification-lot",       # CPV-Code(s) als Array
    "main-classification-part",      # CPV-Code(s) Teil-Ebene
    "estimated-value-lot",           # Geschätzter Auftragswert    ["420000.00"]
    "estimated-value-cur-lot",       # Währung                     ["EUR"]
    "total-value",                   # Vergebener Gesamtwert (CAN) – immer vorhanden
    "total-value-cur",               # Währung Gesamtwert          ["EUR"]
    "buyer-country",                 # Land des Auftraggebers      ["DEU"]
    "contract-duration-end-date-lot",  # Laufzeitende              ["2026-08-16+02:00"]
    "contract-duration-end-date-part", # Laufzeitende Teil-Ebene
]


# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------

class TedNotice(BaseModel):
    """Normalisierte TED-Ausschreibung – kompatibel mit preprocess.py."""
    document_id:                 str
    publication_date:            str | None = None   # Format: YYYYMMDD
    title:                       str | None = None
    description:                 str | None = None
    cpv_code:                    str | None = None
    estimated_value:             float | None = None
    currency:                    str | None = None
    country:                     str | None = None   # 2-Buchstaben: DE/AT/CH
    duration_end:                str | None = None   # Format: YYYYMMDD
    notice_type:                 str | None = None   # cn-standard | can-standard | ...
    raw:                         dict = {}


# ---------------------------------------------------------------------------
# API-Client
# ---------------------------------------------------------------------------

class TedApiClient:
    """
    Kommuniziert mit api.ted.europa.eu/v3.
    Unterstützt paginierte Abfragen mit automatischem Retry bei Rate-Limits.
    """

    def __init__(self, page_size: int = PAGE_SIZE_MAX, max_retries: int = 3, timeout: float = 30.0):
        self.page_size  = min(page_size, 250)
        self.max_retries = max_retries
        self.client      = httpx.Client(timeout=timeout)

    # ------------------------------------------------------------------ Query

    def _build_query(
        self,
        countries: list[str] | None = None,
        year: int | None = None,
        nur_vergaben: bool = False,
    ) -> str:
        """
        Baut die Expert-Query für die TED v3 API zusammen.

        Args:
            countries:    ISO alpha-3 Ländercodes (z. B. ['DEU','AUT','CHE'])
            year:         Filtert auf ein bestimmtes Kalenderjahr
            nur_vergaben: True → nur Contract Award Notices (CAN), enthält Auftragswert
        """
        filter_teile = ["PC=72*"]

        if nur_vergaben:
            nt_ausdruck = " OR ".join(f"NT={t}" for t in CAN_TYPEN)
            filter_teile.append(f"({nt_ausdruck})")

        if countries:
            laender_ausdruck = " OR ".join(f"buyer-country={c}" for c in countries)
            filter_teile.append(f"({laender_ausdruck})")

        if year:
            filter_teile.append(f"PD>={year}0101 AND PD<={year}1231")

        return " AND ".join(filter_teile)

    # ------------------------------------------------------------------ HTTP

    def _request_page(self, query: str, page: int) -> dict:
        """Einzelne paginierte Anfrage mit Retry-Logik."""
        payload = {
            "query":          query,
            "fields":         FIELDS,
            "page":           page,
            "limit":          self.page_size,
            "paginationMode": "PAGE_NUMBER",
        }

        for versuch in range(self.max_retries):
            try:
                response = self.client.post(TED_SEARCH_URL, json=payload)

                if response.status_code == 429:
                    warte = int(response.headers.get("Retry-After", 10))
                    logger.warning("Rate-Limit erreicht – warte %d Sekunden.", warte)
                    time.sleep(warte)
                    continue

                if not response.is_success:
                    logger.error("HTTP %d: %s", response.status_code, response.text[:300])

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as exc:
                logger.error("HTTP-Fehler bei Seite %d (Versuch %d/%d): %s",
                             page, versuch + 1, self.max_retries, exc)
                if versuch < self.max_retries - 1:
                    time.sleep(2 ** versuch)
                else:
                    raise

            except httpx.RequestError as exc:
                logger.error("Verbindungsfehler bei Seite %d: %s", page, exc)
                if versuch < self.max_retries - 1:
                    time.sleep(2 ** versuch)
                else:
                    raise

        raise RuntimeError(f"Alle {self.max_retries} Versuche für Seite {page} fehlgeschlagen")

    # ------------------------------------------------------------------ Parse

    @staticmethod
    def _extrahiere_text(feld: dict | list | str | None, sprache: str = "deu") -> str | None:
        """
        Extrahiert deutschen Text aus mehrsprachigen eForms-Feldern.
        Struktur: {"deu": ["Text…"], "eng": ["Text…"]} oder {"deu": "Text"}
        """
        if not feld:
            return None
        if isinstance(feld, str):
            return feld.strip() or None
        if isinstance(feld, list):
            # Array von Strings (z. B. CPV-Codes)
            return str(feld[0]).strip() if feld else None
        if isinstance(feld, dict):
            # Bevorzuge Deutsch, dann Englisch, dann ersten verfügbaren Wert
            for lang in (sprache, "eng"):
                val = feld.get(lang)
                if val:
                    if isinstance(val, list):
                        return " ".join(str(v) for v in val).strip() or None
                    return str(val).strip() or None
            # Fallback: erster vorhandener Wert
            for val in feld.values():
                if val:
                    if isinstance(val, list):
                        return " ".join(str(v) for v in val).strip() or None
                    return str(val).strip() or None
        return None

    @staticmethod
    def _iso_zu_yyyymmdd(datum_str: str | None) -> str | None:
        """
        Konvertiert ISO-8601-Datum ("2024-06-03Z", "2026-08-16+02:00") → "YYYYMMDD".
        Format, das preprocess.py erwartet.
        """
        if not datum_str:
            return None
        try:
            # Zeitzone-Suffix abschneiden
            kern = datum_str[:10].replace("-", "")
            return kern if len(kern) == 8 and kern.isdigit() else None
        except Exception:
            return None

    @staticmethod
    def _extrahiere_wert(feld: list | str | float | int | None) -> float | None:
        """Liest einen numerischen Wert aus String, Liste oder Zahl."""
        if feld is None:
            return None
        if isinstance(feld, (int, float)):
            return float(feld) if feld > 0 else None
        if isinstance(feld, list) and feld:
            feld = feld[0]
        try:
            wert = float(str(feld).replace(",", ".").replace(" ", ""))
            return wert if wert > 0 else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _extrahiere_waehrung(feld: list | str | None) -> str | None:
        """Liest den Währungscode aus einem Array oder String-Feld."""
        if not feld:
            return None
        val = feld[0] if isinstance(feld, list) else feld
        return str(val).upper().strip() or None

    def _parse_notice(self, raw: dict) -> TedNotice:
        """Wandelt ein rohes eForms-Objekt in ein TedNotice-Modell um."""

        # Titel: bevorzuge Deutsch
        titel = self._extrahiere_text(raw.get("notice-title"))

        # Beschreibung: Los-Ebene → Teil-Ebene → Verfahren
        beschreibung = (
            self._extrahiere_text(raw.get("description-lot"))
            or self._extrahiere_text(raw.get("description-part"))
            or self._extrahiere_text(raw.get("description-proc"))
        )

        # CPV: Los → Teil
        cpv = (
            self._extrahiere_text(raw.get("main-classification-lot"))
            or self._extrahiere_text(raw.get("main-classification-part"))
        )

        # Budget: Schätzwert (CN) → vergebener Gesamtwert (CAN, Pflichtfeld)
        wert = (
            self._extrahiere_wert(raw.get("estimated-value-lot"))
            or self._extrahiere_wert(raw.get("total-value"))
        )
        waehrung = (
            self._extrahiere_waehrung(raw.get("estimated-value-cur-lot"))
            or self._extrahiere_waehrung(raw.get("total-value-cur"))
        )

        # Land: ISO alpha-3 → alpha-2
        land_raw = raw.get("buyer-country", [])
        land_3 = (land_raw[0] if isinstance(land_raw, list) and land_raw
                  else str(land_raw) if land_raw else None)
        land_2 = COUNTRY_3_TO_2.get(land_3 or "", land_3)

        # Laufzeitende: Los → Teil
        laufzeit_ende = (
            self._iso_zu_yyyymmdd(
                (raw.get("contract-duration-end-date-lot") or [None])[0]
                if isinstance(raw.get("contract-duration-end-date-lot"), list)
                else raw.get("contract-duration-end-date-lot")
            )
            or self._iso_zu_yyyymmdd(
                (raw.get("contract-duration-end-date-part") or [None])[0]
                if isinstance(raw.get("contract-duration-end-date-part"), list)
                else raw.get("contract-duration-end-date-part")
            )
        )

        return TedNotice(
            document_id       = raw.get("publication-number", ""),
            publication_date  = self._iso_zu_yyyymmdd(raw.get("publication-date")),
            title             = titel,
            description       = beschreibung,
            cpv_code          = cpv,
            estimated_value   = wert,
            currency          = waehrung,
            country           = land_2,
            duration_end      = laufzeit_ende,
            notice_type       = raw.get("notice-type"),
            raw               = raw,
        )

    # ------------------------------------------------------------------ Generator

    def fetch_notices(
        self,
        countries: list[str] | None = None,
        year: int | None = None,
        max_pages: int | None = None,
        nur_vergaben: bool = False,
    ) -> Iterator[TedNotice]:
        """
        Generator: Liefert alle IT-Ausschreibungen seitenweise.

        Args:
            countries:    3-Buchstaben-Codes (z. B. ['DEU','AUT','CHE']); None = alle
            year:         Filtert auf ein bestimmtes Jahr
            max_pages:    Maximale Seitenanzahl (None = alle)
            nur_vergaben: True → nur Contract Award Notices (CAN)
        """
        query = self._build_query(countries=countries, year=year, nur_vergaben=nur_vergaben)
        logger.info("TED-Abfrage: %s", query)

        page           = 1
        total_geladen  = 0

        while True:
            logger.info("Lade Seite %d...", page)
            data  = self._request_page(query, page)

            total     = data.get("totalNoticeCount", 0)
            notices   = data.get("notices", [])

            if not notices:
                logger.info("Keine weiteren Ausschreibungen. Gesamt: %d", total_geladen)
                break

            for raw_notice in notices:
                yield self._parse_notice(raw_notice)
                total_geladen += 1

            logger.info("Seite %d: %d Einträge geladen (%d/%d)",
                        page, len(notices), total_geladen, total)

            if max_pages and page >= max_pages:
                break
            if total and total_geladen >= total:
                break

            page += 1

    def fetch_dach_notices(self, year: int | None = None, max_pages: int | None = None) -> Iterator[TedNotice]:
        """IT-Ausschreibungen (CN) aus Deutschland, Österreich und der Schweiz."""
        return self.fetch_notices(countries=DACH_QUERY_CODES, year=year, max_pages=max_pages)

    def fetch_dach_award_notices(self, year: int | None = None, max_pages: int | None = None) -> Iterator[TedNotice]:
        """IT-Vergabebekanntmachungen (CAN) aus DACH – enthalten stets Auftragswert."""
        return self.fetch_notices(
            countries=DACH_QUERY_CODES, year=year, max_pages=max_pages, nur_vergaben=True,
        )

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ---------------------------------------------------------------------------
# Convenience-Funktionen
# ---------------------------------------------------------------------------

def fetch_and_save(
    output_path: str | Path | None = None,
    countries: list[str] | None = None,
    year: int | None = None,
    max_pages: int | None = None,
    nur_vergaben: bool = False,
) -> int:
    """
    Ruft TED-Ausschreibungen ab und speichert sie als JSON Lines.
    Gibt die Anzahl gespeicherter Datensätze zurück.

    Wenn output_path nicht angegeben wird:
      - CN:  data/raw_notices_{year}.jsonl
      - CAN: data/raw_notices_awards_{year}.jsonl
    """
    import json

    if output_path is None:
        suffix = f"_{year}" if year else ""
        prefix = "raw_notices_awards" if nur_vergaben else "raw_notices"
        output_path = RAW_DATA_DIR / f"{prefix}{suffix}.jsonl"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    gespeichert = 0
    with TedApiClient() as client, output_path.open("w", encoding="utf-8") as f:
        for notice in client.fetch_notices(
            countries=countries, year=year, max_pages=max_pages, nur_vergaben=nur_vergaben,
        ):
            f.write(json.dumps(notice.model_dump(), ensure_ascii=False) + "\n")
            gespeichert += 1

    logger.info("Gespeichert: %d Bekanntmachungen → %s", gespeichert, output_path)
    return gespeichert


def fetch_dach_alle_vergaben(
    output_dir: str | Path = RAW_DATA_DIR,
    jahre: list[int] = JAHRE_DEFAULT,
    max_pages: int | None = None,
) -> dict[int, int]:
    """
    Ruft DACH IT-Vergabebekanntmachungen (CAN) für mehrere Jahre ab.
    Speichert jedes Jahr: data/raw_notices_awards_{jahr}.jsonl

    Diese Dateien werden von preprocess.py automatisch erkannt
    (Glob-Muster raw_notices_*.jsonl) und enthalten stets einen Auftragswert,
    was die Budget-Label-Rate signifikant erhöht.

    Returns:
        Dict {jahr: anzahl_datensaetze}
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ergebnisse: dict[int, int] = {}

    for jahr in jahre:
        pfad = output_dir / f"raw_notices_awards_{jahr}.jsonl"
        logger.info("=== CAN Jahrgang %d → %s ===", jahr, pfad)
        anzahl = fetch_and_save(
            output_path=pfad,
            countries=DACH_QUERY_CODES,
            year=jahr,
            max_pages=max_pages,
            nur_vergaben=True,
        )
        ergebnisse[jahr] = anzahl
        logger.info("CAN Jahrgang %d: %d Vergabebekanntmachungen gespeichert.", jahr, anzahl)

    gesamt = sum(ergebnisse.values())
    logger.info("Alle CAN-Jahrgänge abgeschlossen. Gesamt: %d Vergaben.", gesamt)
    return ergebnisse


def fetch_dach_alle_jahre(
    output_dir: str | Path = RAW_DATA_DIR,
    jahre: list[int] = JAHRE_DEFAULT,
    max_pages: int | None = None,
) -> dict[int, int]:
    """
    Ruft DACH IT-Ausschreibungen für mehrere Jahre ab.
    Speichert jedes Jahr in eine eigene Datei: raw_notices_{jahr}.jsonl

    Args:
        output_dir:  Zielverzeichnis
        jahre:       Liste der Jahrgänge (Standard: 2022, 2023, 2024)
        max_pages:   Maximale Seitenzahl pro Jahr (None = alle)

    Returns:
        Dict {jahr: anzahl_datensaetze}
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ergebnisse: dict[int, int] = {}

    for jahr in jahre:
        pfad = output_dir / f"raw_notices_{jahr}.jsonl"
        logger.info("=== Jahrgang %d → %s ===", jahr, pfad)
        anzahl = fetch_and_save(
            output_path=pfad,
            countries=DACH_QUERY_CODES,
            year=jahr,
            max_pages=max_pages,
        )
        ergebnisse[jahr] = anzahl
        logger.info("Jahrgang %d: %d Ausschreibungen gespeichert.", jahr, anzahl)

    gesamt = sum(ergebnisse.values())
    logger.info("Alle Jahrgänge abgeschlossen. Gesamt: %d Ausschreibungen.", gesamt)
    return ergebnisse


# ---------------------------------------------------------------------------
# Direkt ausführbar
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="TED-Daten abrufen (CN, CAN oder beides)"
    )
    parser.add_argument(
        "--modus",
        choices=["cn", "can", "beides"],
        default="beides",
        help=(
            "cn    = nur Ausschreibungen (Contract Notices)\n"
            "can   = nur Vergaben (Contract Award Notices, haben stets Budget)\n"
            "beides= beides abrufen (Standard)"
        ),
    )
    parser.add_argument(
        "--max-seiten", type=int, default=None,
        help="Max. Seitenanzahl pro Jahr (None = alle, nützlich zum Testen)",
    )
    args = parser.parse_args()

    ergebnisse_cn:  dict[int, int] = {}
    ergebnisse_can: dict[int, int] = {}

    if args.modus in ("cn", "beides"):
        ergebnisse_cn = fetch_dach_alle_jahre(
            jahre=JAHRE_DEFAULT, max_pages=args.max_seiten,
        )

    if args.modus in ("can", "beides"):
        ergebnisse_can = fetch_dach_alle_vergaben(
            jahre=JAHRE_DEFAULT, max_pages=args.max_seiten,
        )

    print("\n" + "═" * 48)
    print("  TED-Abruf abgeschlossen")
    print("═" * 48)
    if ergebnisse_cn:
        print("\n  Contract Notices (CN):")
        for jahr, n in ergebnisse_cn.items():
            print(f"    {jahr}: {n:>6,} Ausschreibungen")
        print(f"    {'Gesamt':} {sum(ergebnisse_cn.values()):>6,}")
    if ergebnisse_can:
        print("\n  Contract Award Notices (CAN):")
        for jahr, n in ergebnisse_can.items():
            print(f"    {jahr}: {n:>6,} Vergaben")
        print(f"    {'Gesamt':} {sum(ergebnisse_can.values()):>6,}")
    print("═" * 48 + "\n")
