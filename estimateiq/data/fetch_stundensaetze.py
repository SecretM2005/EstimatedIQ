"""
Automatischer Fetch von Handwerks-Stundensätzen aus zwei Quellen:

  1. BA Entgeltatlas (Bundesagentur für Arbeit)
     Brutto-Medianlohn je Beruf + Bundesland → Stundenverrechnungssatz
     Docs: github.com/bundesAPI/entgeltatlas-api

  2. Destatis GENESIS
     Baupreisindex je Bundesland → regionaler Korrekturfaktor

Output: data/stundensaetze.json
  Wird von kalkulator.py via get_stundensatz() genutzt.

Ausführung:
    python -m estimateiq.data.fetch_stundensaetze        # einmalig
    python -m estimateiq.data.fetch_stundensaetze --force # Neuabruf erzwingen
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# ── Pfade ─────────────────────────────────────────────────────────────────────
AUSGABE_PFAD = Path("data/stundensaetze.json")

# ── BA Entgeltatlas ───────────────────────────────────────────────────────────
_BA_TOKEN_URL = "https://rest.arbeitsagentur.de/oauth/gettoken_cc"
_BA_BASE_URL  = "https://rest.arbeitsagentur.de/infosysbub/entgeltatlas/pc/v1"

_BA_CLIENT_ID     = os.getenv("BA_CLIENT_ID",     "c003a37f-024f-462a-b36d-b001be4cd24a")
_BA_CLIENT_SECRET = os.getenv("BA_CLIENT_SECRET", "32a39620-32b3-4307-9aa1-511e3d7f48a8")

# KldB-2010-Schlüssel → Gewerk
KLDB_CODES: dict[str, str] = {
    "Maler":      "51302",   # Maler/Lackierer Betrieb
    "Fliesen":    "51402",   # Fliesen-/Plattenleger
    "Sanitär":    "34212",   # Klempner/Sanitär/Heizung/Klima
    "Elektro":    "26302",   # Elektroniker Energie- und Gebäudetechnik
    "Trockenbau": "51202",   # Trockenbauer/Ausbau
    "Hochbau":    "51112",   # Maurer/Betonbauer
    "Boden":      "51422",   # Bodenleger
}

# AGS-Codes der Bundesländer (Amtlicher Gemeindeschlüssel, 2 Stellen)
BUNDESLAND_CODES: dict[str, str] = {
    "DE-BY": "09",   # Bayern
    "DE-BW": "08",   # Baden-Württemberg
    "DE-HH": "02",   # Hamburg
    "DE-HE": "06",   # Hessen
    "DE-NW": "05",   # Nordrhein-Westfalen
    "DE-BE": "11",   # Berlin
    "DE-NI": "03",   # Niedersachsen   → fließt in DE-sonstige
    "DE-SN": "14",   # Sachsen         → fließt in DE-sonstige
    "DE-TH": "16",   # Thüringen       → fließt in DE-sonstige
}
# Regionsschlüssel "0" = Bundesweit (Fallback)
_BUNDESWEIT = "0"

# Verrechnungsfaktor: Stundensatz = (Bruttolohn/Monat × 1.21 / 160) × Faktor
# Umfasst: Gemeinkosten, Gewinn, Wagnis, Maschinenkosten, Materialaufschlag
VERRECHNUNGSFAKTOREN: dict[str, float] = {
    "Maler":      2.8,
    "Fliesen":    3.0,
    "Sanitär":    3.2,
    "Elektro":    3.1,
    "Trockenbau": 2.9,
    "Hochbau":    2.8,
    "Boden":      2.7,
}

# ── Destatis GENESIS ──────────────────────────────────────────────────────────
_DESTATIS_URL = (
    "https://www-genesis.destatis.de/api/2020/data/table"
    "?name=61111-0003&format=JSON&username=GAST&password=GAST"
    "&startyear=2023&endyear=2024&regionalvariable=DINSG&regionalkey=DG"
)
# Tabelle 61111-0003: Baupreisindizes für Wohngebäude nach Bundesland
_DESTATIS_BL_URL = (
    "https://www-genesis.destatis.de/api/2020/data/table"
    "?name=61111-0002&format=JSON&username=GAST&password=GAST"
    "&startyear=2023&endyear=2024"
)

# Vorab-berechnete regionale Baukostenfaktoren (Fallback wenn Destatis nicht verfügbar)
# Quelle: BBSR Baukostenindex 2023, normiert auf DE = 1.00
_REGIONAL_FAKTOR_FALLBACK: dict[str, float] = {
    "DE-BY": 1.185,
    "DE-BW": 1.080,
    "DE-HH": 1.100,
    "DE-HE": 1.050,
    "DE-NW": 1.012,
    "DE-BE": 1.058,
    "DE-NI": 0.980,
    "DE-SN": 0.921,
    "DE-TH": 0.915,
    "DE-sonstige": 1.000,
    "AT":    1.080,
    "CH":    1.250,
}

# ── Handwerk.cloud Referenzwerte 2026 (für Vergleich) ────────────────────────
from estimateiq.data.stundensaetze import STUNDENSAETZE as _REFERENZ_SAETZE


# ── HTTP-Session mit Retry ────────────────────────────────────────────────────

def _neue_session(timeout: int = 15) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=1.5,   # 1.5s, 3s, 6s, 12s
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    session.request = lambda method, url, **kw: requests.Session.request(
        session, method, url, timeout=timeout, **kw
    )
    return session


# ── BA Entgeltatlas ───────────────────────────────────────────────────────────

class _TokenCache:
    token:   str  = ""
    expires: float = 0.0

    @classmethod
    def gueltig(cls) -> bool:
        return bool(cls.token) and time.time() < cls.expires - 30


def _hole_ba_token(session: requests.Session) -> str:
    if _TokenCache.gueltig():
        return _TokenCache.token

    logger.debug("[BA] Hole OAuth-Token …")
    resp = session.post(
        _BA_TOKEN_URL,
        data={
            "client_id":     _BA_CLIENT_ID,
            "client_secret": _BA_CLIENT_SECRET,
            "grant_type":    "client_credentials",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    daten = resp.json()

    _TokenCache.token   = daten["access_token"]
    _TokenCache.expires = time.time() + float(daten.get("expires_in", 3600))
    logger.debug("[BA] Token gültig für %.0fs", daten.get("expires_in", 3600))
    return _TokenCache.token


def _hole_ba_entgelt(
    session:   requests.Session,
    kldb_code: str,
    region_id: str,
) -> float | None:
    """
    Ruft den Brutto-Median-Monatslohn (€) für einen KldB-Code + Region ab.
    Gibt None zurück wenn die Abfrage fehlschlägt.
    """
    token = _hole_ba_token(session)
    url   = f"{_BA_BASE_URL}/entgelte/{kldb_code}"
    params: dict[str, Any] = {"a": 1, "b": 1}
    if region_id and region_id != _BUNDESWEIT:
        params["r"] = region_id

    try:
        resp = session.get(
            url,
            params=params,
            headers={"OAuthAccessToken": token},
        )
        if resp.status_code == 404:
            logger.debug("[BA] Kein Datensatz für KldB=%s r=%s", kldb_code, region_id)
            return None
        resp.raise_for_status()
        daten = resp.json()

        # Verschiedene mögliche Response-Strukturen abfangen
        for pfad in [
            ("gehalt", "brutto", "median"),
            ("entgelt", "brutto", "p50"),
            ("median",),
            ("brutto", "median"),
        ]:
            node = daten
            for schluessel in pfad:
                node = node.get(schluessel) if isinstance(node, dict) else None
                if node is None:
                    break
            if isinstance(node, (int, float)) and node > 0:
                return float(node)

        logger.warning("[BA] Unbekanntes Response-Format: %s", list(daten.keys()))
        return None

    except requests.exceptions.RequestException as exc:
        logger.warning("[BA] Fehler KldB=%s r=%s: %s", kldb_code, region_id, exc)
        return None


def _ba_regionen(session: requests.Session) -> dict[str, str]:
    """Gibt {Name: RegionID} für alle Bundesländer zurück."""
    token = _hole_ba_token(session)
    try:
        resp = session.get(
            f"{_BA_BASE_URL}/regionen",
            headers={"OAuthAccessToken": token},
        )
        resp.raise_for_status()
        regionen: dict[str, str] = {}
        for eintrag in resp.json():
            name = eintrag.get("label") or eintrag.get("name") or ""
            rid  = str(eintrag.get("id") or eintrag.get("schluessel") or "")
            if name and rid:
                regionen[name] = rid
        logger.info("[BA] %d Regionen geladen.", len(regionen))
        return regionen
    except Exception as exc:
        logger.warning("[BA] Regionen-Abruf fehlgeschlagen: %s – nutze Fallback.", exc)
        return {}


def _berechne_satz(median_brutto_monat: float, gewerk: str) -> float:
    """
    Stundenverrechnungssatz aus Brutto-Medianlohn.

    Formel:
      AG-Kosten/Monat = brutto × 1.21  (+ Sozialabgaben AG-Anteil)
      AG-Kosten/h     = AG-Kosten / 160
      Stundensatz     = AG-Kosten/h × Verrechnungsfaktor
    """
    ag_kosten_monat = median_brutto_monat * 1.21
    ag_kosten_h     = ag_kosten_monat / 160.0
    faktor          = VERRECHNUNGSFAKTOREN.get(gewerk, 3.0)
    return round(ag_kosten_h * faktor, 1)


def _fetch_ba_alle(session: requests.Session) -> dict[str, dict[str, dict]]:
    """
    Holt Stundensätze für alle Gewerke × Bundesländer vom BA Entgeltatlas.

    Returns:
        {gewerk: {region_key: {"satz": float, "brutto_median": float, ...}}}
    """
    logger.info("[BA] Starte Entgeltatlas-Abruf …")

    # Versuche dynamische Regionen-ID-Zuordnung; Fallback auf BUNDESLAND_CODES
    dyn_regionen = _ba_regionen(session)
    # Normalize: AGS-Code → Region-Key
    ags_zu_key = {v: k for k, v in BUNDESLAND_CODES.items()}

    ergebnis: dict[str, dict[str, dict]] = {}

    for gewerk, kldb in KLDB_CODES.items():
        ergebnis[gewerk] = {}

        # Bundesweit als Baseline
        median_bund = _hole_ba_entgelt(session, kldb, _BUNDESWEIT)
        if median_bund:
            satz_bund = _berechne_satz(median_bund, gewerk)
            ergebnis[gewerk]["DE-gesamt"] = {
                "satz":          satz_bund,
                "brutto_median": median_bund,
                "quelle":        "ba_entgeltatlas",
            }

        for region_key, ags in BUNDESLAND_CODES.items():
            median = _hole_ba_entgelt(session, kldb, ags)
            if median is None and median_bund:
                # Schätze aus Bundeswert + regionalem Faktor
                faktor  = _REGIONAL_FAKTOR_FALLBACK.get(region_key, 1.0)
                median  = median_bund * faktor
                quelle  = "ba_entgeltatlas_interpoliert"
            elif median is None:
                logger.warning("[BA] Kein Wert für %s / %s – überspringe.", gewerk, region_key)
                continue
            else:
                quelle = "ba_entgeltatlas"

            satz = _berechne_satz(median, gewerk)
            ergebnis[gewerk][region_key] = {
                "satz":          round(satz, 1),
                "brutto_median": round(median, 0),
                "quelle":        f"{quelle}_{date.today().year}",
            }
            logger.debug("[BA] %-12s %-8s median=%5.0f€  satz=%5.1f€/h",
                         gewerk, region_key, median, satz)

        # DE-sonstige = gewichteter Schnitt der restlichen Bundesländer
        ni = ergebnis[gewerk].get("DE-NI", {}).get("brutto_median")
        sn = ergebnis[gewerk].get("DE-SN", {}).get("brutto_median")
        th = ergebnis[gewerk].get("DE-TH", {}).get("brutto_median")
        werte = [v for v in [ni, sn, th] if v]
        if werte:
            median_sonstige = sum(werte) / len(werte)
            ergebnis[gewerk]["DE-sonstige"] = {
                "satz":          round(_berechne_satz(median_sonstige, gewerk), 1),
                "brutto_median": round(median_sonstige, 0),
                "quelle":        f"ba_entgeltatlas_gemittelt_{date.today().year}",
            }
        elif median_bund:
            ergebnis[gewerk]["DE-sonstige"] = {
                "satz":          round(_berechne_satz(median_bund, gewerk), 1),
                "brutto_median": round(median_bund, 0),
                "quelle":        "ba_entgeltatlas_bundesweit_fallback",
            }

    logger.info("[BA] Abgeschlossen: %d Gewerke.", len(ergebnis))
    return ergebnis


# ── Destatis GENESIS ──────────────────────────────────────────────────────────

def _fetch_destatis_regionalfaktoren(session: requests.Session) -> dict[str, float]:
    """
    Lädt Baupreisindizes von Destatis GENESIS.
    Normiert auf Bundesschnitt = 1.0.
    Gibt Fallback-Dict zurück bei Fehler.
    """
    logger.info("[Destatis] Lade Baupreisindizes …")
    try:
        resp = session.get(_DESTATIS_BL_URL, timeout=20)
        if resp.status_code != 200:
            raise requests.exceptions.HTTPError(
                f"Status {resp.status_code}", response=resp
            )
        daten = resp.json()

        # GENESIS-Format: data.content enthält Zeitreihen
        content = daten.get("Object", {}) or daten.get("data", {}) or {}
        indizes: dict[str, float] = {}

        # Bundesland-Codes in AGS-Format
        _ags_zu_key = {v: k for k, v in BUNDESLAND_CODES.items()}

        # Iteriere über Datenpunkte
        for zeile in _genesis_zeilen(content):
            bl_code = zeile.get("regionalkey", "")[:2]
            wert    = zeile.get("value")
            if bl_code and wert and isinstance(wert, (int, float)) and wert > 0:
                region_key = _ags_zu_key.get(f"0{bl_code}" if len(bl_code) == 1
                                              else bl_code)
                if region_key:
                    indizes[region_key] = float(wert)

        if len(indizes) >= 5:
            bund_schnitt = sum(indizes.values()) / len(indizes)
            normiert     = {k: round(v / bund_schnitt, 4) for k, v in indizes.items()}
            logger.info("[Destatis] %d Bundesland-Indizes geladen, "
                        "normiert auf 1.0.", len(normiert))
            return normiert

        logger.warning("[Destatis] Zu wenige Datenpunkte (%d) – nutze Fallback.",
                       len(indizes))

    except Exception as exc:
        logger.warning("[Destatis] Abruf fehlgeschlagen: %s – nutze BBSR-Fallback.", exc)

    return dict(_REGIONAL_FAKTOR_FALLBACK)


def _genesis_zeilen(content: Any) -> list[dict]:
    """Extrahiert Datenpunkte aus GENESIS-Response-Struktur."""
    if isinstance(content, list):
        return content
    if isinstance(content, dict):
        for key in ("data", "rows", "Werte", "zeitreihen"):
            sub = content.get(key)
            if isinstance(sub, list):
                return sub
    return []


# ── Update-Orchestrierung ─────────────────────────────────────────────────────

def update_stundensaetze(
    ausgabe_pfad: Path = AUSGABE_PFAD,
    force: bool = False,
) -> dict:
    """
    Holt aktuelle Stundensätze und schreibt data/stundensaetze.json.

    Args:
        ausgabe_pfad: Zieldatei
        force:        Auch abrufen wenn Daten jünger als 30 Tage

    Returns:
        dict mit Ergebnissen und Änderungsprotokoll
    """
    ausgabe_pfad = Path(ausgabe_pfad)
    ausgabe_pfad.parent.mkdir(parents=True, exist_ok=True)

    # Prüfe ob Update nötig
    if not force and ausgabe_pfad.exists():
        alt = json.loads(ausgabe_pfad.read_text(encoding="utf-8"))
        aktualisiert = alt.get("aktualisiert", "")
        if aktualisiert:
            alter_tage = (date.today() - date.fromisoformat(aktualisiert)).days
            if alter_tage < 30:
                logger.info("[Update] Daten sind %d Tage alt – kein Update nötig "
                            "(--force zum Erzwingen).", alter_tage)
                return alt

    session = _neue_session()

    # Lade alte Daten für Änderungsprotokoll
    alte_daten: dict = {}
    if ausgabe_pfad.exists():
        try:
            alte_daten = json.loads(ausgabe_pfad.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Fetch BA Entgeltatlas
    neue_saetze = _fetch_ba_alle(session)

    # Fetch Destatis Regionalfaktoren
    regional_faktoren = _fetch_destatis_regionalfaktoren(session)

    # Wende Destatis-Faktor auf Stundensätze an (Feinabstimmung)
    for gewerk in neue_saetze:
        for region_key, eintrag in neue_saetze[gewerk].items():
            faktor = regional_faktoren.get(region_key)
            if faktor and faktor != 1.0 and eintrag.get("quelle", "").endswith(
                ("interpoliert", "gemittelt", "bundesweit_fallback")
            ):
                eintrag["satz"]             = round(eintrag["satz"] * faktor, 1)
                eintrag["destatis_faktor"]  = faktor

    # Änderungsprotokoll
    aenderungen: list[dict] = []
    for gewerk, regionen in neue_saetze.items():
        for region_key, neu in regionen.items():
            alt_satz = (
                alte_daten
                .get(gewerk, {})
                .get(region_key, {})
                .get("satz")
            )
            neuer_satz = neu["satz"]
            if alt_satz and abs(neuer_satz - alt_satz) / alt_satz > 0.05:
                aenderung = {
                    "gewerk":    gewerk,
                    "region":    region_key,
                    "alt":       alt_satz,
                    "neu":       neuer_satz,
                    "delta_pct": round((neuer_satz - alt_satz) / alt_satz * 100, 1),
                }
                aenderungen.append(aenderung)
                logger.warning(
                    "[Änderung >5%%] %-12s %-8s: %.1f€ → %.1f€ (%+.1f%%)",
                    gewerk, region_key, alt_satz, neuer_satz, aenderung["delta_pct"],
                )

    # Ergebnis zusammenstellen
    ergebnis = {
        **neue_saetze,
        "aktualisiert":           date.today().isoformat(),
        "naechste_aktualisierung": f"{date.today().year + 1}-01-01",
        "regional_faktoren":      regional_faktoren,
        "aenderungen":            aenderungen,
        "n_gewerke":              len(neue_saetze),
    }

    ausgabe_pfad.write_text(
        json.dumps(ergebnis, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("[Update] Gespeichert: %s", ausgabe_pfad)
    return ergebnis


# ── get_stundensatz – öffentliche API ─────────────────────────────────────────

def get_stundensatz(
    gewerk: str,
    region: str,
    json_pfad: Path = AUSGABE_PFAD,
) -> float:
    """
    Gibt den Stundenverrechnungssatz zurück.

    Fallback-Hierarchie:
      1. data/stundensaetze.json → exakter Match (gewerk + region)
      2. data/stundensaetze.json → DE-gesamt (Bundeswert)
      3. stundensaetze.py        → hartcodierter Wert

    Args:
        gewerk:   z. B. "Maler", "Elektro"
        region:   z. B. "DE-BY", "AT"
        json_pfad: Pfad zur JSON-Datei

    Returns:
        Stundensatz in €/h
    """
    json_pfad = Path(json_pfad)

    if json_pfad.exists():
        try:
            daten = json.loads(json_pfad.read_text(encoding="utf-8"))
            gewerk_daten = daten.get(gewerk, {})

            # Exakter Match
            if region in gewerk_daten:
                return float(gewerk_daten[region]["satz"])

            # Bundeswert
            if "DE-gesamt" in gewerk_daten:
                return float(gewerk_daten["DE-gesamt"]["satz"])

        except Exception as exc:
            logger.debug("[get_stundensatz] JSON-Lese-Fehler: %s", exc)

    # Fallback auf stundensaetze.py
    from estimateiq.data.stundensaetze import get_stundensatz as _fallback
    return float(_fallback(gewerk, region))


# ── Testausgabe ───────────────────────────────────────────────────────────────

def _drucke_vergleich(ergebnis: dict) -> None:
    """Zeigt Stundensätze für 5 Regionen und Vergleich mit Referenzwerten."""
    haupt_regionen = ["DE-BY", "DE-BW", "DE-HH", "DE-NW", "DE-sonstige"]
    gewerke        = list(KLDB_CODES.keys())

    breite = 68
    print(f"\n{'═'*breite}")
    print(f"  Stundensätze Handwerk 2026 (€/h) – Vergleich BA vs. handwerk.cloud")
    print(f"  Abgerufen: {ergebnis.get('aktualisiert', '?')}")
    print(f"{'═'*breite}")

    header = f"  {'Gewerk':<12}" + "".join(f"  {r:<10}" for r in haupt_regionen)
    print(header)
    print(f"  {'─'*12}" + "  " + "  ".join("─"*10 for _ in haupt_regionen))

    for gewerk in gewerke:
        zeile_ba  = f"  {gewerk:<12}"
        zeile_ref = f"  {'(Ref.)':<12}"

        ref_gewerk = _REFERENZ_SAETZE.get(gewerk, {})

        for region in haupt_regionen:
            ba_val  = ergebnis.get(gewerk, {}).get(region, {}).get("satz")
            ref_val = ref_gewerk.get(region) or ref_gewerk.get("DE-sonstige")

            if ba_val is not None:
                zeile_ba += f"  {ba_val:>7.1f}   "
            else:
                zeile_ba += f"  {'–':>7}   "

            if ref_val is not None:
                zeile_ref += f"  {ref_val:>7}   "
            else:
                zeile_ref += f"  {'–':>7}   "

        print(zeile_ba)
        # Abweichungen markieren
        abw_zeile = f"  {'Δ':>12}"
        hat_abw   = False
        for region in haupt_regionen:
            ba_val  = ergebnis.get(gewerk, {}).get(region, {}).get("satz")
            ref_val = ref_gewerk.get(region) or ref_gewerk.get("DE-sonstige")
            if ba_val and ref_val:
                delta_pct = (ba_val - ref_val) / ref_val * 100
                symbol    = f"{delta_pct:+.1f}%"
                if abs(delta_pct) > 10:
                    symbol = f"⚠ {symbol}"
                    hat_abw = True
                abw_zeile += f"  {symbol:>10}"
            else:
                abw_zeile += f"  {'':>10}"
        if hat_abw:
            print(abw_zeile)
        print()

    print(f"{'─'*breite}")
    if ergebnis.get("aenderungen"):
        print(f"\n  Änderungen >5%% gegenüber Vorjahresdaten:")
        for a in ergebnis["aenderungen"][:10]:
            print(f"    {a['gewerk']:<12} {a['region']:<10} "
                  f"{a['alt']:.1f} → {a['neu']:.1f} €/h  ({a['delta_pct']:+.1f}%)")
    else:
        print("  Keine Änderungen >5%% gegenüber Vorjahresdaten.")

    print(f"\n  Quelle 1: BA Entgeltatlas (rest.arbeitsagentur.de)")
    print(f"  Quelle 2: Destatis GENESIS (Baupreisindex)")
    print(f"  Gespeichert: {AUSGABE_PFAD}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Stundensätze aus BA Entgeltatlas und Destatis laden"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Auch bei aktuellen Daten neu abrufen",
    )
    parser.add_argument(
        "--ausgabe", default=str(AUSGABE_PFAD),
        help=f"Ausgabepfad (default: {AUSGABE_PFAD})",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Debug-Logging aktivieren",
    )
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    ergebnis = update_stundensaetze(
        ausgabe_pfad=Path(args.ausgabe),
        force=args.force,
    )

    _drucke_vergleich(ergebnis)


if __name__ == "__main__":
    main()
