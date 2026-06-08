"""
EstimateIQ – vollständiger Trainings-Workflow.

Ablauf:
  1. Vorverarbeitete Daten laden (data/processed/notices.parquet)
  2. BERT-Features extrahieren (bert_extractor.anreichere_dataframe)
  3. Cost Model v1 trainieren  (nur numerische Features, schnell)
  4. Cost Model v2 trainieren  (+ BERT-Features)
  5. Risk Model trainieren
  6. Alle Metriken zusammenfassen

Verwendung:
  python train.py [--skip-bert] [--only MODEL]

Optionen:
  --skip-bert   Überspringt BERT-Anreicherung; trainiert nur v1 + Risk
  --only v1     Trainiert nur Cost Model v1
  --only v2     Trainiert nur Cost Model v2 (setzt BERT-Anreicherung voraus)
  --only risk   Trainiert nur das Risk Model
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DATEN_PFAD = Path("data/processed/notices.parquet")


def lade_daten() -> pd.DataFrame:
    if not DATEN_PFAD.exists():
        logger.error("Vorverarbeitete Daten nicht gefunden: %s", DATEN_PFAD)
        logger.error("Bitte zuerst ausführen: python -m estimateiq.data.preprocess")
        sys.exit(1)
    df = pd.read_parquet(DATEN_PFAD)
    logger.info("Daten geladen: %d Zeilen aus %s", len(df), DATEN_PFAD)
    return df


def bert_anreichern(df: pd.DataFrame) -> pd.DataFrame:
    """BERT-Features zu allen Zeilen hinzufügen."""
    from estimateiq.models.bert_extractor import anreichere_dataframe
    logger.info("Starte BERT-Anreicherung (%d Texte)...", len(df))
    t0 = time.time()
    df = anreichere_dataframe(df)
    dauer = time.time() - t0
    logger.info("BERT-Anreicherung abgeschlossen in %.0f Sekunden.", dauer)
    return df


def trainiere_v1(df: pd.DataFrame) -> dict:
    from estimateiq.models.cost_model import train
    logger.info("─" * 50)
    logger.info("Trainiere Cost Model v1 (numerische Features)...")
    return train(df)


def trainiere_v2(df: pd.DataFrame) -> dict:
    from estimateiq.models.cost_model_v2 import train
    logger.info("─" * 50)
    logger.info("Trainiere Cost Model v2 (BERT-Features)...")
    return train(df)


def trainiere_risk(df: pd.DataFrame) -> dict:
    from estimateiq.models.risk_model import train
    logger.info("─" * 50)
    logger.info("Trainiere Risk Model (Random Forest)...")
    return train(df)


def drucke_zusammenfassung(ergebnisse: dict) -> None:
    trenner = "═" * 60
    print(f"\n{trenner}")
    print("  EstimateIQ – Trainings-Zusammenfassung")
    print(trenner)

    if "v1" in ergebnisse:
        m = ergebnisse["v1"]
        print(f"\n  Cost Model v1 (numerisch)")
        print(f"    RMSE (EUR):    {m['rmse_eur']:>14,.0f} €")
        print(f"    R²:            {m['r2']:>14.4f}")
        print(f"    RMSE (log):    {m['rmse_log']:>14.4f}")
        print(f"    Train/Test:    {m['n_train']:,} / {m['n_test']:,}")

    if "v2" in ergebnisse:
        m = ergebnisse["v2"]
        print(f"\n  Cost Model v2 (+ BERT-Features)")
        print(f"    RMSE (EUR):    {m['rmse_eur']:>14,.0f} €")
        print(f"    R²:            {m['r2']:>14.4f}")
        print(f"    RMSE (log):    {m['rmse_log']:>14.4f}")
        print(f"    Train/Test:    {m['n_train']:,} / {m['n_test']:,}")
        if "v1" in ergebnisse:
            verbesserung = ergebnisse["v2"]["r2"] - ergebnisse["v1"]["r2"]
            print(f"    R²-Verbesserung ggü. v1: {verbesserung:+.4f}")

    if "risk" in ergebnisse:
        m = ergebnisse["risk"]
        print(f"\n  Risk Model (Random Forest)")
        print(f"    Accuracy:      {m['accuracy']:>14.1%}")
        print(f"    Train/Test:    {m['n_train']:,} / {m['n_val']:,}")
        print(f"    Klassen:       {m['classes']}")

    print(f"\n{trenner}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="EstimateIQ Trainings-Workflow")
    parser.add_argument(
        "--skip-bert",
        action="store_true",
        help="BERT-Anreicherung überspringen (nur v1 + Risk trainieren)",
    )
    parser.add_argument(
        "--only",
        choices=["v1", "v2", "risk"],
        help="Nur ein bestimmtes Modell trainieren",
    )
    args = parser.parse_args()

    df = lade_daten()
    ergebnisse: dict = {}

    # BERT-Anreicherung – benötigt für v2
    df_bert = None
    braucht_bert = not args.skip_bert and args.only in (None, "v2")
    if braucht_bert:
        df_bert = bert_anreichern(df)

    # Trainings-Läufe
    if args.only is None or args.only == "v1":
        ergebnisse["v1"] = trainiere_v1(df)

    if (args.only is None or args.only == "v2") and not args.skip_bert:
        df_fuer_v2 = df_bert if df_bert is not None else bert_anreichern(df)
        ergebnisse["v2"] = trainiere_v2(df_fuer_v2)

    if args.only is None or args.only == "risk":
        ergebnisse["risk"] = trainiere_risk(df)

    drucke_zusammenfassung(ergebnisse)


if __name__ == "__main__":
    main()
