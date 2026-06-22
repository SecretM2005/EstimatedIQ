"""
Validierung: Grössenklassifikator + spezialisierte Dauermodelle.

Zeigt für 5 Testprojekte:
  - Erkannte Grösse + Konfidenz
  - Welches Dauermodell verwendet
  - Dauer + Kosten (erwartet vs. tatsächlich geschätzt)

Verwendung:
  python validate_groessen.py

Voraussetzung:
  python train.py --only size
  python train.py --only specialized (optional, für spezialisierte Modelle)
"""

import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Testprojekte mit erwarteten Werten
TESTPROJEKTE = [
    {
        "name": "WooCommerce-Shop",
        "beschreibung": "WooCommerce-Online-Shop mit 500 Produkten, Stripe und PayPal Zahlung, Produktkatalog",
        "region": "DE-BY",
        "erwartete_groesse": "klein",
        "erwartete_dauer_range": (30, 80),   # Tage
    },
    {
        "name": "SAP HR Portal",
        "beschreibung": "SAP HR Portal für 800 Nutzer mit React Frontend, Java Backend, SSO und LDAP-Integration",
        "region": "DE-BY",
        "erwartete_groesse": "gross",
        "erwartete_dauer_range": (150, 280),
    },
    {
        "name": "iOS/Android Aussendienstapp",
        "beschreibung": "Mobile App für Aussendienst iOS und Android mit GPS-Tracking und CRM-Anbindung für 50 Mitarbeiter",
        "region": "DE-NW",
        "erwartete_groesse": "mittel",
        "erwartete_dauer_range": (90, 180),
    },
    {
        "name": "ML Dokumente NLP",
        "beschreibung": "ML-basierte Dokumentenanalyse mit NLP und Python für automatische Klassifikation und Extraktion",
        "region": "DE",
        "erwartete_groesse": "gross",
        "erwartete_dauer_range": (120, 365),
    },
    {
        "name": "Buchungssystem Physio",
        "beschreibung": "Online-Buchungssystem für Physiotherapiepraxis mit 5 Therapeuten, Terminkalender und Abrechnung",
        "region": "DE-NW",
        "erwartete_groesse": "klein",
        "erwartete_dauer_range": (25, 70),
    },
]


def pruefe_size_classifier_verfuegbar() -> bool:
    """Prüft ob der Grössenklassifikator trainiert wurde."""
    pkl = Path("models/size_classifier.pkl")
    return pkl.exists()


def pruefe_spez_modell_verfuegbar(groesse: str) -> bool:
    """Prüft ob ein spezialisiertes Laufzeit-Modell vorhanden ist."""
    pkl = Path(f"models/duration_model_{groesse}.pkl")
    return pkl.exists()


def formatiere_tabelle(ergebnisse: list[dict]) -> None:
    """Gibt eine formatierte Ergebnistabelle aus."""
    trenner_kurz = "─" * 100
    trenner_lang = "═" * 100

    print(f"\n{trenner_lang}")
    print("  EstimateIQ – Validierung Grössenklassifikator + Spezialisierte Modelle")
    print(trenner_lang)

    print(f"\n{'Projekt':<25} {'Erwartet':<10} {'Erkannt':<10} {'Konfid.':<9} "
          f"{'Modell':<14} {'Dauer':<10} {'Kosten (erw.)':<15} {'Status'}")
    print(trenner_kurz)

    gesamt   = len(ergebnisse)
    korrekt  = 0
    dauer_ok = 0

    for e in ergebnisse:
        # Status Symbole
        groesse_ok = e["erkannte_groesse"] == e["erwartete_groesse"]
        d_min, d_max = e["erwartete_dauer_range"]
        dauer_in_range = d_min <= e["dauer_tage"] <= d_max

        if groesse_ok:
            korrekt += 1
        if dauer_in_range:
            dauer_ok += 1

        groesse_status = "OK" if groesse_ok else "FEHLER"
        dauer_status   = "OK" if dauer_in_range else f"AUSSERHALB ({d_min}-{d_max})"
        gesamt_status  = "OK" if (groesse_ok and dauer_in_range) else "FEHLER"

        konfidenz_str = f"{e['konfidenz']:.0%}" if e["konfidenz"] > 0 else "n/a"
        dauer_str     = f"{e['dauer_tage']:.0f} Tage"
        kosten_str    = f"{e['kosten_expected']:,.0f} EUR"

        print(
            f"  {e['name']:<23} {e['erwartete_groesse']:<10} {e['erkannte_groesse']:<10} "
            f"{konfidenz_str:<9} {e['modell_genutzt']:<14} {dauer_str:<10} "
            f"{kosten_str:<15} [{gesamt_status}]"
        )
        if not groesse_ok:
            print(f"    {'':25} Grössenklasse: erwartet {e['erwartete_groesse']}, "
                  f"erkannt {e['erkannte_groesse']}")
        if not dauer_in_range:
            print(f"    {'':25} Dauer ausserhalb: {e['dauer_tage']:.0f} Tage "
                  f"(erwartet {d_min}–{d_max} Tage)")

    print(trenner_kurz)
    print(f"\n  Grössenklassifikator: {korrekt}/{gesamt} korrekt "
          f"({korrekt/gesamt:.0%})")
    print(f"  Dauer im erwarteten Bereich: {dauer_ok}/{gesamt} "
          f"({dauer_ok/gesamt:.0%})")
    print(f"\n{trenner_lang}\n")


def validiere() -> None:
    """Führt die Validierung für alle Testprojekte durch."""

    # Klassifikator-Status
    if pruefe_size_classifier_verfuegbar():
        logger.info("[Validierung] Grössenklassifikator gefunden.")
        from estimateiq.models.size_classifier import predict_proba as _proba
        klassifikator_aktiv = True
    else:
        logger.warning(
            "[Validierung] Grössenklassifikator NICHT gefunden "
            "(models/size_classifier.pkl fehlt). "
            "Bitte zuerst: python train.py --only size"
        )
        klassifikator_aktiv = False

    # Pipeline laden
    from estimateiq.models.estimate_pipeline import estimate

    ergebnisse = []

    for tp in TESTPROJEKTE:
        name        = tp["name"]
        beschreibung = tp["beschreibung"]
        region      = tp["region"]

        # 1. Grössenklassifikation
        if klassifikator_aktiv:
            try:
                proba_liste = _proba([beschreibung])
                proba       = proba_liste[0]
                erkannte_groesse = max(proba, key=proba.get)
                konfidenz        = proba[erkannte_groesse]
                proba_str = (f"klein={proba.get('klein',0):.2f} "
                             f"mittel={proba.get('mittel',0):.2f} "
                             f"gross={proba.get('gross',0):.2f}")
            except Exception as exc:
                logger.warning("[Validierung] Klassifikator-Fehler bei '%s': %s", name, exc)
                erkannte_groesse = "mittel"
                konfidenz        = 0.0
                proba_str        = "n/a"
        else:
            erkannte_groesse = "mittel"
            konfidenz        = 0.0
            proba_str        = "n/a (Modell fehlt)"

        # Welches Dauermodell würde genutzt?
        if pruefe_spez_modell_verfuegbar(erkannte_groesse):
            modell_genutzt = f"spez._{erkannte_groesse}"
        else:
            modell_genutzt = "generisch"

        # 2. Pipeline-Schätzung (mit Auto-Klassifikation)
        try:
            ergebnis = estimate(
                beschreibung=beschreibung,
                region=region,
                projekt_groesse_auto=True,
            )
            dauer_tage       = ergebnis.dauer_tage
            kosten_expected  = ergebnis.kosten_expected
            pipeline_groesse = ergebnis.projekt_groesse
        except Exception as exc:
            logger.warning("[Validierung] Pipeline-Fehler bei '%s': %s", name, exc)
            dauer_tage       = 0.0
            kosten_expected  = 0.0
            pipeline_groesse = erkannte_groesse

        # Logging für dieses Testprojekt
        logger.info(
            "[Validierung] %s: erkannt=%s (%.0f%%) | erwartet=%s | "
            "Dauer=%.0f Tage | Kosten=%.0f EUR | Modell=%s",
            name, erkannte_groesse, konfidenz * 100,
            tp["erwartete_groesse"],
            dauer_tage, kosten_expected, modell_genutzt,
        )
        logger.debug("[Validierung] %s Wahrscheinlichkeiten: %s", name, proba_str)

        ergebnisse.append({
            "name":                 name,
            "beschreibung":         beschreibung,
            "erwartete_groesse":    tp["erwartete_groesse"],
            "erkannte_groesse":     erkannte_groesse,
            "konfidenz":            konfidenz,
            "modell_genutzt":       modell_genutzt,
            "dauer_tage":           dauer_tage,
            "kosten_expected":      kosten_expected,
            "erwartete_dauer_range": tp["erwartete_dauer_range"],
        })

    # Ergebnistabelle ausgeben
    formatiere_tabelle(ergebnisse)

    # Exit-Code: 0 wenn alle Grössenklassen korrekt
    korrekt = sum(1 for e in ergebnisse if e["erkannte_groesse"] == e["erwartete_groesse"])
    if not klassifikator_aktiv:
        logger.warning("[Validierung] Grössenklassifikator nicht trainiert – keine sinnvolle Validierung möglich.")
        sys.exit(0)
    elif korrekt == len(ergebnisse):
        logger.info("[Validierung] Alle %d Grössenklassen korrekt erkannt.", korrekt)
        sys.exit(0)
    else:
        logger.warning(
            "[Validierung] %d/%d Grössenklassen korrekt – bitte Modell prüfen.",
            korrekt, len(ergebnisse),
        )
        sys.exit(1)


if __name__ == "__main__":
    validiere()
