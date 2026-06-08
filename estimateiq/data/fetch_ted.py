"""
TED Europa API Connector
Ruft öffentliche EU-Ausschreibungen ab und filtert auf IT-relevante CPV-Codes (72000000–72900000).
Dokumentation: https://ted.europa.eu/api/v3.0
"""

import time
import logging
from typing import Iterator

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# TED API Basiskonfiguration
TED_API_BASE = "https://ted.europa.eu/api/v3.0"
TED_SEARCH_ENDPOINT = f"{TED_API_BASE}/notices/search"

# IT-relevante CPV-Codes (Informationstechnologie & Dienstleistungen)
IT_CPV_RANGE_START = 72000000
IT_CPV_RANGE_END = 72900000

# Felder, die aus der TED-API abgerufen werden
FIELDS = [
    "ND",           # Dokumentennummer
    "PD",           # Veröffentlichungsdatum
    "TD",           # Dokumenttyp
    "AA",           # Auftraggeber-Typ
    "AC",           # Vergabekriterien
    "PC",           # CPV-Hauptcode
    "TI",           # Titel
    "DS",           # Beschreibung
    "VA",           # Geschätzter Gesamtwert
    "CY",           # Land
    "TW",           # Ort
    "TE",           # Laufzeitende
    "NC",           # Art des Auftrags
    "PR",           # Verfahrensart
    "RC",           # NUTS-Code (Region)
    "RN",           # Referenznummer
]

# DACH-Ländercodes
DACH_COUNTRIES = ["DE", "AT", "CH"]


class TedNotice(BaseModel):
    """Repräsentiert eine einzelne TED-Ausschreibung."""
    document_id: str
    publication_date: str | None = None
    title: str | None = None
    description: str | None = None
    cpv_code: str | None = None
    estimated_value: float | None = None
    currency: str | None = None
    country: str | None = None
    city: str | None = None
    contracting_authority_type: str | None = None
    contract_type: str | None = None
    procedure_type: str | None = None
    award_criteria: str | None = None
    duration_end: str | None = None
    nuts_code: str | None = None
    reference_number: str | None = None
    raw: dict = {}


class TedApiClient:
    """
    Kommuniziert mit der TED Europa REST API v3.
    Unterstützt paginierte Abfragen mit automatischem Retry bei Rate-Limits.
    """

    def __init__(
        self,
        page_size: int = 100,
        max_retries: int = 3,
        timeout: float = 30.0,
    ):
        self.page_size = page_size
        self.max_retries = max_retries
        self.client = httpx.Client(timeout=timeout)

    def _build_cpv_filter(self) -> str:
        """Erstellt einen CQL-Filter für den IT-CPV-Bereich."""
        # TED-API nutzt CQL (Common Query Language)
        codes = [str(c) for c in range(IT_CPV_RANGE_START, IT_CPV_RANGE_END + 1, 100000)]
        cpv_conditions = " OR ".join(f'PC=[{IT_CPV_RANGE_START},{IT_CPV_RANGE_END}]')
        return f"PC=[{IT_CPV_RANGE_START},{IT_CPV_RANGE_END}]"

    def _build_query(self, countries: list[str] | None = None, year: int | None = None) -> str:
        """Baut die CQL-Suchanfrage zusammen."""
        filters = [self._build_cpv_filter()]

        if countries:
            country_filter = " OR ".join(f'CY={c}' for c in countries)
            filters.append(f"({country_filter})")

        if year:
            filters.append(f"PD>={year}0101 AND PD<={year}1231")

        # Nur Bekanntmachungen mit vergebenen Aufträgen (TD=7) oder Ausschreibungen (TD=3)
        filters.append("(TD=3 OR TD=7)")

        return " AND ".join(filters)

    def _parse_notice(self, raw: dict) -> TedNotice:
        """Wandelt ein rohes API-Objekt in ein TedNotice-Modell um."""
        fields = raw.get("fields", {})

        # Geschätzten Wert extrahieren (kann Bereich oder Einzelwert sein)
        value = None
        currency = None
        val_field = fields.get("VA", [])
        if val_field:
            try:
                value = float(str(val_field[0]).replace(",", ".").replace(" ", ""))
            except (ValueError, TypeError):
                pass
        if isinstance(val_field, list) and len(val_field) > 1:
            currency = val_field[-1] if isinstance(val_field[-1], str) else None

        return TedNotice(
            document_id=fields.get("ND", [""])[0] if fields.get("ND") else raw.get("_id", ""),
            publication_date=fields.get("PD", [None])[0] if fields.get("PD") else None,
            title=fields.get("TI", [None])[0] if fields.get("TI") else None,
            description=fields.get("DS", [None])[0] if fields.get("DS") else None,
            cpv_code=fields.get("PC", [None])[0] if fields.get("PC") else None,
            estimated_value=value,
            currency=currency,
            country=fields.get("CY", [None])[0] if fields.get("CY") else None,
            city=fields.get("TW", [None])[0] if fields.get("TW") else None,
            contracting_authority_type=fields.get("AA", [None])[0] if fields.get("AA") else None,
            contract_type=fields.get("NC", [None])[0] if fields.get("NC") else None,
            procedure_type=fields.get("PR", [None])[0] if fields.get("PR") else None,
            award_criteria=fields.get("AC", [None])[0] if fields.get("AC") else None,
            duration_end=fields.get("TE", [None])[0] if fields.get("TE") else None,
            nuts_code=fields.get("RC", [None])[0] if fields.get("RC") else None,
            reference_number=fields.get("RN", [None])[0] if fields.get("RN") else None,
            raw=raw,
        )

    def _request_page(self, query: str, page: int) -> dict:
        """Führt eine einzelne paginierte Anfrage durch, mit Retry-Logik."""
        payload = {
            "query": query,
            "fields": FIELDS,
            "pageNum": page,
            "pageSize": self.page_size,
            "sortField": "PD",
            "sortOrder": "DESC",
        }

        for attempt in range(self.max_retries):
            try:
                response = self.client.post(TED_SEARCH_ENDPOINT, json=payload)

                # Rate-Limit abwarten
                if response.status_code == 429:
                    wait = int(response.headers.get("Retry-After", 10))
                    logger.warning("Rate-Limit erreicht, warte %d Sekunden...", wait)
                    time.sleep(wait)
                    continue

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as exc:
                logger.error("HTTP-Fehler bei Seite %d: %s", page, exc)
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise

            except httpx.RequestError as exc:
                logger.error("Verbindungsfehler bei Seite %d: %s", page, exc)
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise

        raise RuntimeError(f"Alle {self.max_retries} Versuche für Seite {page} fehlgeschlagen")

    def fetch_notices(
        self,
        countries: list[str] | None = None,
        year: int | None = None,
        max_pages: int | None = None,
    ) -> Iterator[TedNotice]:
        """
        Generator: Liefert alle IT-Ausschreibungen seitenweise.

        Args:
            countries: Ländercodes (z. B. ['DE', 'AT', 'CH']); None = alle
            year:      Filtert auf ein bestimmtes Jahr
            max_pages: Maximale Anzahl Seiten (None = alle)
        """
        query = self._build_query(countries=countries, year=year)
        logger.info("TED-Abfrage: %s", query)

        page = 1
        total_fetched = 0

        while True:
            logger.info("Lade Seite %d...", page)
            data = self._request_page(query, page)

            notices = data.get("notices", [])
            total = data.get("total", 0)

            if not notices:
                logger.info("Keine weiteren Ausschreibungen. Gesamt: %d", total_fetched)
                break

            for raw_notice in notices:
                notice = self._parse_notice(raw_notice)
                total_fetched += 1
                yield notice

            logger.info("Seite %d: %d Ausschreibungen geladen (%d/%d)", page, len(notices), total_fetched, total)

            # Abbruchbedingungen
            if max_pages and page >= max_pages:
                break
            if total_fetched >= total:
                break

            page += 1

    def fetch_dach_notices(self, year: int | None = None, max_pages: int | None = None) -> Iterator[TedNotice]:
        """Ruft IT-Ausschreibungen aus Deutschland, Österreich und der Schweiz ab."""
        return self.fetch_notices(countries=DACH_COUNTRIES, year=year, max_pages=max_pages)

    def close(self):
        """Schließt den HTTP-Client."""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def fetch_and_save(
    output_path: str = "data/raw_notices.jsonl",
    countries: list[str] | None = None,
    year: int | None = None,
    max_pages: int | None = None,
) -> int:
    """
    Ruft TED-Ausschreibungen ab und speichert sie als JSON Lines-Datei.
    Gibt die Anzahl gespeicherter Datensätze zurück.
    """
    import json
    import os

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    saved = 0
    with TedApiClient() as client, open(output_path, "w", encoding="utf-8") as f:
        for notice in client.fetch_notices(countries=countries, year=year, max_pages=max_pages):
            f.write(json.dumps(notice.model_dump(), ensure_ascii=False) + "\n")
            saved += 1

    logger.info("Gespeichert: %d Ausschreibungen in %s", saved, output_path)
    return saved


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Beispielaufruf: DACH-Ausschreibungen für 2024 laden (max. 5 Seiten zum Testen)
    count = fetch_and_save(
        output_path="data/raw_notices.jsonl",
        countries=DACH_COUNTRIES,
        year=2024,
        max_pages=5,
    )
    print(f"Abgeschlossen: {count} Ausschreibungen gespeichert.")
