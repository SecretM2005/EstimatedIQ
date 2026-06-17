"""
TED Europa API Connector – Bauprojekte (CPV 45*)

Analog zu fetch_ted.py, aber für Bau-CPV-Codes 45000000–45999999.
Extrahiert zusätzlich Auftraggeber-Ort und PLZ für Geocoding.

Speichert: data/raw_notices_bau_{YYYY}.jsonl
"""

import calendar
import json
import logging
import time
from pathlib import Path
from typing import Iterator

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

TED_API_BASE   = "https://api.ted.europa.eu/v3"
TED_SEARCH_URL = f"{TED_API_BASE}/notices/search"
PAGE_SIZE_MAX  = 100

DACH_QUERY_CODES = ["DEU", "AUT", "CHE"]
COUNTRY_3_TO_2   = {"DEU": "DE", "AUT": "AT", "CHE": "CH"}

RAW_DATA_DIR = Path("data")
JAHRE_DEFAULT = [2020, 2021, 2022, 2023, 2024]

# Bau-CPV-Codes (45*)
BAU_CPV_CODES = [
    "45000000",  # Bauarbeiten allgemein
    "45100000",  # Vorbereitung Baustelle
    "45200000",  # Hoch- und Tiefbau
    "45210000",  # Hochbau
    "45211000",  # Wohngebäude
    "45212000",  # Freizeit & Sport
    "45213000",  # Gewerbegebäude
    "45214000",  # Schulen
    "45215000",  # Gesundheitsgebäude
    "45300000",  # Gebäudetechnik
    "45310000",  # Elektro
    "45330000",  # Sanitär & Heizung
    "45400000",  # Ausbauarbeiten
    "45410000",  # Putz & Stuck
    "45420000",  # Tischler & Zimmerer
    "45430000",  # Boden & Wand
    "45440000",  # Malerarbeiten
    "45450000",  # Sonstige Ausbauarbeiten
]

# eForms-Felder für die Bau-Abfrage (nur von TED v3 unterstützte Felder)
FIELDS = [
    "publication-number",
    "publication-date",
    "notice-type",
    "notice-title",
    "description-lot",
    "description-part",
    "description-proc",
    "main-classification-lot",
    "main-classification-part",
    "estimated-value-lot",
    "estimated-value-cur-lot",
    "total-value",
    "total-value-cur",
    "buyer-country",
    "buyer-city",                      # Auftraggeber-Stadt {'mul': ['Stadtname']}
    "contract-duration-end-date-lot",
    "contract-duration-end-date-part",
]


# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------

class TedBauNotice(BaseModel):
    """Normalisierte TED-Bau-Ausschreibung."""
    document_id:        str
    publication_date:   str | None = None
    title:              str | None = None
    description:        str | None = None
    cpv_code:           str | None = None
    estimated_value:    float | None = None
    currency:           str | None = None
    country:            str | None = None
    duration_end:       str | None = None
    duration_days:      int | None = None   # direkte Laufzeit wenn vorhanden
    notice_type:        str | None = None
    auftraggeber_ort:   str | None = None
    auftraggeber_plz:   str | None = None
    ausfuehrungsort:    str | None = None
    datenquelle:        str = "ted_bau"
    raw:                dict = {}


# ---------------------------------------------------------------------------
# API-Client
# ---------------------------------------------------------------------------

class TedBauApiClient:
    """
    TED-API-Client für Bau-Ausschreibungen (CPV 45*).
    Erbt die Request-Logik von fetch_ted.py, angepasst für Bau-Features.
    """

    def __init__(self, page_size: int = PAGE_SIZE_MAX, max_retries: int = 3, timeout: float = 30.0):
        self.page_size   = min(page_size, 250)
        self.max_retries = max_retries
        self.client      = httpx.Client(timeout=timeout)

    def _build_query(
        self,
        countries: list[str] | None = None,
        year: int | None = None,
        month: int | None = None,
    ) -> str:
        """Baut Expert-Query für Bau-CPV-Codes (PC=45*). month=1-12 für Monatsabfragen."""
        filter_teile = ["PC=45*"]

        if countries:
            laender = " OR ".join(f"buyer-country={c}" for c in countries)
            filter_teile.append(f"({laender})")

        if year and month:
            letzter_tag = calendar.monthrange(year, month)[1]
            filter_teile.append(
                f"PD>={year}{month:02d}01 AND PD<={year}{month:02d}{letzter_tag:02d}"
            )
        elif year:
            filter_teile.append(f"PD>={year}0101 AND PD<={year}1231")

        return " AND ".join(filter_teile)

    def _get_total_count(self, query: str) -> int:
        """Ermittelt Gesamttrefferzahl mit einer minimalen Anfrage."""
        payload = {
            "query":          query,
            "fields":         ["publication-number"],
            "page":           1,
            "limit":          1,
            "paginationMode": "PAGE_NUMBER",
        }
        try:
            response = self.client.post(TED_SEARCH_URL, json=payload)
            response.raise_for_status()
            return int(response.json().get("totalNoticeCount", 0))
        except Exception as exc:
            logger.warning("Trefferanzahl konnte nicht ermittelt werden: %s", exc)
            return 0

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
                    logger.warning("Rate-Limit – warte %d Sekunden.", warte)
                    time.sleep(warte)
                    continue

                if not response.is_success:
                    logger.error("HTTP %d: %s", response.status_code, response.text[:300])

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as exc:
                logger.error("HTTP-Fehler Seite %d (Versuch %d/%d): %s",
                             page, versuch + 1, self.max_retries, exc)
                if versuch < self.max_retries - 1:
                    time.sleep(2 ** versuch)
                else:
                    raise

            except httpx.RequestError as exc:
                logger.error("Verbindungsfehler Seite %d: %s", page, exc)
                if versuch < self.max_retries - 1:
                    time.sleep(2 ** versuch)
                else:
                    raise

        raise RuntimeError(f"Alle {self.max_retries} Versuche für Seite {page} fehlgeschlagen")

    @staticmethod
    def _text(feld, sprache: str = "deu") -> str | None:
        """Extrahiert Text aus mehrsprachigen eForms-Feldern."""
        if not feld:
            return None
        if isinstance(feld, str):
            return feld.strip() or None
        if isinstance(feld, list):
            return str(feld[0]).strip() if feld else None
        if isinstance(feld, dict):
            for lang in (sprache, "eng"):
                val = feld.get(lang)
                if val:
                    if isinstance(val, list):
                        return " ".join(str(v) for v in val).strip() or None
                    return str(val).strip() or None
            for val in feld.values():
                if val:
                    if isinstance(val, list):
                        return " ".join(str(v) for v in val).strip() or None
                    return str(val).strip() or None
        return None

    @staticmethod
    def _datum(datum_str: str | None) -> str | None:
        """ISO-8601 → YYYYMMDD."""
        if not datum_str:
            return None
        try:
            kern = datum_str[:10].replace("-", "")
            return kern if len(kern) == 8 and kern.isdigit() else None
        except Exception:
            return None

    @staticmethod
    def _wert(feld) -> float | None:
        """Numerischen Wert aus verschiedenen TED-Feldformaten lesen."""
        if feld is None:
            return None
        if isinstance(feld, dict):
            for key in ("number", "value", "amount"):
                val = feld.get(key)
                if val is not None:
                    try:
                        w = float(str(val).replace(",", ".").replace(" ", ""))
                        return w if w > 0 else None
                    except (ValueError, TypeError):
                        continue
            return None
        if isinstance(feld, (int, float)):
            return float(feld) if feld > 0 else None
        if isinstance(feld, list) and feld:
            return TedBauApiClient._wert(feld[0])
        try:
            w = float(str(feld).replace(",", ".").replace(" ", ""))
            return w if w > 0 else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _waehrung(feld) -> str | None:
        if not feld:
            return None
        if isinstance(feld, dict):
            val = feld.get("currency") or feld.get("cur") or feld.get("code")
            return str(val).upper().strip() if val else None
        val = feld[0] if isinstance(feld, list) else feld
        return str(val).upper().strip() or None

    @staticmethod
    def _extrahiere_stadt(feld) -> str | None:
        """
        Liest Stadtname aus buyer-city: {'mul': ['Stadtname']} oder ähnlich.
        """
        if not feld:
            return None
        if isinstance(feld, str):
            return feld.strip() or None
        if isinstance(feld, list):
            return str(feld[0]).strip() if feld else None
        if isinstance(feld, dict):
            # TED v3: {'mul': ['Stadtname']} oder {'deu': ['Stadt']}
            for schluessel in ("mul", "deu", "eng"):
                val = feld.get(schluessel)
                if val:
                    if isinstance(val, list):
                        return str(val[0]).strip() or None
                    return str(val).strip() or None
            # Erster verfügbarer Wert
            for val in feld.values():
                if val:
                    if isinstance(val, list):
                        return str(val[0]).strip() or None
                    return str(val).strip() or None
        return None

    def _parse_notice(self, raw: dict) -> TedBauNotice:
        """Wandelt ein rohes eForms-Objekt in ein TedBauNotice-Modell um."""
        titel = self._text(raw.get("notice-title"))
        beschreibung = (
            self._text(raw.get("description-lot"))
            or self._text(raw.get("description-part"))
            or self._text(raw.get("description-proc"))
        )

        cpv = (
            self._text(raw.get("main-classification-lot"))
            or self._text(raw.get("main-classification-part"))
        )

        wert = (
            self._wert(raw.get("estimated-value-lot"))
            or self._wert(raw.get("total-value"))
        )
        waehrung = (
            self._waehrung(raw.get("estimated-value-cur-lot"))
            or self._waehrung(raw.get("total-value-cur"))
        )

        land_raw = raw.get("buyer-country", [])
        land_3 = (land_raw[0] if isinstance(land_raw, list) and land_raw
                  else str(land_raw) if land_raw else None)
        land_2 = COUNTRY_3_TO_2.get(land_3 or "", land_3)

        laufzeit_ende = self._datum(
            (raw.get("contract-duration-end-date-lot") or [None])[0]
            if isinstance(raw.get("contract-duration-end-date-lot"), list)
            else raw.get("contract-duration-end-date-lot")
        ) or self._datum(
            (raw.get("contract-duration-end-date-part") or [None])[0]
            if isinstance(raw.get("contract-duration-end-date-part"), list)
            else raw.get("contract-duration-end-date-part")
        )

        # Auftraggeber-Stadt (buyer-city: {'mul': ['Stadtname']})
        ort = self._extrahiere_stadt(raw.get("buyer-city"))
        plz = None  # buyer-postal-code wird von TED v3 nicht unterstützt
        ausfuehrungsort = None  # place-performance-lot nicht unterstützt

        return TedBauNotice(
            document_id      = raw.get("publication-number", ""),
            publication_date = self._datum(raw.get("publication-date")),
            title            = titel,
            description      = beschreibung,
            cpv_code         = cpv,
            estimated_value  = wert,
            currency         = waehrung,
            country          = land_2,
            duration_end     = laufzeit_ende,
            duration_days    = None,  # Kein Direktfeld verfügbar; wird aus duration_end berechnet
            notice_type      = raw.get("notice-type"),
            auftraggeber_ort = ort,
            auftraggeber_plz = plz,
            ausfuehrungsort  = ausfuehrungsort,
            raw              = raw,
        )

    def _fetch_query(
        self,
        query: str,
        max_pages: int | None = None,
        nur_vergaben: bool = False,
    ) -> Iterator[TedBauNotice]:
        """Paginierter Abruf für eine einzelne Query (bleibt unter dem 15k-Fenster)."""
        logger.info("TED-Bau-Abfrage: %s", query)
        page = 1
        total_geladen = 0

        while True:
            logger.info("Lade Seite %d...", page)
            data    = self._request_page(query, page)
            total   = data.get("totalNoticeCount", 0)
            notices = data.get("notices", [])

            if not notices:
                logger.info("Keine weiteren Ausschreibungen. Gesamt: %d", total_geladen)
                break

            seite_geliefert = 0
            for raw_notice in notices:
                notice = self._parse_notice(raw_notice)
                if nur_vergaben:
                    nt = (notice.notice_type or "").lower()
                    if not (nt.startswith("can") or nt == "veat"):
                        continue
                yield notice
                total_geladen += 1
                seite_geliefert += 1

            logger.info("Seite %d: %d/%d behalten (%d gesamt)",
                        page, seite_geliefert, len(notices), total_geladen)

            if max_pages and page >= max_pages:
                break

            naechstes_fenster = (page + 1) * self.page_size
            if naechstes_fenster > 14_900:
                logger.warning(
                    "15k-Fenstergrenze erreicht (Seite %d, Fenster %d). Abfrage beendet.",
                    page, naechstes_fenster,
                )
                break

            page += 1

    def fetch_notices(
        self,
        countries: list[str] | None = None,
        year: int | None = None,
        max_pages: int | None = None,
        nur_vergaben: bool = False,
    ) -> Iterator[TedBauNotice]:
        """
        Generator: Liefert alle Bau-Ausschreibungen.
        Bei Jahresabfragen mit >14.900 Treffern wird automatisch in
        Monatsabfragen aufgeteilt (TED-API-Limit: Seite × Limit ≤ 15.000).
        """
        if max_pages:
            # Testmodus: direkte jährliche Abfrage ohne Vorprüfung
            yield from self._fetch_query(
                self._build_query(countries=countries, year=year),
                max_pages=max_pages,
                nur_vergaben=nur_vergaben,
            )
            return

        query_jahr = self._build_query(countries=countries, year=year)
        total = self._get_total_count(query_jahr)
        logger.info("Jahresabfrage '%s': %d Treffer gesamt.", query_jahr, total)

        if total <= 14_900:
            yield from self._fetch_query(query_jahr, nur_vergaben=nur_vergaben)
        else:
            logger.info(
                "Überschreitet 15k-Limit (%d) – wechsle zu Monatsabfragen.", total
            )
            for monat in range(1, 13):
                query_monat = self._build_query(
                    countries=countries, year=year, month=monat
                )
                monat_total = self._get_total_count(query_monat)
                logger.info("  Monat %02d/%d: %d Treffer", monat, year or 0, monat_total)
                if monat_total == 0:
                    continue
                if monat_total > 14_900:
                    logger.warning(
                        "Monat %02d/%d überschreitet ebenfalls 15k (%d) – "
                        "Abfrage wird teilweise abgeschnitten!",
                        monat, year or 0, monat_total,
                    )
                yield from self._fetch_query(query_monat, nur_vergaben=nur_vergaben)

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ---------------------------------------------------------------------------
# Convenience-Funktionen
# ---------------------------------------------------------------------------

def fetch_and_save_bau(
    output_path: Path | str | None = None,
    countries: list[str] | None = None,
    year: int | None = None,
    max_pages: int | None = None,
    nur_vergaben: bool = False,
) -> int:
    """Ruft Bau-Ausschreibungen ab und speichert als JSON Lines."""
    if output_path is None:
        suffix = f"_{year}" if year else ""
        prefix = "raw_notices_bau_awards" if nur_vergaben else "raw_notices_bau"
        output_path = RAW_DATA_DIR / f"{prefix}{suffix}.jsonl"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    gespeichert = 0
    with TedBauApiClient() as client, output_path.open("w", encoding="utf-8") as f:
        for notice in client.fetch_notices(
            countries=countries, year=year,
            max_pages=max_pages, nur_vergaben=nur_vergaben,
        ):
            # raw-Feld nicht persistieren (zu groß)
            data = notice.model_dump(exclude={"raw"})
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
            gespeichert += 1

    logger.info("Gespeichert: %d Bau-Bekanntmachungen → %s", gespeichert, output_path)
    return gespeichert


def fetch_dach_bau_alle_jahre(
    output_dir: Path | str = RAW_DATA_DIR,
    jahre: list[int] = JAHRE_DEFAULT,
    max_pages: int | None = None,
    nur_vergaben: bool = True,
) -> dict[int, int]:
    """
    Ruft DACH Bau-Ausschreibungen für mehrere Jahre ab.
    Standard: CAN (Vergabebekanntmachungen) – enthalten stets Auftragswert.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ergebnisse: dict[int, int] = {}

    for jahr in jahre:
        suffix = "awards" if nur_vergaben else "notices"
        pfad = output_dir / f"raw_notices_bau_{suffix}_{jahr}.jsonl"
        logger.info("=== Bau-Jahrgang %d → %s ===", jahr, pfad)
        anzahl = fetch_and_save_bau(
            output_path=pfad,
            countries=DACH_QUERY_CODES,
            year=jahr,
            max_pages=max_pages,
            nur_vergaben=nur_vergaben,
        )
        ergebnisse[jahr] = anzahl
        logger.info("Jahrgang %d: %d Bau-Bekanntmachungen gespeichert.", jahr, anzahl)

    return ergebnisse


def zeige_statistik(ergebnisse: dict[int, int], pfade: list[Path]) -> None:
    """Ausgabe von Abruf-Statistiken."""
    import collections

    gesamt = sum(ergebnisse.values())

    print("\n" + "═" * 52)
    print("  TED Bau-Abruf – Ergebnis")
    print("═" * 52)

    print("\n  Projekte pro Jahr:")
    for jahr, n in sorted(ergebnisse.items()):
        print(f"    {jahr}:  {n:>8,}")
    print(f"    {'Gesamt':}  {gesamt:>8,}")

    # CPV-Verteilung und Vollständigkeit aus gespeicherten Dateien
    n_mit_budget = 0
    n_mit_dauer  = 0
    n_mit_ort    = 0
    cpv_gruppen: dict[str, int] = collections.defaultdict(int)
    laender: dict[str, int] = collections.defaultdict(int)

    for pfad in pfade:
        if not pfad.exists():
            continue
        with pfad.open(encoding="utf-8") as f:
            for zeile in f:
                try:
                    rec = json.loads(zeile)
                except json.JSONDecodeError:
                    continue
                if rec.get("estimated_value"):
                    n_mit_budget += 1
                if rec.get("duration_days") or rec.get("duration_end"):
                    n_mit_dauer += 1
                if rec.get("auftraggeber_ort") or rec.get("auftraggeber_plz"):
                    n_mit_ort += 1
                cpv = str(rec.get("cpv_code") or "")[:4]
                if cpv:
                    cpv_gruppen[cpv] += 1
                land = rec.get("country") or "?"
                laender[land] += 1

    if gesamt > 0:
        print(f"\n  Vollständigkeit:")
        print(f"    Mit Budget:    {n_mit_budget:>8,}  ({100*n_mit_budget/gesamt:.0f}%)")
        print(f"    Mit Laufzeit:  {n_mit_dauer:>8,}  ({100*n_mit_dauer/gesamt:.0f}%)")
        print(f"    Mit Ort/PLZ:   {n_mit_ort:>8,}  ({100*n_mit_ort/gesamt:.0f}%)")

    if cpv_gruppen:
        print(f"\n  CPV-Hauptgruppen (Top 8, 4-stellig):")
        for cpv, n in sorted(cpv_gruppen.items(), key=lambda x: -x[1])[:8]:
            print(f"    {cpv}xxxx  {n:>7,}")

    if laender:
        print(f"\n  Top Länder:")
        for land, n in sorted(laender.items(), key=lambda x: -x[1])[:5]:
            print(f"    {land:<6}  {n:>7,}")

    print("═" * 52 + "\n")


# ---------------------------------------------------------------------------
# Direkt ausführbar
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="TED Bau-Daten abrufen (CPV 45*)")
    parser.add_argument(
        "--modus", choices=["cn", "can", "beides"], default="can",
        help="cn=Ausschreibungen, can=Vergaben (haben stets Budget), beides=beide",
    )
    parser.add_argument(
        "--jahre", nargs="+", type=int, default=JAHRE_DEFAULT,
        help="Jahrgänge (Standard: 2020–2024)",
    )
    parser.add_argument(
        "--max-seiten", type=int, default=None,
        help="Max. Seitenanzahl pro Jahr (None=alle; für Tests z.B. 5)",
    )
    args = parser.parse_args()

    ergebnisse_cn:  dict[int, int] = {}
    ergebnisse_can: dict[int, int] = {}
    alle_pfade: list[Path] = []

    if args.modus in ("cn", "beides"):
        for jahr in args.jahre:
            pfad = RAW_DATA_DIR / f"raw_notices_bau_notices_{jahr}.jsonl"
            anzahl = fetch_and_save_bau(
                output_path=pfad,
                countries=DACH_QUERY_CODES,
                year=jahr,
                max_pages=args.max_seiten,
                nur_vergaben=False,
            )
            ergebnisse_cn[jahr] = anzahl
            alle_pfade.append(pfad)

    if args.modus in ("can", "beides"):
        for jahr in args.jahre:
            pfad = RAW_DATA_DIR / f"raw_notices_bau_awards_{jahr}.jsonl"
            anzahl = fetch_and_save_bau(
                output_path=pfad,
                countries=DACH_QUERY_CODES,
                year=jahr,
                max_pages=args.max_seiten,
                nur_vergaben=True,
            )
            ergebnisse_can[jahr] = anzahl
            alle_pfade.append(pfad)

    gesamt_ergebnisse = {**ergebnisse_cn, **ergebnisse_can}
    # Summiere pro Jahr wenn beide Modi
    if ergebnisse_cn and ergebnisse_can:
        for j in set(list(ergebnisse_cn.keys()) + list(ergebnisse_can.keys())):
            gesamt_ergebnisse[j] = ergebnisse_cn.get(j, 0) + ergebnisse_can.get(j, 0)

    zeige_statistik(gesamt_ergebnisse, alle_pfade)
