"""
Testet den regelbasierten Kalkulator mit 10 Beispielprojekten.

Ausführung:
    python test_kalkulation.py
"""

from estimateiq.models.kalkulator import kalkuliere_aus_text

TESTFAELLE = [
    # ── 5 Kernfälle ──────────────────────────────────────────────────────────
    {
        "nr": 1,
        "name": "Bad komplett 12m²",
        "beschreibung": (
            "Badezimmer 12m² Fliesen Boden und Wand, "
            "Dusche komplett, WC und Waschbecken erneuern"
        ),
        "region": "DE-sonstige",
        "erwartet": {"kosten_min": 8_000, "kosten_max": 15_000,
                     "dauer_min": 5, "dauer_max": 8},
    },
    {
        "nr": 2,
        "name": "Elektro EFH 100m²",
        "beschreibung": (
            "Elektroinstallation komplett 100m² Einfamilienhaus, "
            "Unterverteilung erneuern"
        ),
        "region": "DE-sonstige",
        "erwartet": {"kosten_min": 12_000, "kosten_max": 22_000,
                     "dauer_min": 5, "dauer_max": 12},  # Einzelarbeiter-Stunden; Team halbiert
    },
    {
        "nr": 3,
        "name": "Maler Wohnung Wände + Decken",
        "beschreibung": (
            "Wände streichen 120m² Innenbereich, "
            "Decken streichen 80m², "
            "200m² spachteln und glätten"
        ),
        "region": "DE-sonstige",
        "erwartet": {"kosten_min": 6_000, "kosten_max": 12_000,
                     "dauer_min": 5, "dauer_max": 10},
    },
    {
        "nr": 4,
        "name": "Wärmepumpe Luft-Wasser",
        "beschreibung": "Wärmepumpe Luftquelle installieren Einfamilienhaus",
        "region": "DE-sonstige",
        "erwartet": {"kosten_min": 18_000, "kosten_max": 38_000,
                     "dauer_min": 3, "dauer_max": 7},
    },
    {
        "nr": 5,
        "name": "Dachausbau 75m² komplett",
        "beschreibung": (
            "Dachausbau 75m²: Dachstuhl erneuern, Dachdämmung 75m², "
            "Trockenbau Decke und Wände, Parkett verlegen, "
            "Elektroinstallation"
        ),
        "region": "DE-sonstige",
        "erwartet": {"kosten_min": 45_000, "kosten_max": 80_000,
                     "dauer_min": 20, "dauer_max": 50},
    },
    # ── 5 Bonusfälle ─────────────────────────────────────────────────────────
    {
        "nr": 6,
        "name": "Parkett verlegen 80m²",
        "beschreibung": "Parkett verlegen 80m² Wohnzimmer und Schlafzimmer",
        "region": "DE-sonstige",
        "erwartet": {"kosten_min": 4_000, "kosten_max": 11_000,
                     "dauer_min": 3, "dauer_max": 7},
    },
    {
        "nr": 7,
        "name": "Gasheizung Tausch NRW",
        "beschreibung": "Gasheizung komplett erneuern, Brennwertkessel tauschen",
        "region": "DE-NW",
        "erwartet": {"kosten_min": 8_000, "kosten_max": 22_000,
                     "dauer_min": 2, "dauer_max": 6},
    },
    {
        "nr": 8,
        "name": "Trockenbau Büro 40m²",
        "beschreibung": (
            "Trockenbau 40m² Wände und 40m² abgehängte Decke Bürofläche"
        ),
        "region": "DE-sonstige",
        "erwartet": {"kosten_min": 3_000, "kosten_max": 9_000,
                     "dauer_min": 3, "dauer_max": 8},
    },
    {
        "nr": 9,
        "name": "Fliesen Bad München 15m²",
        "beschreibung": (
            "Badezimmer 15m² Bodenfliesen und Wandfliesen, "
            "schwimmender Estrich"
        ),
        "region": "DE-BY",
        "erwartet": {"kosten_min": 5_000, "kosten_max": 14_000,
                     "dauer_min": 3, "dauer_max": 8},
    },
    {
        "nr": 10,
        "name": "WDVS Fassade 120m²",
        "beschreibung": "Fassadendämmung WDVS 120m² Außenwand",
        "region": "DE-sonstige",
        "erwartet": {"kosten_min": 8_000, "kosten_max": 20_000,
                     "dauer_min": 4, "dauer_max": 10},
    },
]


def _check(wert: float, lo: float, hi: float) -> str:
    return "✓" if lo <= wert <= hi else "✗"


def drucke_ergebnis(nr: int, name: str, ergebnis: dict, erwartet: dict) -> bool:
    trennlinie = "─" * 68

    print(f"\n{trennlinie}")
    print(f"  [{nr:02d}] {name}  │  Region: {ergebnis['region']}")
    print(trennlinie)

    if not ergebnis["erkannte_positionen_roh"]:
        print("  ⚠️  Keine Positionen erkannt!")
        return False

    print(f"  {'Position':<30} {'Menge':>7}  {'h':>6}  {'Lohn':>8}  {'Mat.':>8}  {'∑':>9}")
    print(f"  {'─'*30} {'─'*7}  {'─'*6}  {'─'*8}  {'─'*8}  {'─'*9}")

    for p in ergebnis["positionen"]:
        print(
            f"  {p['position']:<30} {p['menge']:>6.1f}{p['einheit'][0]}  "
            f"{p['stunden']:>5.1f}h  "
            f"{p['lohn']:>7,.0f}€  "
            f"{p['material']:>7,.0f}€  "
            f"{p['gesamt']:>8,.0f}€"
        )

    print(f"  {'─'*30} {'─'*7}  {'─'*6}  {'─'*8}  {'─'*8}  {'─'*9}")
    print(
        f"  {'GESAMT':<30}          "
        f"{ergebnis['gesamt_stunden']:>5.1f}h  "
        f"{ergebnis['lohnkosten']:>7,.0f}€  "
        f"{ergebnis['materialkosten']:>7,.0f}€"
    )
    print(
        f"  Aufschläge (31%): {ergebnis['aufschlaege']:>44,.0f}€"
    )
    print(f"  {'─'*60}")

    k_erw  = ergebnis["kosten_erwartet"]
    k_min  = ergebnis["kosten_min"]
    k_max  = ergebnis["kosten_max"]
    d_tage = ergebnis["dauer_tage"]

    k_check = _check(k_erw, erwartet["kosten_min"], erwartet["kosten_max"])
    d_check = _check(d_tage, erwartet["dauer_min"], erwartet["dauer_max"])

    print(f"  Kosten  erwartet: {k_erw:>10,.0f}€   Bandbreite: {k_min:,.0f}€–{k_max:,.0f}€")
    print(
        f"  Zielbereich: {erwartet['kosten_min']:,.0f}€–{erwartet['kosten_max']:,.0f}€  "
        f"{k_check}"
    )
    print(
        f"  Dauer   erwartet: {d_tage:>7.1f} Tage  "
        f"(min {ergebnis['dauer_min_tage']:.1f} / max {ergebnis['dauer_max_tage']:.1f})"
    )
    print(
        f"  Zielbereich: {erwartet['dauer_min']}–{erwartet['dauer_max']} Tage  "
        f"{d_check}"
    )

    ok = k_check == "✓" and d_check == "✓"
    print(f"  {'→ BESTANDEN' if ok else '→ ABWEICHUNG (Zeitwerte ggf. kalibrieren)'}")
    return ok


def main() -> None:
    bestanden = 0
    gesamt    = len(TESTFAELLE)

    for fall in TESTFAELLE:
        ergebnis = kalkuliere_aus_text(fall["beschreibung"], region=fall["region"])
        ok = drucke_ergebnis(
            fall["nr"], fall["name"], ergebnis, fall["erwartet"]
        )
        if ok:
            bestanden += 1

    trennlinie = "═" * 68
    print(f"\n{trennlinie}")
    print(f"  Ergebnis: {bestanden}/{gesamt} Testfälle bestanden")
    print(trennlinie)


if __name__ == "__main__":
    main()
