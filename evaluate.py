"""
evaluate.py – Backtesting der EstimateIQ Duration-Pipeline auf historischen TED-Daten.

Holdout-Strategie:
  Gleicher 80/20 Random-Split wie train.py (random_state=42, stratifiziert).
  Das Test-Set wurde beim Training nur für Early Stopping genutzt –
  kein Einfluss auf Hyperparameter-Optimierung → valides Holdout-Set.

Ausgabe:
  - R², MAE, MdAPE auf dem Holdout
  - models/evaluation_scatter.png (Scatter + Residual-Verteilung)
  - Top 10 größte Fehlschätzungen
"""

import logging
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DATA_PATH   = Path("data/processed/notices.parquet")
PLOT_PATH   = Path("models/evaluation_scatter.png")
DAUER_MIN   = 3
DAUER_MAX   = 3_650


def _lade_holdout() -> pd.DataFrame:
    """Reproduziert den 20 %-Holdout aus train.py exakt (random_state=42)."""
    df = pd.read_parquet(DATA_PATH)

    dauer = pd.to_numeric(df["dauer_tage"], errors="coerce")
    maske = dauer.notna() & dauer.ge(DAUER_MIN) & dauer.le(DAUER_MAX)
    df_sauber = df[maske].reset_index(drop=True)

    y = np.log1p(pd.to_numeric(df_sauber["dauer_tage"], errors="coerce").values)
    quartile = pd.qcut(pd.Series(y), q=4, labels=False, duplicates="drop").fillna(0).values
    _, idx_test = train_test_split(
        np.arange(len(df_sauber)), test_size=0.20, random_state=42, stratify=quartile
    )
    return df_sauber.iloc[idx_test].reset_index(drop=True)


def _plot(y_true: np.ndarray, y_pred: np.ndarray, r2: float, mdape: float) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # ── Scatter: Vorhergesagt vs. Tatsächlich (log) ──────────────────────────
    ax = axes[0]
    ax.scatter(y_true, y_pred, alpha=0.45, s=18, color="#2563eb", zorder=3)
    lim = [
        min(y_true.min(), y_pred.min()) * 0.85,
        max(y_true.max(), y_pred.max()) * 1.15,
    ]
    ax.plot(lim, lim, "r--", lw=1.5, label="Ideal (y = x)", zorder=4)
    # ×2 / ÷2 Band
    ax.plot(lim, [v * 2 for v in lim], color="#f97316", lw=1, ls=":", label="Faktor 2×")
    ax.plot(lim, [v / 2 for v in lim], color="#f97316", lw=1, ls=":")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Tatsächliche Laufzeit (Tage, log)")
    ax.set_ylabel("Vorhergesagte Laufzeit (Tage, log)")
    ax.set_title(
        f"Vorhergesagt vs. Tatsächlich\nR² = {r2:.3f}  |  MdAPE = {mdape:.1f} %",
        fontweight="bold",
    )
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    # ── Residual-Histogramm ───────────────────────────────────────────────────
    ax2 = axes[1]
    residuen = y_pred - y_true
    ax2.hist(residuen, bins=30, color="#f97316", alpha=0.75, edgecolor="white", linewidth=0.4)
    ax2.axvline(0, color="red", ls="--", lw=1.5, label="Kein Fehler")
    bias = float(np.mean(residuen))
    ax2.axvline(bias, color="navy", ls="--", lw=1.2, label=f"Bias: {bias:+.0f} Tage")
    ax2.set_xlabel("Residuum (Vorhergesagt − Tatsächlich, Tage)")
    ax2.set_ylabel("Anzahl Projekte")
    ax2.set_title("Residual-Verteilung", fontweight="bold")
    ax2.legend(fontsize=9)
    ax2.grid(alpha=0.3)

    plt.suptitle(
        "EstimateIQ – Duration Model · Holdout-Evaluation (20 % TED)",
        fontsize=13, fontweight="bold",
    )
    plt.tight_layout()
    PLOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(PLOT_PATH, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Scatter-Plot gespeichert: %s", PLOT_PATH)


def evaluate() -> dict:
    if not DATA_PATH.exists():
        logger.error("Datei nicht gefunden: %s", DATA_PATH)
        sys.exit(1)

    logger.info("Lade Holdout-Set (20 %% TED, gleicher Split wie train.py)...")
    df_test = _lade_holdout()
    logger.info("Holdout: %d Projekte", len(df_test))

    # ── Vorhersagen ───────────────────────────────────────────────────────────
    from estimateiq.models.duration_model import _feature_engineering, predict as dur_predict
    df_feat = _feature_engineering(df_test.copy())
    y_pred  = dur_predict(df_feat)
    y_true  = pd.to_numeric(df_test["dauer_tage"], errors="coerce").values.astype(float)

    # ── Metriken ──────────────────────────────────────────────────────────────
    r2    = r2_score(y_true, y_pred)
    mae   = mean_absolute_error(y_true, y_pred)
    mdape = float(np.median(np.abs(y_true - y_pred) / (y_true + 1e-6)) * 100)
    bias  = float(np.mean(y_pred - y_true))

    logger.info("")
    logger.info("══════════════════════════════════════════════")
    logger.info("  HOLDOUT-EVALUATION (n = %d)", len(df_test))
    logger.info("══════════════════════════════════════════════")
    logger.info("  R²            %8.4f", r2)
    logger.info("  MAE  (Tage)   %8.1f", mae)
    logger.info("  MdAPE         %7.1f %%", mdape)
    logger.info("  Bias          %+8.0f Tage", bias)
    logger.info("══════════════════════════════════════════════")

    _plot(y_true, y_pred, r2, mdape)

    # ── Top 10 Fehlschätzungen ────────────────────────────────────────────────
    fehler   = np.abs(y_pred - y_true)
    top10    = np.argsort(fehler)[-10:][::-1]

    logger.info("")
    logger.info("Top 10 größte Fehlschätzungen:")
    logger.info("%-55s %8s %8s %8s", "Beschreibung", "Tats.", "Vorher.", "Fehler")
    logger.info("─" * 83)
    for i in top10:
        desc = str(df_test.iloc[i].get("beschreibung", "") or "")[:52]
        logger.info(
            "%-55s %5.0f T  %5.0f T  %5.0f T",
            desc, y_true[i], y_pred[i], fehler[i],
        )

    return {"r2": r2, "mae": mae, "mdape": mdape, "bias": bias, "n": len(df_test)}


if __name__ == "__main__":
    evaluate()
