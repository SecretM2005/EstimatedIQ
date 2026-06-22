"""
EstimateIQ – vollständiger Trainings-Workflow.

Ablauf:
  1. Vorverarbeitete Daten laden (data/processed/notices.parquet)
  2. Cost Model v1 trainieren  (4 numerische Features)
  3. Cost Model v2 trainieren  (TF-IDF + SVD Textfeatures, kein BERT nötig)
  4. Cost Model v3 trainieren  (v2 + neue Features, Huber-Loss)
  5. Risk Model trainieren
  6. [NEU] Laufzeit-Modell trainieren  (Stufe 1: ALLE Projekte mit dauer_tage)
  7. [NEU] Overhead-Modell trainieren  (Stufe 2: Projekte mit Budget)
  8. [NEU] Grössenklassifikator trainieren  (klein/mittel/gross)
  9. [NEU] Spezialisierte Laufzeit-Modelle  (klein/mittel/gross getrennt)
  10. Metriken ausgeben

Verwendung:
  python train.py [--only MODEL]

Optionen:
  --only v1           Nur Cost Model v1
  --only v2           Nur Cost Model v2
  --only v3           Nur Cost Model v3
  --only risk         Nur Risk Model
  --only duration     Nur Laufzeit-Modell (Stufe 1, zweistufige Pipeline)
  --only overhead     Nur Overhead-Modell (Stufe 2, zweistufige Pipeline)
  --only pipeline     Alle drei Ensemble-Modelle (v3 + duration + overhead)
  --only size         Grössenklassifikator (fetch_size_labels + size_classifier)
  --only specialized  Spezialisierte Laufzeit-Modelle (klein/mittel/gross)
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DATEN_PFAD      = Path("data/processed/notices.parquet")
SIZE_LABELS_PFAD = Path("data/size_labels.jsonl")


def lade_daten() -> pd.DataFrame:
    if not DATEN_PFAD.exists():
        logger.error("Vorverarbeitete Daten nicht gefunden: %s", DATEN_PFAD)
        logger.error("Bitte zuerst ausführen: python -m estimateiq.data.preprocess")
        sys.exit(1)
    df = pd.read_parquet(DATEN_PFAD)
    logger.info("Daten geladen: %d Zeilen aus %s", len(df), DATEN_PFAD)
    return df


def trainiere_v1(df: pd.DataFrame) -> dict:
    from estimateiq.models.cost_model import train
    logger.info("─" * 50)
    logger.info("Trainiere Cost Model v1 (numerische Features)...")
    return train(df)


def trainiere_v2(df: pd.DataFrame) -> dict:
    from estimateiq.models.cost_model_v2 import train
    logger.info("─" * 50)
    logger.info("Trainiere Cost Model v2 (TF-IDF + SVD, kein BERT)...")
    return train(df)


def trainiere_v3(df: pd.DataFrame) -> dict:
    from estimateiq.models.cost_model_v3 import train
    logger.info("─" * 50)
    logger.info("Trainiere Cost Model v3 (neue Features: Wortanzahl, Deadline, Tagesrate, 86 Features)...")
    return train(df)


def trainiere_risk(df: pd.DataFrame) -> dict:
    from estimateiq.models.risk_model import train
    logger.info("─" * 50)
    logger.info("Trainiere Risk Model (Random Forest)...")
    return train(df)


def trainiere_duration(df: pd.DataFrame) -> dict:
    from estimateiq.models.duration_model import train
    logger.info("─" * 50)
    logger.info("Trainiere Laufzeit-Modell Stufe 1 (ALLE Projekte mit dauer_tage, TF-IDF+SVD)...")
    return train(df)


def trainiere_overhead(df: pd.DataFrame) -> dict:
    from estimateiq.models.overhead_model import train
    logger.info("─" * 50)
    logger.info("Trainiere Overhead-Modell Stufe 2 (Projekte mit Budget+Laufzeit)...")
    return train(df)


def trainiere_size(df: pd.DataFrame) -> dict:
    """
    Erstellt Grössenklassen-Labels aus allen Quellen und trainiert den Klassifikator.

    Schritte:
      1. estimateiq.data.fetch_size_labels: Labels aus GitHub, TED und manuellen Daten
      2. estimateiq.models.size_classifier: XGBoost-Klassifikator auf den Labels
    """
    logger.info("─" * 50)
    logger.info("Trainiere Grössenklassifikator (klein/mittel/gross)...")

    # Schritt 1: Labels erstellen/aktualisieren
    from estimateiq.data.fetch_size_labels import erstelle_labels
    logger.info("[Size] Erstelle Labels aus allen Quellen...")
    erstelle_labels()

    # Schritt 2: Labels laden
    if not SIZE_LABELS_PFAD.exists():
        logger.error("[Size] Labels-Datei nicht gefunden: %s", SIZE_LABELS_PFAD)
        return {"fehler": "Labels-Datei nicht gefunden"}

    eintraege = []
    with SIZE_LABELS_PFAD.open("r", encoding="utf-8") as f:
        for zeile in f:
            zeile = zeile.strip()
            if zeile:
                try:
                    eintraege.append(json.loads(zeile))
                except json.JSONDecodeError:
                    pass

    if not eintraege:
        logger.error("[Size] Keine Labels in %s gefunden.", SIZE_LABELS_PFAD)
        return {"fehler": "Keine Labels"}

    df_labels = pd.DataFrame(eintraege)
    logger.info("[Size] %d Labels geladen.", len(df_labels))

    # Schritt 3: Klassifikator trainieren
    from estimateiq.models.size_classifier import train as _train_size
    return _train_size(df_labels)


def trainiere_spezialisiert(df: pd.DataFrame) -> dict:
    """
    Trainiert spezialisierte Laufzeit-Modelle für alle drei Grössenklassen:
      - klein  (14–90 Tage)
    - mittel (60–365 Tage)
    - gross  (180–730 Tage)
    """
    logger.info("─" * 50)
    logger.info("Trainiere spezialisierte Laufzeit-Modelle (klein/mittel/gross)...")

    from estimateiq.models.duration_model_klein  import train as train_klein
    from estimateiq.models.duration_model_mittel import train as train_mittel
    from estimateiq.models.duration_model_gross  import train as train_gross

    ergebnisse: dict[str, dict] = {}

    for name, train_fn in [("klein", train_klein), ("mittel", train_mittel), ("gross", train_gross)]:
        logger.info("[Spez.] Starte %s-Modell...", name)
        try:
            ergebnisse[name] = train_fn(df)
            logger.info("[Spez.] %s-Modell fertig.", name)
        except ValueError as exc:
            logger.warning("[Spez.] %s-Modell übersprungen: %s", name, exc)
            ergebnisse[name] = {"fehler": str(exc)}

    return ergebnisse


def drucke_zusammenfassung(ergebnisse: dict) -> None:
    trenner = "═" * 62
    print(f"\n{trenner}")
    print("  EstimateIQ – Trainings-Zusammenfassung")
    print(trenner)

    if "v1" in ergebnisse:
        m = ergebnisse["v1"]
        print(f"\n  Cost Model v1 (numerisch, 4 Features)")
        print(f"    RMSE (EUR):    {m['rmse_eur']:>14,.0f} €")
        print(f"    R²:            {m['r2']:>14.4f}")
        print(f"    RMSE (log):    {m['rmse_log']:>14.4f}")
        print(f"    Train/Test:    {m['n_train']:,} / {m['n_test']:,}")

    if "v2" in ergebnisse:
        m = ergebnisse["v2"]
        print(f"\n  Cost Model v2 (TF-IDF+SVD, {m.get('n_features','?')} Features)")
        print(f"    RMSE (EUR):    {m['rmse_eur']:>14,.0f} €")
        print(f"    R²:            {m['r2']:>14.4f}")
        print(f"    RMSE (log):    {m['rmse_log']:>14.4f}")
        print(f"    Train/Test:    {m['n_train']:,} / {m['n_test']:,}")
        if "v1" in ergebnisse:
            delta = m["r2"] - ergebnisse["v1"]["r2"]
            print(f"    R²-Verbesserung ggü. v1: {delta:+.4f}")

    if "v3" in ergebnisse:
        m = ergebnisse["v3"]
        print(f"\n  Cost Model v3 (TF-IDF+SVD+neue Features, {m.get('n_features','?')} Features)")
        print(f"    RMSE (EUR, gesamt): {m['rmse_eur']:>12,.0f} €")
        print(f"    RMSE (EUR, ≤p95):   {m['rmse_p95']:>12,.0f} €  "
              f"(p95={m.get('p95_budget_eur',0)/1e6:.1f} M €)")
        print(f"    R²  (gesamt):  {m['r2']:>14.4f}")
        print(f"    R²  (≤p95):    {m['r2_p95']:>14.4f}")
        print(f"    RMSE (log):    {m['rmse_log']:>14.4f}")
        print(f"    Train/Test:    {m['n_train']:,} / {m['n_test']:,}")
        if "v2" in ergebnisse:
            delta = m["r2"] - ergebnisse["v2"]["r2"]
            print(f"    R²-Verbesserung ggü. v2: {delta:+.4f}")

    if "risk" in ergebnisse:
        m = ergebnisse["risk"]
        print(f"\n  Risk Model (Random Forest)")
        print(f"    Accuracy:      {m['accuracy']:>14.1%}")
        print(f"    Train/Test:    {m['n_train']:,} / {m['n_val']:,}")
        print(f"    Klassen:       {m['classes']}")

    if "duration" in ergebnisse:
        m = ergebnisse["duration"]
        print(f"\n  Laufzeit-Modell Stufe 1 ({m.get('n_features','?')} Features)")
        print(f"    RMSE (Tage):   {m['rmse_tage']:>12.1f}")
        print(f"    MAE  (Tage):   {m['mae_tage']:>12.1f}")
        print(f"    R²  (linear):  {m['r2']:>12.4f}")
        print(f"    R²  (log):     {m['r2_log']:>12.4f}")
        print(f"    MdAPE:         {m['mape']:>11.1f}%")
        print(f"    Train/Test:    {m['n_train']:,} / {m['n_test']:,}  "
              f"(davon {m['n_mit_budget']:,} mit Budget)")

    if "overhead" in ergebnisse:
        m = ergebnisse["overhead"]
        print(f"\n  Tagespreis-Modell Stufe 2 (budget_eur / dauer_tage)")
        print(f"    RMSE (log):    {m['rmse_log']:>12.4f}")
        print(f"    R²  (log):     {m['r2_log']:>12.4f}")
        print(f"    Tagespreis Med: {m['overhead_median']:>10,.0f} €/Tag  "
              f"[{m['overhead_p25']:,.0f} – {m['overhead_p75']:,.0f} €/Tag]")
        print(f"    Train/Test:    {m['n_train']:,} / {m['n_test']:,}")
        print(f"    Residual CI:   p25={m['rq_p25']:+.3f}  p75={m['rq_p75']:+.3f}  "
              f"(×{abs(m['rq_p75'] - m['rq_p25']):.2f} Spread im log-Raum)")

    if "size" in ergebnisse:
        m = ergebnisse["size"]
        if "fehler" in m:
            print(f"\n  Grössenklassifikator – FEHLER: {m['fehler']}")
        else:
            print(f"\n  Grössenklassifikator (TF-IDF+SVD, {N_SVD_DISPLAY} SVD-Komponenten)")
            print(f"    Accuracy:      {m['accuracy']:>14.1%}")
            print(f"    Train/Test:    {m['n_train']:,} / {m['n_test']:,}")
            n_pc = m.get("n_per_class", {})
            print(f"    Klassen:       klein={n_pc.get('klein',0)}  "
                  f"mittel={n_pc.get('mittel',0)}  gross={n_pc.get('gross',0)}")

    if "spezialisiert" in ergebnisse:
        print(f"\n  Spezialisierte Laufzeit-Modelle")
        for groesse in ["klein", "mittel", "gross"]:
            m = ergebnisse["spezialisiert"].get(groesse, {})
            if "fehler" in m:
                print(f"    {groesse:<8}: FEHLER – {m['fehler']}")
            else:
                print(
                    f"    {groesse:<8}: RMSE={m.get('rmse_tage',0):>6.1f} Tage  "
                    f"R²={m.get('r2',0):>6.4f}  "
                    f"Train/Test={m.get('n_train',0):,}/{m.get('n_test',0):,}  "
                    f"n={m.get('n_gesamt',0):,}"
                )

    print(f"\n{trenner}\n")


# Konstante für Zusammenfassung (spiegelt N_SVD aus size_classifier.py)
N_SVD_DISPLAY = 30


def main() -> None:
    parser = argparse.ArgumentParser(description="EstimateIQ Trainings-Workflow")
    parser.add_argument(
        "--only",
        choices=["v1", "v2", "v3", "risk", "duration", "overhead", "pipeline",
                 "size", "specialized"],
        help="Nur ein bestimmtes Modell trainieren",
    )
    args = parser.parse_args()

    ergebnisse: dict = {}

    # Size-Klassifikator und spezialisierte Modelle benötigen df nicht zwingend,
    # aber die spezialisierten Modelle brauchen die prozessierten Daten.
    if args.only in ("size",):
        # Kein df nötig (Labels werden aus mehreren Quellen gesammelt)
        df = pd.DataFrame()  # Platzhalter
        ergebnisse["size"] = trainiere_size(df)
        drucke_zusammenfassung(ergebnisse)
        return

    # Alle anderen Modi: df laden
    df = lade_daten()

    if args.only is None or args.only == "v1":
        ergebnisse["v1"] = trainiere_v1(df)

    if args.only is None or args.only == "v2":
        ergebnisse["v2"] = trainiere_v2(df)

    if args.only in (None, "v3", "pipeline"):
        ergebnisse["v3"] = trainiere_v3(df)

    if args.only is None or args.only == "risk":
        ergebnisse["risk"] = trainiere_risk(df)

    if args.only in (None, "duration", "pipeline"):
        ergebnisse["duration"] = trainiere_duration(df)

    if args.only in (None, "overhead", "pipeline"):
        ergebnisse["overhead"] = trainiere_overhead(df)

    if args.only == "specialized":
        ergebnisse["spezialisiert"] = trainiere_spezialisiert(df)

    # Im vollständigen Durchlauf: Size + Spezialisiert ebenfalls trainieren
    if args.only is None:
        ergebnisse["size"] = trainiere_size(df)
        ergebnisse["spezialisiert"] = trainiere_spezialisiert(df)

    drucke_zusammenfassung(ergebnisse)


if __name__ == "__main__":
    main()
