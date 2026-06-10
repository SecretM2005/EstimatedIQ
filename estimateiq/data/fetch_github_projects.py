"""
GitHub Projects Connector – schätzt Entwicklungsaufwand abgeschlossener IT-Repositories.

Strategie:
  - GitHub Search API: Archivierte Repositories mit IT-Bezug
  - Aufwandsschätzung: contributors_estimate × aktive_Monate × 20 h × 85 €/h
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

GITHUB_API_BASE   = "https://api.github.com"
STUNDENSATZ_DACH  = 85.0    # €/h
STUNDEN_PRO_MONAT = 20.0    # typischer Open-Source-Beitrag pro Contributor/Monat
MAX_REPOS         = 500
PAGE_SIZE         = 100     # GitHub max

RAW_DATA_DIR      = Path("data")
OUTPUT_FILE       = RAW_DATA_DIR / "raw_github_projects.jsonl"

# Thematische Suchqueries – decken verschiedene IT-Bereiche ab
SEARCH_QUERIES = [
    "archived:true topic:enterprise-software stars:20..5000",
    "archived:true topic:erp stars:20..5000",
    "archived:true topic:crm stars:20..5000",
    "archived:true enterprise management language:Java stars:20..2000",
    "archived:true enterprise management language:Python stars:20..2000",
    "archived:true business application language:Java stars:20..2000",
    "archived:true business application language:TypeScript stars:20..2000",
    "archived:true ERP system language:Java stars:20..2000",
    "archived:true data analytics platform language:Python stars:30..3000",
    "archived:true devops infrastructure language:Go stars:30..3000",
    "archived:true security scanner language:Python stars:30..3000",
    "archived:true web application framework language:Python stars:50..5000",
    "archived:true microservices language:Java stars:20..2000",
    "archived:true content management language:PHP stars:20..2000",
    "archived:true workflow management language:Java stars:20..2000",
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


def _berechne_aufwand(repo: dict) -> tuple[float, int | None]:
    """
    Schätzt Projektaufwand aus öffentlichen Repository-Metadaten.

    contributors_estimate ≈ sqrt(stargazers) [nicht-linear: 100 Sterne → 10 Contrib.]
    aktive_monate = (pushed_at - created_at) in Monaten, max. 60
    effort_h = contributors × monate × 20 h/Monat
    """
    stars  = max(1, repo.get("stargazers_count", 1))
    forks  = repo.get("forks_count", 0)
    # Contributors-Schätzung aus Stars + Forks
    contrib_estimate = max(1, int((stars ** 0.45) + (forks ** 0.3)))
    contrib_estimate = min(contrib_estimate, 80)    # Cap: keine Linux-Kernel-Projekte

    try:
        created = datetime.fromisoformat(repo["created_at"].replace("Z", "+00:00"))
        pushed  = datetime.fromisoformat(repo["pushed_at"].replace("Z", "+00:00"))
        monate  = max(1, int((pushed - created).days / 30.44))
    except Exception:
        monate = 12

    monate = min(monate, 60)     # Max 5 Jahre

    effort_h   = contrib_estimate * monate * STUNDEN_PRO_MONAT
    budget_eur = round(effort_h * STUNDENSATZ_DACH, 2)

    dauer_tage = monate * 30
    dauer_tage = dauer_tage if 7 <= dauer_tage <= 3_650 else None

    return budget_eur, dauer_tage


def _repo_zu_datensatz(repo: dict) -> dict | None:
    """Konvertiert ein GitHub-Repo-Objekt in unser JSONL-Schema."""
    name        = repo.get("name", "")
    description = (repo.get("description") or "").strip()
    sprache     = repo.get("language")
    topics      = repo.get("topics") or []
    stars       = repo.get("stargazers_count", 0)
    forks       = repo.get("forks_count", 0)
    owner       = repo.get("owner", {}).get("login", "unknown")

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

    budget_eur, dauer_tage = _berechne_aufwand(repo)
    if not (5_000 <= budget_eur <= 500_000_000):
        return None

    cpv = _cpv_fuer_repo(sprache, topics)

    try:
        pub_date = repo["pushed_at"][:10].replace("-", "") + "0000"[:8 - len(repo["pushed_at"][:10].replace("-", ""))]
        pub_date = repo["pushed_at"][:10].replace("-", "")
    except Exception:
        pub_date = "20200101"

    return {
        "document_id":       f"github_{owner}_{name}",
        "publication_date":  pub_date,
        "title":             titel,
        "description":       beschreibung,
        "cpv_code":          cpv,
        "estimated_value":   budget_eur,
        "currency":          "EUR",
        "country":           "DE",
        "duration_end":      None,
        "dauer_tage_direkt": dauer_tage,
        "notice_type":       "github",
        "datenquelle":       "github",
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
