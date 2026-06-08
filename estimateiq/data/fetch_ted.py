"""
TED Europa API Connector – v3 (api.ted.europa.eu)
Ruft öffentliche EU-Ausschreibungen ab und filtert auf IT-relevante CPV-Codes (72*).
Dokumentation: https://docs.ted.europa.eu/api/latest/index.html
"""

import time
import logging
from typing import Iterator

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# API-Konfiguration
# ---------------------------------------------------------------------------

TED_API_BASE       = "https://api.ted.europa.eu/v3"
TED_SEARCH_URL     = f"{TED_API_BASE}/notices/search"
PAGE_SIZE_MAX      = 100   # max 250 laut Doku; 100 ist ein robuster Wert

# DACH-Ländercodes (v3 API nutzt ISO 3166-1 alpha-3)
DACH_QUERY_CODES   = ["DEU", "AUT", "CHE"]
# Rückgabe-Konvertierung → 2-Buchstaben für preprocess.py
COUNTRY_3_TO_2 = {"DEU": "DE", "AUT": "AT", "CHE": "CH"}

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
    "total-value",                   # Vergebener Gesamtwert       (Zahl)
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

    def _build_query(self, countries: list[str] | None = None, year: int | None = None) -> str:
        """
        Baut die Expert-Query für die TED v3 API zusammen.

        Syntax-Änderungen gegenüber v2:
          - CPV-Bereich: PC=72*  (kein Bereichsoperator [ ] mehr)
          - Ländercodes: buyer-country=DEU  (ISO alpha-3 statt alpha-2)
          - Datumsfilter: PD>=YYYYMMDD  (funktioniert weiterhin)
          - Dokumenttyp TD=3/TD=7 entfällt (Typ als notice-type im Response)
        """
        filter_teile = ["PC=72*"]

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

        # Budget: geschätzter Wert → Gesamtwert vergabe
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
            raw               = raw,
        )

    # ------------------------------------------------------------------ Generator

    def fetch_notices(
        self,
        countries: list[str] | None = None,
        year: int | None = None,
        max_pages: int | None = None,
    ) -> Iterator[TedNotice]:
        """
        Generator: Liefert alle IT-Ausschreibungen seitenweise.

        Args:
            countries:  3-Buchstaben-Codes (z. B. ['DEU','AUT','CHE']); None = alle
            year:       Filtert auf ein bestimmtes Jahr
            max_pages:  Maximale Seitenanzahl (None = alle)
        """
        query = self._build_query(countries=countries, year=year)
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
        """IT-Ausschreibungen aus Deutschland, Österreich und der Schweiz."""
        return self.fetch_notices(countries=DACH_QUERY_CODES, year=year, max_pages=max_pages)

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ---------------------------------------------------------------------------
# Convenience-Funktion
# ---------------------------------------------------------------------------

def fetch_and_save(
    output_path: str = "data/raw_notices.jsonl",
    countries: list[str] | None = None,
    year: int | None = None,
    max_pages: int | None = None,
) -> int:
    """
    Ruft TED-Ausschreibungen ab und speichert sie als JSON Lines (streambar, append-fähig).
    Gibt die Anzahl gespeicherter Datensätze zurück.
    """
    import json
    import os

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    gespeichert = 0
    with TedApiClient() as client, open(output_path, "w", encoding="utf-8") as f:
        for notice in client.fetch_notices(countries=countries, year=year, max_pages=max_pages):
            f.write(json.dumps(notice.model_dump(), ensure_ascii=False) + "\n")
            gespeichert += 1

    logger.info("Gespeichert: %d Ausschreibungen → %s", gespeichert, output_path)
    return gespeichert


# ---------------------------------------------------------------------------
# Direkt ausführbar
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    anzahl = fetch_and_save(
        output_path="data/raw_notices.jsonl",
        countries=DACH_QUERY_CODES,
        year=2024,
        max_pages=5,   # ~500 Einträge zum Testen
    )
    print(f"\nAbgeschlossen: {anzahl} Ausschreibungen gespeichert.")
