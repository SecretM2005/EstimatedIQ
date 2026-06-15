"""
IndieHackers Products Connector.

Scraped von öffentlichen IndieHackers-Produktseiten (Next.js __NEXT_DATA__).
Nur Produkte mit erkennbarer "time to build"-Angabe in der Beschreibung
werden gespeichert – nur diese haben ein gültiges dauer_tage für das Modell.

Ausgabe: data/raw_indiehackers.jsonl (kompatibel mit preprocess.py)

Verwendung:
  python -m estimateiq.data.fetch_indiehackers
  python -m estimateiq.data.fetch_indiehackers --max-seiten 5 --max-produkte 100
"""

import json
import logging
import re
import time
from html.parser import HTMLParser
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

OUTPUT_FILE  = Path("data") / "raw_indiehackers.jsonl"
IH_BASE_URL  = "https://www.indiehackers.com"
MAX_SEITEN   = 20
MAX_PRODUKTE = 500

# Regex-Muster für "time to build"-Angaben im Text
_ZEITDAUER_MUSTER: list[str] = [
    r"(?:built?|developed?|created?)\s+(?:it\s+|this\s+)?in\s+(\d+(?:\.\d+)?)\s*(month|week|day|year)s?",
    r"(\d+(?:\.\d+)?)\s*(month|week|day|year)s?\s+(?:to\s+build|to\s+develop|to\s+launch|to\s+create|to\s+ship)",
    r"time\s+to\s+(?:build|launch|market|release|ship)[\s:–-]+(\d+(?:\.\d+)?)\s*(month|week|day|year)s?",
    r"(?:took|take|takes)\s+(?:me\s+|us\s+)?(\d+(?:\.\d+)?)\s*(month|week|day|year)s?",
    r"(?:after|within|in)\s+(\d+(?:\.\d+)?)\s*(month|week|day|year)s?\s+of\s+(?:work|building|development|coding)",
    r"launched?\s+(?:it\s+)?after\s+(\d+(?:\.\d+)?)\s*(month|week|day|year)s?",
    r"(\d+)[-\s](month|week|day|year)\s+(?:side\s+)?project",
]
_EINHEIT_ZU_TAGE: dict[str, float] = {
    "day":   1.0,
    "week":  7.0,
    "month": 30.44,
    "year":  365.0,
}


def _extrahiere_dauer(text: str) -> int | None:
    """Versucht 'time to build' aus freiem Text zu extrahieren. Gibt Tage zurück oder None."""
    text_lower = (text or "").lower()
    for muster in _ZEITDAUER_MUSTER:
        treffer = re.search(muster, text_lower)
        if treffer:
            try:
                zahl   = float(treffer.group(1))
                einheit = treffer.group(2).rstrip("s")
                tage   = round(zahl * _EINHEIT_ZU_TAGE.get(einheit, 30.44))
                if 7 <= tage <= 730:
                    return tage
            except (IndexError, ValueError):
                pass
    return None


# ---------------------------------------------------------------------------
# HTML-Parser für Next.js __NEXT_DATA__
# ---------------------------------------------------------------------------

class _NextDataExtractor(HTMLParser):
    """Extrahiert __NEXT_DATA__ JSON aus Next.js-gerenderten HTML-Seiten."""

    def __init__(self):
        super().__init__()
        self._in_block = False
        self.data: str = ""

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "script":
            attrs_dict = dict(attrs)
            if attrs_dict.get("id") == "__NEXT_DATA__":
                self._in_block = True

    def handle_data(self, data: str) -> None:
        if self._in_block:
            self.data += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_block:
            self._in_block = False


# ---------------------------------------------------------------------------
# HTTP-Hilfsfunktionen
# ---------------------------------------------------------------------------

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; EstimateIQ-ResearchBot/1.0; "
        "+https://github.com/secretm2005/estimatediq)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _lade_seite(client: httpx.Client, url: str, max_versuche: int = 3) -> str | None:
    """Lädt eine URL mit Retry-Logik und gibt HTML zurück oder None."""
    for versuch in range(max_versuche):
        try:
            resp = client.get(url, timeout=30.0)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (429, 503):
                warte = 2 ** (versuch + 2)
                logger.warning("[IH] HTTP %d – warte %d s.", resp.status_code, warte)
                time.sleep(warte)
            else:
                logger.warning("[IH] HTTP %d für %s", resp.status_code, url[:80])
                return None
        except Exception as exc:
            warte = 2 ** versuch
            logger.warning("[IH] Fehler (Versuch %d/%d): %s – warte %d s.",
                           versuch + 1, max_versuche, exc, warte)
            if versuch < max_versuche - 1:
                time.sleep(warte)
    return None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _extrahiere_next_data(html: str) -> dict | None:
    """Parst __NEXT_DATA__ aus Next.js-HTML und gibt den Props-Dict zurück."""
    parser = _NextDataExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass

    if not parser.data:
        return None

    try:
        return json.loads(parser.data)
    except json.JSONDecodeError:
        return None


def _finde_produkte(next_data: dict) -> list[dict]:
    """Sucht Produktlisten in verschiedenen möglichen Next.js-Datenstrukturen."""
    props = next_data.get("props", {}).get("pageProps", {})

    for schluessel in ["products", "initialProducts", "items"]:
        kandidat = props.get(schluessel)
        if isinstance(kandidat, list) and kandidat:
            return kandidat

    # Tiefere Suche in data-Unterobjekten
    data = props.get("data", {})
    if isinstance(data, dict):
        for schluessel in ["products", "items"]:
            kandidat = data.get(schluessel)
            if isinstance(kandidat, list) and kandidat:
                return kandidat

    return []


def _produkt_zu_datensatz(produkt: dict) -> dict | None:
    """Konvertiert ein IndieHackers-Produkt-Objekt in unser JSONL-Schema."""
    slug = (produkt.get("slug") or produkt.get("id") or "").strip()
    name = (produkt.get("name") or produkt.get("title") or "").strip()

    if not slug or not name:
        return None

    # Beschreibungstext aus verschiedenen möglichen Feldern
    teile: list[str] = []
    for key in ["tagline", "description", "about", "shortDescription", "summary", "storyPreview"]:
        val = (produkt.get(key) or "").strip()
        if val and val not in teile:
            teile.append(val)
    beschreibung = " ".join(teile)

    if len(beschreibung) < 20:
        return None

    # Laufzeit: zuerst explizites Feld, dann Freitext
    dauer_tage: int | None = None
    for key in ["timeToLaunch", "timeToMvp", "buildTime", "timeToFirstRevenue"]:
        val = produkt.get(key)
        if val:
            d = _extrahiere_dauer(str(val))
            if d:
                dauer_tage = d
                break

    if dauer_tage is None:
        dauer_tage = _extrahiere_dauer(beschreibung)

    if dauer_tage is None:
        return None  # Nur Produkte mit bekannter Bauzeit verwenden

    # Technologie-Tags
    tags = produkt.get("tags") or produkt.get("technologies") or produkt.get("stack") or []
    if isinstance(tags, list):
        technologie = ", ".join(str(t).strip() for t in tags[:6] if t)
    elif isinstance(tags, str):
        technologie = tags
    else:
        technologie = ""

    # Publikationsdatum → YYYYMMDD
    datum_roh = (
        produkt.get("launchDate")
        or produkt.get("createdAt")
        or produkt.get("foundedDate")
        or ""
    )
    pub_date = "20230101"
    try:
        datum_clean = str(datum_roh)[:10].replace("-", "")
        if len(datum_clean) == 8 and datum_clean.isdigit():
            pub_date = datum_clean
    except Exception:
        pass

    return {
        "document_id":       f"ih_{slug}",
        "publication_date":  pub_date,
        "title":             f"IndieHackers: {name}",
        "description":       beschreibung,
        "cpv_code":          "72400000",   # Internet- & Cloud-Dienste (Standardwert für SaaS)
        "estimated_value":   None,
        "currency":          "EUR",
        "country":           "US",
        "duration_end":      None,
        "dauer_tage_direkt": dauer_tage,
        "notice_type":       "indiehackers",
        "datenquelle":       "indiehackers",
        "technologie":       technologie,
        "raw":               {},
    }


# ---------------------------------------------------------------------------
# Haupt-Exportfunktion
# ---------------------------------------------------------------------------

def fetch_indiehackers_data(
    output_path: Path = OUTPUT_FILE,
    max_seiten: int = MAX_SEITEN,
    max_produkte: int = MAX_PRODUKTE,
) -> int:
    """
    Scraped IndieHackers-Produktseiten und speichert Datensätze mit
    erkennbarer 'time to build'-Angabe als JSONL.

    Args:
        output_path:   Ausgabedatei (data/raw_indiehackers.jsonl)
        max_seiten:    Maximale Seitenanzahl (Paginierung)
        max_produkte:  Maximale Gesamtanzahl Datensätze

    Returns:
        Anzahl gespeicherter Datensätze
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    alle_datensaetze: list[dict] = []
    gesehene_ids: set[str]       = set()

    with httpx.Client(headers=_HEADERS, follow_redirects=True) as client:
        for seite in range(max_seiten):
            if len(alle_datensaetze) >= max_produkte:
                break

            url  = f"{IH_BASE_URL}/products?page={seite}"
            logger.info("[IH] Lade Seite %d: %s", seite, url)

            html = _lade_seite(client, url)
            if not html:
                logger.warning("[IH] Seite %d konnte nicht geladen werden – Abbruch.", seite)
                break

            next_data = _extrahiere_next_data(html)
            if not next_data:
                logger.warning("[IH] Seite %d: Kein __NEXT_DATA__ gefunden – Abbruch.", seite)
                break

            produkte_roh = _finde_produkte(next_data)
            if not produkte_roh:
                logger.info("[IH] Seite %d: Keine weiteren Produkte → Ende.", seite)
                break

            neu_diese_seite = 0
            for produkt in produkte_roh:
                doc_id = f"ih_{(produkt.get('slug') or produkt.get('id') or '').strip()}"
                if not doc_id or doc_id == "ih_" or doc_id in gesehene_ids:
                    continue
                gesehene_ids.add(doc_id)

                datensatz = _produkt_zu_datensatz(produkt)
                if datensatz is None:
                    continue

                alle_datensaetze.append(datensatz)
                neu_diese_seite += 1

                if len(alle_datensaetze) >= max_produkte:
                    break

            logger.info("[IH] Seite %d: %d neue Datensätze (%d gesamt).",
                        seite, neu_diese_seite, len(alle_datensaetze))
            time.sleep(2.0)

    with output_path.open("w", encoding="utf-8") as f:
        for ds in alle_datensaetze:
            f.write(json.dumps(ds, ensure_ascii=False) + "\n")

    logger.info("[IH] Gesamt: %d Datensätze → %s", len(alle_datensaetze), output_path)
    return len(alle_datensaetze)


# ---------------------------------------------------------------------------
# Direkt ausführbar
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="IndieHackers-Produktdaten abrufen")
    parser.add_argument("--max-seiten",   type=int, default=MAX_SEITEN,
                        help=f"Maximale Seitenanzahl (Standard: {MAX_SEITEN})")
    parser.add_argument("--max-produkte", type=int, default=MAX_PRODUKTE,
                        help=f"Maximale Datensätze (Standard: {MAX_PRODUKTE})")
    args = parser.parse_args()

    n = fetch_indiehackers_data(max_seiten=args.max_seiten, max_produkte=args.max_produkte)
    print(f"\nIndieHackers-Datensätze gespeichert: {n}")
