"""
EstimateIQ – Kompletter Daten-Fetch aus allen Quellen.

Abruf-Reihenfolge:
  1. TED Europa (CN + CAN für DACH, 2022–2024)
  2. PROMISE Repository (Derek Jones GitHub)
  3. GitHub Archivierte IT-Projekte
  4. COSMIC Benchmark-Datensätze (Zenodo ISBSG + Valdes-Souto)
  5. IndieHackers Produktseiten (time-to-build aus Beschreibung)

Verwendung:
  python fetch_all.py                           # alle Quellen
  python fetch_all.py --nur ted                # nur TED
  python fetch_all.py --nur promise            # nur PROMISE
  python fetch_all.py --nur github             # nur GitHub
  python fetch_all.py --nur cosmic             # nur COSMIC (öffentliche Quellen)
  python fetch_all.py --nur indiehackers       # nur IndieHackers
  python fetch_all.py --nur cosmic --cosmic-lokal datei.csv  # COSMIC aus lokalem File
  python fetch_all.py --max-seiten 2          # TED: max. 2 Seiten/Jahr (Test)
  python fetch_all.py --max-repos 100         # GitHub: max. 100 Repos (Test)
  python fetch_all.py --max-ih-seiten 5       # IndieHackers: max. 5 Seiten (Test)
"""

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def fetch_ted(max_seiten: int | None = None) -> dict:
    from estimateiq.data.fetch_ted import fetch_dach_alle_jahre, fetch_dach_alle_vergaben, JAHRE_DEFAULT
    logger.info("━" * 55)
    logger.info("Quelle 1/3 – TED Europa (CN + CAN, DACH, %s)", JAHRE_DEFAULT)
    cn  = fetch_dach_alle_jahre(max_pages=max_seiten)
    can = fetch_dach_alle_vergaben(max_pages=max_seiten)
    return {"cn": cn, "can": can}


def fetch_promise() -> int:
    from estimateiq.data.fetch_promise import fetch_promise_data
    logger.info("━" * 55)
    logger.info("Quelle 2/3 – PROMISE Repository (Derek Jones GitHub)")
    return fetch_promise_data()


def fetch_github(max_repos: int = 500) -> int:
    from estimateiq.data.fetch_github_projects import fetch_github_projects
    logger.info("━" * 55)
    logger.info("Quelle 3/4 – GitHub Archivierte IT-Repositories (max %d)", max_repos)
    return fetch_github_projects(max_repos=max_repos)


def fetch_cosmic(lokal: Path | None = None) -> int:
    from estimateiq.data.fetch_cosmic import fetch_cosmic_data
    logger.info("━" * 55)
    if lokal:
        logger.info("Quelle 4/5 – COSMIC Datensatz (lokal: %s)", lokal)
    else:
        logger.info("Quelle 4/5 – COSMIC Benchmark-Datensätze (Zenodo + Valdes-Souto)")
    return fetch_cosmic_data(lokal=lokal)


def fetch_indiehackers(max_seiten: int = 20) -> int:
    from estimateiq.data.fetch_indiehackers import fetch_indiehackers_data
    logger.info("━" * 55)
    logger.info("Quelle 5/5 – IndieHackers Produkte (max %d Seiten)", max_seiten)
    return fetch_indiehackers_data(max_seiten=max_seiten)


def main() -> None:
    parser = argparse.ArgumentParser(description="EstimateIQ – Alle Datenquellen abrufen")
    parser.add_argument(
        "--nur",
        choices=["ted", "promise", "github", "cosmic", "indiehackers"],
        help="Nur eine bestimmte Quelle abrufen",
    )
    parser.add_argument(
        "--cosmic-lokal", type=Path, default=None, metavar="DATEI",
        help="COSMIC: lokale CSV/Excel-Datei (Originaldatensatz aus DOI 10.1016/j.jss.2025.112602)",
    )
    parser.add_argument(
        "--max-seiten", type=int, default=None,
        help="TED: Maximale Seiten pro Jahr (None = alle; empfohlen für Tests: 2)",
    )
    parser.add_argument(
        "--max-repos", type=int, default=500,
        help="GitHub: Maximale Anzahl Repositories (Standard: 500)",
    )
    parser.add_argument(
        "--max-ih-seiten", type=int, default=20,
        help="IndieHackers: Maximale Seitenanzahl (Standard: 20)",
    )
    args = parser.parse_args()

    ergebnisse: dict = {}

    if args.nur is None or args.nur == "ted":
        ergebnisse["ted"] = fetch_ted(max_seiten=args.max_seiten)

    if args.nur is None or args.nur == "promise":
        ergebnisse["promise"] = fetch_promise()

    if args.nur is None or args.nur == "github":
        ergebnisse["github"] = fetch_github(max_repos=args.max_repos)

    if args.nur is None or args.nur == "cosmic":
        ergebnisse["cosmic"] = fetch_cosmic(lokal=args.cosmic_lokal)

    if args.nur is None or args.nur == "indiehackers":
        ergebnisse["indiehackers"] = fetch_indiehackers(max_seiten=args.max_ih_seiten)

    # Zusammenfassung
    trenner = "═" * 55
    print(f"\n{trenner}")
    print("  EstimateIQ – Fetch abgeschlossen")
    print(trenner)

    if "ted" in ergebnisse:
        ted = ergebnisse["ted"]
        cn_gesamt  = sum(ted["cn"].values())
        can_gesamt = sum(ted["can"].values())
        print(f"\n  TED (CN):         {cn_gesamt:>6,} Ausschreibungen")
        print(f"  TED (CAN):        {can_gesamt:>6,} Vergaben")
        print(f"  TED Gesamt:       {cn_gesamt + can_gesamt:>6,}")

    if "promise" in ergebnisse:
        print(f"\n  PROMISE:          {ergebnisse['promise']:>6,} Projekte")

    if "github" in ergebnisse:
        print(f"  GitHub:           {ergebnisse['github']:>6,} Repositories")

    if "cosmic" in ergebnisse:
        print(f"  COSMIC:           {ergebnisse['cosmic']:>6,} Projekte")

    if "indiehackers" in ergebnisse:
        print(f"  IndieHackers:     {ergebnisse['indiehackers']:>6,} Produkte")

    print(f"\n  Nächster Schritt:")
    print("    python -m estimateiq.data.preprocess")
    print(f"\n{trenner}\n")


if __name__ == "__main__":
    main()
