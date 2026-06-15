"""
GitHub Projects Connector – kleine bis mittelgroße IT-Repositories.

Strategie:
  - 15 gezielte Search-Queries für echte kleine Projekte
  - Laufzeit: dauer_tage = (pushed_at - created_at).days
  - Filter: 14 ≤ dauer_tage ≤ 548
  - Projekttyp aus Repository-Topics ableiten
  - Teamgröße: optional via Contributors-API (nur mit GITHUB_TOKEN), sonst Heuristik
  - Reichhaltige beschreibung für TF-IDF-Features

Authentifizierung (empfohlen):
  export GITHUB_TOKEN=ghp_...
  → höhere Rate-Limits + Contributors-Abruf aktiv

Ausgabe: data/raw_github_projects.jsonl (kompatibel mit preprocess.py)
"""

import json
import logging
import os
import statistics
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
MAX_REPOS       = 500
PAGE_SIZE       = 100
DAUER_MIN_TAGE  = 14
DAUER_MAX_TAGE  = 548   # 1.5 Jahre – reale Projektgrenze für kleine/mittlere Projekte
STARS_MIN       = 5
STARS_MAX       = 5_000

RAW_DATA_DIR = Path("data")
OUTPUT_FILE  = RAW_DATA_DIR / "raw_github_projects.jsonl"

# 15 gezielte Queries für echte kleine/mittlere IT-Projekte
SEARCH_QUERIES = [
    # Kleine Web-Apps
    "topic:webapp language:JavaScript stars:10..500 pushed:2022-01-01..2024-12-31",
    "topic:saas language:TypeScript stars:10..1000 pushed:2022-01-01..2024-12-31",
    "topic:dashboard language:JavaScript stars:5..500",
    "booking system language:PHP stars:10..300",
    "shop ecommerce WooCommerce language:PHP stars:5..200",
    # Mobile Apps
    "topic:mobile-app language:Swift stars:10..500 pushed:2022-01-01..2024-12-31",
    "topic:android-app language:Kotlin stars:10..500",
    "topic:flutter-app stars:10..1000",
    # Backend / API
    "topic:rest-api language:Python stars:10..500",
    "topic:fastapi stars:10..800",
    "topic:nodejs-api stars:10..500",
    # Tools & Automation
    "topic:tool language:Python stars:10..300",
    "topic:bot language:Python stars:10..500",
    "topic:cli language:Go stars:10..500",
    # DACH-nah (aktive PHP-Projekte)
    "language:PHP stars:5..200 pushed:2023-01-01..2024-12-31",
]

# Primärsprache → CPV-Code (für Kompatibilität mit preprocess.py)
SPRACHE_ZU_CPV: dict[str, str] = {
    "JavaScript":  "72400000",
    "TypeScript":  "72400000",
    "PHP":         "72400000",
    "CSS":         "72400000",
    "Go":          "72700000",
    "Rust":        "72700000",
    "C":           "72700000",
    "C++":         "72700000",
    "Shell":       "72700000",
    "Python":      "72200000",
    "Java":        "72200000",
    "Kotlin":      "72200000",
    "Scala":       "72200000",
    "C#":          "72200000",
    "Ruby":        "72200000",
    "Swift":       "72200000",
    "Dart":        "72400000",
    "R":           "72300000",
    "Julia":       "72300000",
    "Jupyter Notebook": "72300000",
}

TOPIC_ZU_CPV: dict[str, str] = {
    "analytics":      "72300000",
    "data":           "72300000",
    "machine-learning": "72300000",
    "ml":             "72300000",
    "ai":             "72300000",
    "security":       "72700000",
    "network":        "72700000",
    "devops":         "72700000",
    "infrastructure": "72700000",
    "web":            "72400000",
    "api":            "72400000",
    "cloud":          "72400000",
    "erp":            "72200000",
    "crm":            "72200000",
    "enterprise":     "72200000",
    "testing":        "72800000",
    "migration":      "72900000",
    "maintenance":    "72500000",
}

# Topic-Schlüsselwörter → Projekttyp-Label
TOPIC_ZU_PROJEKTTYP: list[tuple[list[str], str]] = [
    (["shop", "ecommerce", "woocommerce", "storefront", "commerce"], "E-Commerce"),
    (["saas", "platform"],                                           "SaaS-Plattform"),
    (["webapp", "dashboard", "frontend", "ui", "portfolio"],        "Webanwendung"),
    (["mobile", "ios", "android", "flutter", "react-native"],       "Mobile App"),
    (["api", "backend", "microservice", "rest-api", "fastapi", "nodejs-api"], "Backend/API"),
    (["bot", "automation", "cli", "tool", "script"],                "Tool/Automation"),
    (["ml", "machine-learning", "ai", "data", "analytics"],         "Datenverarbeitung"),
]


def _headers() -> dict[str, str]:
    token = os.getenv("GITHUB_TOKEN")
    h = {"Accept": "application/vnd.github.v3+json"}
    if token:
        h["Authorization"] = f"token {token}"
    return h


def _rate_limit_pause(resp: httpx.Response) -> None:
    remaining = int(resp.headers.get("X-RateLimit-Remaining", "1"))
    reset_ts  = int(resp.headers.get("X-RateLimit-Reset", "0"))
    if remaining < 3:
        warte = max(reset_ts - int(time.time()), 1) + 2
        logger.warning("[GitHub] Rate-Limit fast erschöpft – warte %d s.", warte)
        time.sleep(warte)


def _cpv_fuer_repo(sprache: str | None, topics: list[str]) -> str:
    topic_str = " ".join(topics).lower()
    for schluessel, cpv in TOPIC_ZU_CPV.items():
        if schluessel in topic_str:
            return cpv
    return SPRACHE_ZU_CPV.get(sprache or "", "72200000")


def _projekttyp_aus_topics(topics: list[str], beschreibung: str = "") -> str:
    topic_str = " ".join(topics).lower() + " " + beschreibung.lower()
    for schluessel_liste, label in TOPIC_ZU_PROJEKTTYP:
        if any(k in topic_str for k in schluessel_liste):
            return label
    return "Software"


def _teamgroesse_aus_heuristik(stars: int, forks: int) -> int:
    """Schätzt Teamgröße aus Stars/Forks wenn Contributors-API nicht verfügbar."""
    if stars <= 20 and forks <= 3:
        return 1
    if stars <= 80 or forks <= 10:
        return 2
    if stars <= 300 or forks <= 40:
        return 3
    if stars <= 1000 or forks <= 120:
        return 5
    return 8


def _fetch_contributors_count(client: httpx.Client, owner: str, name: str) -> int | None:
    """Ruft Contributor-Anzahl ab (nur mit GITHUB_TOKEN, max 100)."""
    if not os.getenv("GITHUB_TOKEN"):
        return None
    url = f"{GITHUB_API_BASE}/repos/{owner}/{name}/contributors"
    try:
        resp = client.get(url, params={"per_page": 100, "anon": "true"},
                          headers=_headers(), timeout=10.0)
        _rate_limit_pause(resp)
        if resp.status_code != 200:
            return None
        return min(len(resp.json()), 20)
    except Exception:
        return None


def _teamgroesse_aus_contributors(n: int) -> int:
    if n <= 1:  return 1
    if n <= 3:  return 2
    if n <= 6:  return 3
    if n <= 12: return 5
    return 8


def _berechne_dauer(repo: dict) -> int | None:
    try:
        created = datetime.fromisoformat(repo["created_at"].replace("Z", "+00:00"))
        pushed  = datetime.fromisoformat(repo["pushed_at"].replace("Z", "+00:00"))
        tage    = (pushed - created).days
    except Exception:
        return None
    return tage if DAUER_MIN_TAGE <= tage <= DAUER_MAX_TAGE else None


def _dauer_kategorie(tage: int) -> str:
    if tage <= 90:  return "klein"
    if tage <= 365: return "mittel"
    return "groß"


def _reich_beschreibung(repo: dict, projekttyp: str) -> str:
    """Erstellt eine angereicherte Beschreibung für bessere TF-IDF-Features."""
    name        = repo.get("name", "")
    description = (repo.get("description") or "").strip()
    sprache     = repo.get("language") or ""
    topics      = repo.get("topics") or []
    stars       = repo.get("stargazers_count", 0)
    forks       = repo.get("forks_count", 0)
    owner       = repo.get("owner", {}).get("login", "unknown")

    teile = []
    if description:
        teile.append(description + ".")
    if sprache:
        teile.append(f"Sprache: {sprache}.")
    if topics:
        teile.append(f"Topics: {', '.join(topics[:5])}.")
    teile.append(f"Typ: {projekttyp}.")
    teile.append(
        f"Repository {name} von {owner}. "
        f"Stars: {stars}, Forks: {forks}. "
        f"IT-Entwicklungsprojekt."
    )
    return " ".join(teile)


def _repo_zu_datensatz(repo: dict, client: httpx.Client) -> dict | None:
    name    = repo.get("name", "")
    sprache = repo.get("language")
    topics  = repo.get("topics") or []
    stars   = repo.get("stargazers_count", 0)
    forks   = repo.get("forks_count", 0)
    owner   = repo.get("owner", {}).get("login", "unknown")
    repo_id = repo.get("id")

    # Stars-Filter
    if not (STARS_MIN <= stars <= STARS_MAX):
        return None

    # Primärsprache erforderlich
    if not sprache:
        return None

    # Titel-Mindestlänge
    titel = f"GitHub: {name} ({owner})"
    if len(titel) < 10:
        return None

    # Rohe Beschreibung muss existieren
    raw_description = (repo.get("description") or "").strip()
    if len(raw_description) < 20:
        return None

    # Laufzeit berechnen
    dauer_tage = _berechne_dauer(repo)
    if dauer_tage is None:
        return None

    # Projekttyp aus Topics
    projekttyp = _projekttyp_aus_topics(topics, raw_description)

    # Angereicherte Beschreibung
    beschreibung = _reich_beschreibung(repo, projekttyp)

    # Teamgröße schätzen
    contributor_count = _fetch_contributors_count(client, owner, name)
    if contributor_count is not None:
        teamgroesse = _teamgroesse_aus_contributors(contributor_count)
    else:
        teamgroesse = _teamgroesse_aus_heuristik(stars, forks)

    # Jahr aus created_at
    try:
        jahr = int(repo["created_at"][:4])
    except Exception:
        jahr = None

    # Publikationsdatum für preprocess.py-Kompatibilität
    try:
        pub_date = repo["pushed_at"][:10].replace("-", "")
    except Exception:
        pub_date = "20200101"

    cpv = _cpv_fuer_repo(sprache, topics)

    return {
        # ── Felder für preprocess.py ──────────────────────────────────────────
        "document_id":       f"github_{owner}_{name}",
        "publication_date":  pub_date,
        "title":             titel,
        "description":       beschreibung,
        "cpv_code":          cpv,
        "estimated_value":   None,
        "currency":          "EUR",
        "country":           "DE",
        "duration_end":      None,
        "dauer_tage_direkt": dauer_tage,
        "notice_type":       "github",
        "datenquelle":       "github",
        "technologie":       sprache,
        # ── Neue Analysefelder ────────────────────────────────────────────────
        "beschreibung":      beschreibung,
        "dauer_tage":        dauer_tage,
        "dauer_kategorie":   _dauer_kategorie(dauer_tage),
        "projekttyp":        projekttyp,
        "teamgroesse":       teamgroesse,
        "stars":             stars,
        "region":            "github-international",
        "jahr":              jahr,
        "repo_id":           repo_id,
        "raw":               {},
    }


def _search_repos(client: httpx.Client, query: str, max_ergebnisse: int = 200) -> list[dict]:
    repos: list[dict] = []
    page = 1

    while len(repos) < max_ergebnisse:
        per_page = min(PAGE_SIZE, max_ergebnisse - len(repos))
        url = f"{GITHUB_API_BASE}/search/repositories"
        params = {"q": query, "sort": "stars", "order": "desc",
                  "per_page": per_page, "page": page}
        try:
            resp = client.get(url, params=params, headers=_headers(), timeout=30.0)
            _rate_limit_pause(resp)

            if resp.status_code == 403:
                logger.warning("[GitHub] Rate-Limit 403 – warte 60 s.")
                time.sleep(60)
                continue
            if resp.status_code == 422:
                logger.warning("[GitHub] Query ungültig: %s", query)
                break
            resp.raise_for_status()

            data  = resp.json()
            items = data.get("items", [])
            if not items:
                break

            repos.extend(items)
            logger.info("[GitHub] Query='%s'... Seite %d: %d Repos (%d gesamt)",
                        query[:60], page, len(items), len(repos))

            if len(items) < per_page:
                break

            page += 1
            time.sleep(1.2)

        except httpx.HTTPStatusError as exc:
            logger.error("[GitHub] HTTP %d für Query '%s': %s", exc.response.status_code, query, exc)
            break
        except Exception as exc:
            logger.error("[GitHub] Fehler bei Query '%s': %s", query, exc)
            break

    return repos


def _zeige_statistik(datensaetze: list[dict]) -> None:
    """Gibt Fetch-Statistik auf der Konsole aus."""
    if not datensaetze:
        print("  Keine Datensätze gefetcht.")
        return

    dauern      = [d["dauer_tage"] for d in datensaetze if d.get("dauer_tage")]
    projekttypen = Counter(d.get("projekttyp", "?") for d in datensaetze)
    sprachen    = Counter(d.get("technologie", "?") for d in datensaetze)

    trenner = "─" * 50
    print(f"\n{trenner}")
    print("  GitHub-Fetch – Statistik")
    print(trenner)
    print(f"\n  Datensätze gesamt: {len(datensaetze):>6,}")

    if dauern:
        dauern_sorted = sorted(dauern)
        median = statistics.median(dauern_sorted)
        print(f"\n  Laufzeit (Tage):")
        print(f"    Min:    {min(dauern_sorted):>5}")
        print(f"    Median: {median:>5.0f}")
        print(f"    Max:    {max(dauern_sorted):>5}")

    print(f"\n  Projekttypen:")
    for typ, anzahl in projekttypen.most_common():
        print(f"    {typ:<25} {anzahl:>4,}")

    print(f"\n  Top 5 Sprachen:")
    for sprache, anzahl in sprachen.most_common(5):
        print(f"    {sprache:<20} {anzahl:>4,}")

    print(f"\n{trenner}\n")


def fetch_github_projects(output_path: Path = OUTPUT_FILE, max_repos: int = MAX_REPOS) -> int:
    """Ruft kleine IT-Repositories ab und speichert als JSONL."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    hat_token = bool(os.getenv("GITHUB_TOKEN"))
    if hat_token:
        logger.info("[GitHub] Authentifiziert – Contributors-Abruf aktiv, höhere Rate-Limits.")
    else:
        logger.warning(
            "[GitHub] Kein GITHUB_TOKEN. Unauthentifiziert: 10 Req/min, "
            "kein Contributors-Abruf. Empfohlen: export GITHUB_TOKEN=ghp_..."
        )

    gesehene_ids: set[str] = set()
    alle_datensaetze: list[dict] = []

    with httpx.Client() as client:
        for query in SEARCH_QUERIES:
            if len(alle_datensaetze) >= max_repos:
                break

            noch_noetig = max_repos - len(alle_datensaetze)
            repos = _search_repos(client, query, max_ergebnisse=min(100, noch_noetig + 30))

            fuer_diese_query = 0
            for repo in repos:
                repo_id = str(repo.get("id", ""))
                if not repo_id or repo_id in gesehene_ids:
                    continue
                gesehene_ids.add(repo_id)

                datensatz = _repo_zu_datensatz(repo, client)
                if datensatz is None:
                    continue

                alle_datensaetze.append(datensatz)
                fuer_diese_query += 1

                if len(alle_datensaetze) >= max_repos:
                    break

            logger.info("[GitHub] Query fertig: %d neue Datensätze (%d gesamt).",
                        fuer_diese_query, len(alle_datensaetze))
            time.sleep(2.0)

    with output_path.open("w", encoding="utf-8") as f:
        for ds in alle_datensaetze:
            f.write(json.dumps(ds, ensure_ascii=False) + "\n")

    logger.info("[GitHub] Gesamt: %d Datensätze → %s", len(alle_datensaetze), output_path)
    _zeige_statistik(alle_datensaetze)

    return len(alle_datensaetze)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="GitHub kleine IT-Projekte abrufen")
    parser.add_argument("--max-repos", type=int, default=MAX_REPOS,
                        help=f"Maximale Anzahl Repositories (Standard: {MAX_REPOS})")
    args = parser.parse_args()

    n = fetch_github_projects(max_repos=args.max_repos)
    print(f"\nGitHub-Datensätze gespeichert: {n}")
