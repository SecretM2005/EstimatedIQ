"""
EstimateIQ – vollständiger Trainings-Workflow.

Ablauf:
  1. Vorverarbeitete Daten laden (data/processed/notices.parquet)
  2. BERT-Embeddings berechnen (mit Disk-Cache – wird nur einmal berechnet)
  3. BERT-Scalar-Features ableiten (projekttyp_bert, komplexitaet, ...)
  4. Cost Model v1 trainieren  (4 numerische Features, schnell)
  5. Cost Model v2 trainieren  (+ 50 PCA-Komponenten aus BERT-Embeddings)
  6. Risk Model trainieren
  7. Alle Metriken zusammenfassen

Verwendung:
  python train.py [--skip-bert] [--only MODEL]

Optionen:
  --skip-bert   Überspringt BERT; trainiert nur v1 + Risk (kein Cache nötig)
  --only v1     Trainiert nur Cost Model v1
  --only v2     Trainiert nur Cost Model v2 (nutzt Embedding-Cache falls vorhanden)
  --only risk   Trainiert nur das Risk Model
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np
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


def bert_anreichern(df: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    """
    BERT nur für Zeilen mit bekanntem Budget berechnen (~33 % der Daten).
    Der inkrementelle Hash-Cache stellt sicher, dass bei neuen Jahrgängen
    nur die wirklich neuen Texte durch BERT gerechnet werden.

    Returns:
        (df_budget_angereichert, embeddings_matrix)
        – der zurückgegebene DataFrame enthält nur Zeilen mit budget_eur != NaN
    """
    from estimateiq.models.bert_extractor import anreichere_dataframe, berechne_embeddings_gecacht

    df_budget = df[df["budget_eur"].notna()].reset_index(drop=True)
    n_gesamt  = len(df)
    n_budget  = len(df_budget)
    logger.info(
        "BERT nur für Budget-Zeilen: %d/%d (%.0f%% der Daten)",
        n_budget, n_gesamt, 100 * n_budget / n_gesamt,
    )

    texte = df_budget["beschreibung"].fillna("").tolist()
    t0 = time.time()
    embeddings = berechne_embeddings_gecacht(texte)
    logger.info("Embeddings bereit in %.0f Sekunden.", time.time() - t0)

    t1 = time.time()
    df_angereichert = anreichere_dataframe(df_budget)
    logger.info("Scalar-Features abgeleitet in %.0f Sekunden.", time.time() - t1)

    return df_angereichert, embeddings


def trainiere_v1(df: pd.DataFrame) -> dict:
    from estimateiq.models.cost_model import train
    logger.info("─" * 50)
    logger.info("Trainiere Cost Model v1 (numerische Features)...")
    return train(df)


def trainiere_v2(df: pd.DataFrame, embeddings: np.ndarray) -> dict:
    from estimateiq.models.cost_model_v2 import train
    logger.info("─" * 50)
    logger.info("Trainiere Cost Model v2 (PCA-Embeddings + numerisch, %d Features gesamt)...",
                50 + 2 + 6)
    return train(df, embeddings=embeddings)


def trainiere_risk(df: pd.DataFrame) -> dict:
    from estimateiq.models.risk_model import train
    logger.info("─" * 50)
    logger.info("Trainiere Risk Model (Random Forest)...")
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
        n_pca = m.get("n_pca_features", "?")
        n_feat = m.get("n_features", "?")
        print(f"\n  Cost Model v2 (PCA-Embeddings, {n_feat} Features, {n_pca} PCA-Komp.)")
        print(f"    RMSE (EUR):    {m['rmse_eur']:>14,.0f} €")
        print(f"    R²:            {m['r2']:>14.4f}")
        print(f"    RMSE (log):    {m['rmse_log']:>14.4f}")
        print(f"    Train/Test:    {m['n_train']:,} / {m['n_test']:,}")
        if "v1" in ergebnisse:
            delta = m["r2"] - ergebnisse["v1"]["r2"]
            print(f"    R²-Verbesserung ggü. v1: {delta:+.4f}")

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
        help="BERT überspringen; trainiert nur v1 + Risk (kein Embedding-Cache nötig)",
    )
    parser.add_argument(
        "--only",
        choices=["v1", "v2", "risk"],
        help="Nur ein bestimmtes Modell trainieren",
    )
    args = parser.parse_args()

    df = lade_daten()
    ergebnisse: dict = {}

    # BERT – benötigt für v2; Embeddings und Scalar-Features werden zusammen berechnet
    df_bert: pd.DataFrame | None = None
    embeddings: np.ndarray | None = None
    braucht_bert = not args.skip_bert and args.only in (None, "v2")

    if braucht_bert:
        df_bert, embeddings = bert_anreichern(df)

    # Trainings-Läufe
    if args.only is None or args.only == "v1":
        ergebnisse["v1"] = trainiere_v1(df)

    if (args.only is None or args.only == "v2") and not args.skip_bert:
        if df_bert is None or embeddings is None:
            df_bert, embeddings = bert_anreichern(df)
        ergebnisse["v2"] = trainiere_v2(df_bert, embeddings)

    if args.only is None or args.only == "risk":
        ergebnisse["risk"] = trainiere_risk(df)

    drucke_zusammenfassung(ergebnisse)


if __name__ == "__main__":
    main()
