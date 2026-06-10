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
  8. Metriken ausgeben

Verwendung:
  python train.py [--only MODEL]

Optionen:
  --only v1        Nur Cost Model v1
  --only v2        Nur Cost Model v2
  --only v3        Nur Cost Model v3
  --only risk      Nur Risk Model
  --only duration  Nur Laufzeit-Modell (Stufe 1, zweistufige Pipeline)
  --only overhead  Nur Overhead-Modell (Stufe 2, zweistufige Pipeline)
  --only pipeline  Beide Pipeline-Modelle (duration + overhead)
"""

import argparse
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

DATEN_PFAD = Path("data/processed/notices.parquet")


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

    print(f"\n{trenner}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="EstimateIQ Trainings-Workflow")
    parser.add_argument(
        "--only",
        choices=["v1", "v2", "v3", "risk", "duration", "overhead", "pipeline"],
        help="Nur ein bestimmtes Modell trainieren",
    )
    args = parser.parse_args()

    df = lade_daten()
    ergebnisse: dict = {}

    if args.only is None or args.only == "v1":
        ergebnisse["v1"] = trainiere_v1(df)

    if args.only is None or args.only == "v2":
        ergebnisse["v2"] = trainiere_v2(df)

    if args.only is None or args.only == "v3":
        ergebnisse["v3"] = trainiere_v3(df)

    if args.only is None or args.only == "risk":
        ergebnisse["risk"] = trainiere_risk(df)

    if args.only in (None, "duration", "pipeline"):
        ergebnisse["duration"] = trainiere_duration(df)

    if args.only in (None, "overhead", "pipeline"):
        ergebnisse["overhead"] = trainiere_overhead(df)

    drucke_zusammenfassung(ergebnisse)


if __name__ == "__main__":
    main()
