"""
Geo-Feature-Anreicherung für EstimateIQ Bau.

Verwendet OpenStreetMap Nominatim für Geocoding (Rate Limit: 1 req/sek).
Cache: data/geo_cache.json – Key: "{ort}_{land}"
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

NOMINATIM_URL   = "https://nominatim.openstreetmap.org/search"
USER_AGENT      = "EstimateIQ/1.0 (research project)"
RATE_LIMIT_SECS = 1.0

GEO_CACHE_PFAD  = Path("data/geo_cache.json")

# Landeszentroide als Fallback wenn nur Land bekannt
LAND_ZENTROID: dict[str, tuple[float, float]] = {
    "DE": (51.1657, 10.4515),
    "AT": (47.5162, 14.5501),
    "CH": (46.8182, 8.2275),
}

# Metropolen in DACH (normalisiert auf Kleinschreibung)
METROPOLEN: set[str] = {
    "berlin", "hamburg", "münchen", "munich", "köln", "cologne",
    "frankfurt", "frankfurt am main", "stuttgart", "düsseldorf",
    "wien", "vienna", "zürich", "zurich", "basel",
}

# Großstädte > 100.000 Einwohner in DACH (Auswahl)
GROSSSTAEDTE: set[str] = {
    "berlin", "hamburg", "münchen", "köln", "frankfurt", "frankfurt am main",
    "stuttgart", "düsseldorf", "dortmund", "essen", "leipzig", "bremen",
    "dresden", "hannover", "nürnberg", "nuremberg", "duisburg", "bochum",
    "wuppertal", "bielefeld", "bonn", "münster", "karlsruhe", "mannheim",
    "augsburg", "wiesbaden", "gelsenkirchen", "mönchengladbach", "braunschweig",
    "chemnitz", "kiel", "aachen", "halle", "magdeburg", "freiburg",
    "krefeld", "lübeck", "oberhausen", "erfurt", "rostock", "mainz",
    "kassel", "hagen", "hamm", "saarbrücken", "mülheim", "potsdam",
    "ludwigshafen", "oldenburg", "leverkusen", "osnabrück", "heidelberg",
    "solingen", "darmstadt", "regensburg", "herne", "paderborn", "ingolstadt",
    "würzburg", "wolfsburg", "offenbach", "ulm", "fürth", "erlangen",
    # Österreich
    "wien", "graz", "linz", "salzburg", "innsbruck", "klagenfurt",
    # Schweiz
    "zürich", "genf", "genève", "basel", "bern", "lausanne",
}

_letzter_request: float = 0.0
_cache: dict[str, dict] = {}
_cache_geladen: bool = False


def _lade_cache() -> None:
    global _cache, _cache_geladen
    if _cache_geladen:
        return
    if GEO_CACHE_PFAD.exists():
        try:
            with GEO_CACHE_PFAD.open(encoding="utf-8") as f:
                _cache = json.load(f)
            logger.info("[GeoCache] %d Einträge geladen.", len(_cache))
        except Exception as exc:
            logger.warning("[GeoCache] Laden fehlgeschlagen: %s", exc)
            _cache = {}
    _cache_geladen = True


def _speichere_cache() -> None:
    GEO_CACHE_PFAD.parent.mkdir(parents=True, exist_ok=True)
    with GEO_CACHE_PFAD.open("w", encoding="utf-8") as f:
        json.dump(_cache, f, ensure_ascii=False, indent=2)


def _rate_limit() -> None:
    global _letzter_request
    elapsed = time.time() - _letzter_request
    if elapsed < RATE_LIMIT_SECS:
        time.sleep(RATE_LIMIT_SECS - elapsed)
    _letzter_request = time.time()


def _ist_metropole(ortsname: str) -> bool:
    return ortsname.lower().strip() in METROPOLEN


def _ist_grossstadt(ortsname: str) -> bool:
    return ortsname.lower().strip() in GROSSSTAEDTE


def _extrahiere_bundesland(adress_dict: dict) -> str | None:
    """Extrahiert Bundesland / Bundesland-äquivalent aus Nominatim-Adressobjekt."""
    for key in ("state", "county", "region"):
        val = adress_dict.get(key)
        if val:
            return str(val)
    return None


def _normalisiere_ortsname(name: str | None) -> str | None:
    """Entfernt führende Nullen aus PLZ und bereinigt Leerzeichen."""
    if not name:
        return None
    return name.strip()


def geocode(
    ort_oder_plz: str | None,
    land: str = "DE",
    max_retries: int = 3,
) -> dict:
    """
    Geocodiert einen Ort oder eine PLZ via Nominatim.

    Gibt ein Dict zurück mit den Feldern:
        lat, lon, bundesland, landkreis, ist_metropole, ist_grossstadt

    Bei Fehler: Felder sind None (außer bei bekanntem Land → Zentroid).
    """
    _lade_cache()

    ort_norm = _normalisiere_ortsname(ort_oder_plz)
    cache_key = f"{ort_norm}_{land}" if ort_norm else None

    if cache_key and cache_key in _cache:
        return _cache[cache_key]

    ergebnis: dict = {
        "lat":            None,
        "lon":            None,
        "bundesland":     None,
        "landkreis":      None,
        "ist_metropole":  False,
        "ist_grossstadt": False,
    }

    if not ort_norm:
        # Nur Land bekannt → Landeszentroid
        zentroid = LAND_ZENTROID.get(land.upper())
        if zentroid:
            ergebnis["lat"] = zentroid[0]
            ergebnis["lon"] = zentroid[1]
        if cache_key:
            _cache[cache_key] = ergebnis
        return ergebnis

    params = {
        "q":            ort_norm,
        "countrycodes": land.lower(),
        "format":       "json",
        "limit":        1,
        "addressdetails": 1,
    }

    for versuch in range(max_retries):
        try:
            _rate_limit()
            with httpx.Client(timeout=10.0) as client:
                response = client.get(
                    NOMINATIM_URL,
                    params=params,
                    headers={"User-Agent": USER_AGENT},
                )
            response.raise_for_status()
            treffer = response.json()

            if treffer:
                eintrag = treffer[0]
                lat = float(eintrag.get("lat", 0))
                lon = float(eintrag.get("lon", 0))
                adresse = eintrag.get("address", {})
                bundesland = _extrahiere_bundesland(adresse)
                landkreis = adresse.get("county") or adresse.get("district")
                stadtname = (
                    adresse.get("city")
                    or adresse.get("town")
                    or adresse.get("village")
                    or ort_norm
                )

                ergebnis = {
                    "lat":            lat,
                    "lon":            lon,
                    "bundesland":     bundesland,
                    "landkreis":      landkreis,
                    "ist_metropole":  _ist_metropole(stadtname),
                    "ist_grossstadt": _ist_grossstadt(stadtname),
                }
            else:
                # Kein Treffer → Landeszentroid
                zentroid = LAND_ZENTROID.get(land.upper())
                if zentroid:
                    ergebnis["lat"] = zentroid[0]
                    ergebnis["lon"] = zentroid[1]
                logger.debug("[Geo] Kein Treffer für '%s' (%s).", ort_norm, land)

            break

        except Exception as exc:
            logger.warning(
                "[Geo] Fehler bei '%s' (Versuch %d/%d): %s",
                ort_norm, versuch + 1, max_retries, exc,
            )
            if versuch < max_retries - 1:
                time.sleep(2 ** versuch)

    if cache_key:
        _cache[cache_key] = ergebnis
        # Cache alle 100 neuen Einträge persistieren
        if len(_cache) % 100 == 0:
            _speichere_cache()

    return ergebnis


def enrich_with_geo(df: pd.DataFrame) -> pd.DataFrame:
    """
    Reichert einen DataFrame mit Geo-Features an.

    Erwartet Spalten: auftraggeber_ort (str|None), auftraggeber_plz (str|None), land (str)

    Fügt hinzu:
        latitude, longitude, bundesland, landkreis, ist_metropole, ist_grossstadt
    """
    _lade_cache()

    lats, lons, bundeslaender, landkreise, ist_metropole, ist_grossstadt = (
        [], [], [], [], [], []
    )

    gesamt = len(df)
    geocodiert = 0

    for _, zeile in df.iterrows():
        land = str(zeile.get("land", "DE") or "DE").upper()
        plz  = _normalisiere_ortsname(str(zeile.get("auftraggeber_plz", "") or ""))
        ort  = _normalisiere_ortsname(str(zeile.get("auftraggeber_ort", "") or ""))

        # PLZ hat Vorrang, dann Ort
        suchbegriff = plz or ort or None

        geo = geocode(suchbegriff, land=land)
        geocodiert += 1

        lats.append(geo["lat"])
        lons.append(geo["lon"])
        bundeslaender.append(geo["bundesland"])
        landkreise.append(geo["landkreis"])
        ist_metropole.append(geo["ist_metropole"])
        ist_grossstadt.append(geo["ist_grossstadt"])

        if geocodiert % 500 == 0:
            logger.info("[Geo] %d/%d Projekte geocodiert...", geocodiert, gesamt)
            _speichere_cache()

    _speichere_cache()
    logger.info("[Geo] Geocoding abgeschlossen: %d Projekte.", geocodiert)

    df = df.copy()
    df["latitude"]      = lats
    df["longitude"]     = lons
    df["bundesland"]    = bundeslaender
    df["landkreis"]     = landkreise
    df["ist_metropole"] = ist_metropole
    df["ist_grossstadt"] = ist_grossstadt

    return df
