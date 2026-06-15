"""
GitHub Projects Connector – extrahiert Entwicklungslaufzeit abgeschlossener IT-Repositories.

Strategie:
  - GitHub Search API: Archivierte Repositories mit IT-Bezug
  - Laufzeit: dauer_tage = (pushed_at - created_at).days
  - Filter: 14 < dauer_tage < 730 (plausible Projektdauer)
  - 500 eindeutige Repos aus mehreren thematischen Suchqueries

Authentifizierung (optional, empfohlen):
  export GITHUB_TOKEN=ghp_...
  → höhere Rate-Limits: 30 Search-Req/min statt 10

Ausgabe: data/raw_github_projects.jsonl (kompatibel mit preprocess.py)
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
MAX_REPOS       = 500
PAGE_SIZE       = 100     # GitHub max
DAUER_MIN_TAGE  = 14     # Untergrenze: > 14 Tage (exklusiv)
DAUER_MAX_TAGE  = 365    # Obergrenze: kleine Projekte bis 1 Jahr
STARS_MIN       = 10     # Zu unbekannte Repos rausfiltern
STARS_MAX       = 5_000  # Zu populäre (= zu große) Projekte rausfiltern

RAW_DATA_DIR      = Path("data")
OUTPUT_FILE       = RAW_DATA_DIR / "raw_github_projects.jsonl"

# Suchqueries für kleine bis mittlere Projekte (webapp, tools, SaaS, mobile)
SEARCH_QUERIES = [
    # Web-Apps & Dashboards
    "archived:true topic:webapp stars:10..5000",
    "archived:true topic:saas stars:10..5000",
    "archived:true topic:dashboard stars:10..5000",
    "archived:true topic:portfolio stars:10..5000",
    # Tools & APIs & Bots
    "archived:true topic:tool stars:10..5000",
    "archived:true topic:api stars:10..5000",
    "archived:true topic:bot stars:10..5000",
    # Mobile Apps
    "archived:true topic:mobile-app stars:10..5000",
    "archived:true topic:ios language:Swift stars:10..2000",
    "archived:true topic:android language:Kotlin stars:10..2000",
    # Kleine Business-Systeme
    "archived:true booking system language:Python stars:10..1000",
    "archived:true shop ecommerce language:PHP stars:10..2000",
    "archived:true shop ecommerce language:JavaScript stars:10..2000",
    "archived:true admin panel crm language:Python stars:10..1000",
    "archived:true small business management language:JavaScript stars:10..1000",
]

# Primärsprache → CPV-Code
SPRACHE_ZU_CPV: dict[str, str] = {
    "JavaScript":  "72400000",   # Internet- & Cloud-Dienste
    "TypeScript":  "72400000",
    "PHP":         "72400000",
    "CSS":         "72400000",
    "Go":          "72700000",   # Netzwerk & Infrastruktur
    "Rust":        "72700000",
    "C":           "72700000",
    "C++":         "72700000",
    "Shell":       "72700000",
    "Python":      "72200000",   # Softwareentwicklung
    "Java":        "72200000",
    "Kotlin":      "72200000",
    "Scala":       "72200000",
    "C#":          "72200000",
    "Ruby":        "72200000",
    "Swift":       "72200000",
    "R":           "72300000",   # Datenverarbeitung & Analytics
    "Julia":       "72300000",
    "Jupyter Notebook": "72300000",
}

# Topic-Keywords → CPV-Code (Vorrang vor Sprache)
TOPIC_ZU_CPV: dict[str, str] = {
    "analytics":   "72300000",
    "data":        "72300000",
    "machine-learning": "72300000",
    "ml":          "72300000",
    "ai":          "72300000",
    "security":    "72700000",
    "network":     "72700000",
    "devops":      "72700000",
    "infrastructure": "72700000",
    "web":         "72400000",
    "api":         "72400000",
    "cloud":       "72400000",
    "erp":         "72200000",
    "crm":         "72200000",
    "enterprise":  "72200000",
    "testing":     "72800000",
    "migration":   "72900000",
    "maintenance": "72500000",
}


def _headers() -> dict[str, str]:
    token = os.getenv("GITHUB_TOKEN")
    h = {"Accept": "application/vnd.github.v3+json"}
    if token:
        h["Authorization"] = f"token {token}"
    return h


def _rate_limit_pause(resp: httpx.Response) -> None:
    """Pausiert falls Rate-Limit erschöpft."""
    remaining = int(resp.headers.get("X-RateLimit-Remaining", "1"))
    reset_ts  = int(resp.headers.get("X-RateLimit-Reset", "0"))
    if remaining < 3:
        warte = max(reset_ts - int(time.time()), 1) + 1
        logger.warning("[GitHub] Rate-Limit fast erschöpft – warte %d s.", warte)
        time.sleep(warte)


def _cpv_fuer_repo(sprache: str | None, topics: list[str]) -> str:
    topic_str = " ".join(topics).lower()
    for schluessel, cpv in TOPIC_ZU_CPV.items():
        if schluessel in topic_str:
            return cpv
    return SPRACHE_ZU_CPV.get(sprache or "", "72200000")


def _projekttyp_fuer_cpv(cpv: str) -> str:
    mapping = {
        "72200000": "Softwareentwicklung",
        "72300000": "Datenverarbeitung & Analytics",
        "72400000": "Internet- & Cloud-Dienste",
        "72500000": "IT-Betrieb & Wartung",
        "72600000": "IT-Beratung & Support",
        "72700000": "Netzwerk & Infrastruktur",
        "72800000": "IT-Prüfung & Testing",
        "72900000": "Datenmigration & Backup",
    }
    return mapping.get(cpv, "Softwareentwicklung")


def _berechne_dauer(repo: dict) -> int | None:
    """Berechnet Projektlaufzeit als (pushed_at - created_at).days.
    Filter: DAUER_MIN_TAGE < tage < DAUER_MAX_TAGE (14–365 für kleine Projekte).
    """
    try:
        created = datetime.fromisoformat(repo["created_at"].replace("Z", "+00:00"))
        pushed  = datetime.fromisoformat(repo["pushed_at"].replace("Z", "+00:00"))
        tage    = (pushed - created).days
    except Exception:
        return None
    return tage if DAUER_MIN_TAGE < tage < DAUER_MAX_TAGE else None


def _repo_zu_datensatz(repo: dict) -> dict | None:
    """Konvertiert ein GitHub-Repo-Objekt in unser JSONL-Schema."""
    name        = repo.get("name", "")
    description = (repo.get("description") or "").strip()
    sprache     = repo.get("language")
    topics      = repo.get("topics") or []
    stars       = repo.get("stargazers_count", 0)
    forks       = repo.get("forks_count", 0)
    owner       = repo.get("owner", {}).get("login", "unknown")

    # Stars-Filter: zu unbekannte oder zu populäre Repos ausschließen
    if not (STARS_MIN <= stars <= STARS_MAX):
        return None

    titel = f"GitHub: {name} ({owner})"
    if len(titel) < 10:
        return None

    beschreibung_teile = []
    if description:
        beschreibung_teile.append(description + ".")
    if sprache:
        beschreibung_teile.append(f"Primärsprache: {sprache}.")
    if topics:
        beschreibung_teile.append(f"Themen: {', '.join(topics[:8])}.")
    beschreibung_teile.append(
        f"Repository: {name} von {owner}. "
        f"Stars: {stars}, Forks: {forks}. "
        f"Archiviertes IT-Projekt."
    )
    beschreibung = " ".join(beschreibung_teile)

    if len(beschreibung) < 30:
        return None

    dauer_tage = _berechne_dauer(repo)
    if dauer_tage is None:
        return None

    cpv = _cpv_fuer_repo(sprache, topics)

    try:
        pub_date = repo["pushed_at"][:10].replace("-", "")
    except Exception:
        pub_date = "20200101"

    return {
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
        "technologie":       sprache or "",
        "raw":               {},
    }


def _search_repos(client: httpx.Client, query: str, max_ergebnisse: int = 200) -> list[dict]:
    """Paginierte GitHub-Repository-Suche."""
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
                logger.warning("[GitHub] Zugriff verweigert (Rate-Limit). Warte 60 s.")
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
                        query[:50], page, len(items), len(repos))

            if len(items) < per_page:
                break

            page += 1
            time.sleep(1.2)   # Höfliche Pause zwischen Seiten

        except httpx.HTTPStatusError as exc:
            logger.error("[GitHub] HTTP %d für Query '%s': %s", exc.response.status_code, query, exc)
            break
        except Exception as exc:
            logger.error("[GitHub] Fehler bei Query '%s': %s", query, exc)
            break

    return repos


# ---------------------------------------------------------------------------
# Haupt-Exportfunktion
# ---------------------------------------------------------------------------

def fetch_github_projects(output_path: Path = OUTPUT_FILE, max_repos: int = MAX_REPOS) -> int:
    """Ruft archivierte IT-Repositories ab und speichert als JSONL."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if os.getenv("GITHUB_TOKEN"):
        logger.info("[GitHub] Authentifiziert mit GITHUB_TOKEN (höhere Rate-Limits).")
    else:
        logger.warning(
            "[GitHub] Kein GITHUB_TOKEN gesetzt. Unauthentifiziert: 10 Req/min. "
            "Für 500 Repos empfohlen: export GITHUB_TOKEN=ghp_..."
        )

    gesehene_ids: set[str] = set()
    alle_datensaetze: list[dict] = []

    with httpx.Client() as client:
        for query in SEARCH_QUERIES:
            if len(alle_datensaetze) >= max_repos:
                break

            noch_noetig = max_repos - len(alle_datensaetze)
            repos = _search_repos(client, query, max_ergebnisse=min(100, noch_noetig + 20))

            fuer_diese_query = 0
            for repo in repos:
                repo_id = str(repo.get("id", ""))
                if not repo_id or repo_id in gesehene_ids:
                    continue
                gesehene_ids.add(repo_id)

                datensatz = _repo_zu_datensatz(repo)
                if datensatz is None:
                    continue

                alle_datensaetze.append(datensatz)
                fuer_diese_query += 1

                if len(alle_datensaetze) >= max_repos:
                    break

            logger.info("[GitHub] Query abgeschlossen: %d neue Datensätze (%d gesamt).",
                        fuer_diese_query, len(alle_datensaetze))
            time.sleep(2.0)   # Pause zwischen Queries

    with output_path.open("w", encoding="utf-8") as f:
        for ds in alle_datensaetze:
            f.write(json.dumps(ds, ensure_ascii=False) + "\n")

    logger.info("[GitHub] Gesamt: %d Datensätze → %s", len(alle_datensaetze), output_path)
    return len(alle_datensaetze)


# ---------------------------------------------------------------------------
# Direkt ausführbar
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="GitHub-Projektdaten abrufen")
    parser.add_argument("--max-repos", type=int, default=MAX_REPOS,
                        help=f"Maximale Anzahl Repositories (Standard: {MAX_REPOS})")
    args = parser.parse_args()

    n = fetch_github_projects(max_repos=args.max_repos)
    print(f"\nGitHub-Datensätze gespeichert: {n}")
