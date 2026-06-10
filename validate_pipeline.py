"""
EstimateIQ – Vollständige Pipeline-Validierung.

Testet die zweistufige Kostenschätzungs-Pipeline gegen echte TED-Budgets.
Benötigt: data/processed/notices.parquet + trainierte Modelle.

Metriken:
  RMSE  – Root Mean Squared Error (sensitiv für Ausreißer)
  MAE   – Mean Absolute Error (robust)
  R²    – Erklärte Varianz (1.0 = perfekt, 0.0 = Mittelwert-Baseline)
  MAPE  – Mean Absolute Percentage Error
  MdAPE – Median Absolute Percentage Error (robustestes Maß)
  CovP50 – Anteil Projekte bei denen budget_eur ≤ kosten_expected × 1.0
           (Überschreitungsrate)

Verwendung:
  python validate_pipeline.py
  python validate_pipeline.py --n 200      # Zufallsstichprobe 200 Projekte
  python validate_pipeline.py --region AT  # Nur österreichische Projekte
  python validate_pipeline.py --plot       # Scatter-Plot speichern
"""

import argparse
import logging
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DATEN_PFAD = Path("data/processed/notices.parquet")


# ---------------------------------------------------------------------------
# Metriken
# ---------------------------------------------------------------------------

def berechne_metriken(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """Berechnet alle relevanten Regressionsmetriken."""
    eps   = 1.0  # Division-durch-Null Schutz
    fehler = y_pred - y_true
    ape    = np.abs(fehler) / (y_true + eps) * 100

    from sklearn.metrics import mean_squared_error, r2_score, mean_absolute_error

    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    mae  = float(mean_absolute_error(y_true, y_pred))
    r2   = float(r2_score(y_true, y_pred))
    mape = float(ape.mean())
    mdape = float(np.median(ape))

    # Kalibrierungs-Metriken: Wie oft liegt wahrer Wert im geschätzten Intervall?
    return {
        "rmse":   rmse,
        "mae":    mae,
        "r2":     r2,
        "mape":   mape,
        "mdape":  mdape,
    }


def berechne_intervall_metriken(
    y_true: np.ndarray,
    y_low: np.ndarray,
    y_high: np.ndarray,
) -> dict:
    """Berechnet Überdeckungsrate der Konfidenzintervalle."""
    ueberdeckung = ((y_true >= y_low) & (y_true <= y_high)).mean()
    breite_relativ = ((y_high - y_low) / (y_true + 1)).mean()
    return {
        "ueberdeckung":       float(ueberdeckung),
        "intervall_breite":   float(breite_relativ),
    }


# ---------------------------------------------------------------------------
# Haupt-Validierungslogik
# ---------------------------------------------------------------------------

def validiere_pipeline(
    df: pd.DataFrame,
    mit_plot: bool = False,
    ausgabe_pfad: Path = Path("models/validation_scatter.png"),
) -> dict:
    from estimateiq.models.estimate_pipeline import estimate_batch

    logger.info("[Validierung] Starte Batch-Schätzung für %d Projekte...", len(df))

    # verwende_tatsaechliche_dauer=False: echte End-to-End-Validierung, kein Datenleck
    ergebnisse = estimate_batch(df, verwende_tatsaechliche_dauer=False)

    # Ergebnisse aufsammeln
    zeilen = []
    for ergebnis, (_, zeile) in zip(ergebnisse, df.iterrows()):
        if ergebnis is None:
            continue
        zeilen.append({
            "budget_eur":        float(zeile["budget_eur"]),
            "kosten_expected":   ergebnis.kosten_expected,
            "kosten_low":        ergebnis.kosten_low,
            "kosten_high":       ergebnis.kosten_high,
            "dauer_tage_pred":   ergebnis.dauer_tage,
            "dauer_tage_actual": float(zeile["dauer_tage"]) if pd.notna(zeile.get("dauer_tage")) else None,
            "tagespreis_p50":    ergebnis.tagespreis_p50,
            "personalkosten":    ergebnis.personalkosten,
            "projekttyp":        ergebnis.projekttyp,
            "region":            ergebnis.region,
            "datenquelle":       str(zeile.get("datenquelle", "ted")),
        })

    if not zeilen:
        logger.error("[Validierung] Keine Ergebnisse erzeugt.")
        return {}

    df_res = pd.DataFrame(zeilen)
    y_true = df_res["budget_eur"].values.astype(np.float64)
    y_pred = df_res["kosten_expected"].values.astype(np.float64)
    y_low  = df_res["kosten_low"].values.astype(np.float64)
    y_high = df_res["kosten_high"].values.astype(np.float64)

    metriken     = berechne_metriken(y_true, y_pred)
    iv_metriken  = berechne_intervall_metriken(y_true, y_low, y_high)
    metriken.update(iv_metriken)

    # Laufzeit-Metriken (wo verfügbar)
    hat_actual_dauer = df_res["dauer_tage_actual"].notna()
    if hat_actual_dauer.sum() > 10:
        dauer_m = berechne_metriken(
            df_res.loc[hat_actual_dauer, "dauer_tage_actual"].values.astype(np.float64),
            df_res.loc[hat_actual_dauer, "dauer_tage_pred"].values.astype(np.float64),
        )
        metriken["dauer_r2"]    = dauer_m["r2"]
        metriken["dauer_mdape"] = dauer_m["mdape"]
        metriken["dauer_n"]     = int(hat_actual_dauer.sum())

    # Per-Quelle Metriken
    per_quelle: dict[str, dict] = {}
    for quelle, gruppe in df_res.groupby("datenquelle"):
        if len(gruppe) < 5:
            continue
        per_quelle[str(quelle)] = berechne_metriken(
            gruppe["budget_eur"].values.astype(np.float64),
            gruppe["kosten_expected"].values.astype(np.float64),
        )

    metriken["n"]          = len(df_res)
    metriken["per_quelle"] = per_quelle

    if mit_plot:
        _erstelle_scatter_plot(df_res, ausgabe_pfad)

    return metriken


# ---------------------------------------------------------------------------
# Scatter-Plot
# ---------------------------------------------------------------------------

def _erstelle_scatter_plot(df_res: pd.DataFrame, pfad: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    y_true = df_res["budget_eur"].values / 1e6
    y_pred = df_res["kosten_expected"].values / 1e6
    p95    = np.percentile(y_true, 95)

    # --- Links: gesamte Range ---
    sc = axes[0].scatter(y_true, y_pred, alpha=0.35, s=15,
                         c=np.log10(y_true + 1), cmap="viridis")
    plt.colorbar(sc, ax=axes[0], label="log₁₀(Budget, Mio €)")
    lim = max(y_true.max(), y_pred.max()) * 1.05
    axes[0].plot([0, lim], [0, lim], "r--", linewidth=1.5, label="Perfekte Schätzung")
    axes[0].set_xlabel("Tatsächliches Budget (Mio €)")
    axes[0].set_ylabel("Geschätzte Kosten (Mio €)")
    axes[0].set_title("Pipeline-Validierung: Gesamt", fontweight="bold")
    axes[0].legend()

    # --- Rechts: ≤p95 (ohne extreme Ausreißer) ---
    maske_p95 = y_true <= p95
    axes[1].scatter(y_true[maske_p95], y_pred[maske_p95], alpha=0.4, s=20, color="#2563eb")
    lim95 = p95 * 1.05
    axes[1].plot([0, lim95], [0, lim95], "r--", linewidth=1.5, label="Perfekte Schätzung")
    axes[1].set_xlabel("Tatsächliches Budget (Mio €)")
    axes[1].set_ylabel("Geschätzte Kosten (Mio €)")
    axes[1].set_title(f"Pipeline-Validierung: ≤p95 ({p95:.1f} Mio €)", fontweight="bold")
    axes[1].legend()

    plt.suptitle("EstimateIQ – Zweistufige Pipeline: Vorhersage vs. Tatsächliches Budget",
                 fontsize=13, fontweight="bold")
    plt.tight_layout()
    pfad.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(pfad, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("[Validierung] Scatter-Plot: %s", pfad)


# ---------------------------------------------------------------------------
# Ausgabe-Formatierung
# ---------------------------------------------------------------------------

def drucke_ergebnisse(metriken: dict) -> None:
    n      = metriken.get("n", 0)
    trenner = "═" * 66
    print(f"\n{trenner}")
    print("  EstimateIQ – Pipeline-Validierung (n=%d Projekte)" % n)
    print(trenner)

    print(f"\n  Kostenschätzung (budget_eur vs. kosten_expected):")
    print(f"    RMSE:     {metriken['rmse']/1e6:>10.2f} Mio €")
    print(f"    MAE:      {metriken['mae']/1e6:>10.2f} Mio €")
    print(f"    R²:       {metriken['r2']:>10.4f}")
    print(f"    MAPE:     {metriken['mape']:>9.1f}%")
    print(f"    MdAPE:    {metriken['mdape']:>9.1f}%  ← robustestes Maß")
    print(f"\n  Konfidenzintervall (p25–p75):")
    print(f"    Überdeckungsrate:  {metriken['ueberdeckung']:>7.1%}  "
          f"(Anteil Projekte bei denen budget im p25–p75-Band liegt)")
    print(f"    Bandbreite (rel.): {metriken['intervall_breite']:>7.1%}  "
          f"(p75–p25 relativ zum Budget)")

    if "dauer_r2" in metriken:
        print(f"\n  Laufzeit-Modell (n={metriken['dauer_n']} mit tatsächl. dauer_tage):")
        print(f"    R²:    {metriken['dauer_r2']:>10.4f}")
        print(f"    MdAPE: {metriken['dauer_mdape']:>9.1f}%")

    if metriken.get("per_quelle"):
        print(f"\n  Ergebnisse je Datenquelle:")
        for quelle, m in metriken["per_quelle"].items():
            print(f"    {quelle:<12}  R²={m['r2']:+.4f}  MdAPE={m['mdape']:.0f}%  MAE={m['mae']/1e6:.1f}M€")

    # Gesamtbewertung
    r2, mdape = metriken.get("r2", -999), metriken.get("mdape", 999)
    if r2 >= 0.65 and mdape <= 40:
        bewertung = "SEHR GUT – Ziel erreicht (R²≥0.65, MdAPE≤40%)"
        farbe = "✓"
    elif r2 >= 0.50 and mdape <= 60:
        bewertung = "GUT – Nahe am Ziel"
        farbe = "~"
    elif r2 >= 0.30:
        bewertung = "AUSREICHEND – Verbesserungen sinnvoll"
        farbe = "△"
    else:
        bewertung = "SCHWACH – Modell-Architektur überdenken"
        farbe = "✗"

    print(f"\n  Gesamtbewertung: {farbe} {bewertung}")
    print(f"\n{trenner}\n")


# ---------------------------------------------------------------------------
# Hauptprogramm
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="EstimateIQ Pipeline-Validierung")
    parser.add_argument("--n",       type=int,   default=None, help="Zufallsstichprobe (None = alle)")
    parser.add_argument("--region",  type=str,   default=None, help="Nur Projekte aus diesem Land (DE/AT/CH)")
    parser.add_argument("--quelle",  type=str,   default=None, help="Nur Projekte dieser Quelle (ted/promise/github)")
    parser.add_argument("--plot",    action="store_true",       help="Scatter-Plot speichern")
    parser.add_argument("--seed",    type=int,   default=42,    help="Zufalls-Seed für Stichprobe")
    args = parser.parse_args()

    if not DATEN_PFAD.exists():
        logger.error("Vorverarbeitete Daten nicht gefunden: %s", DATEN_PFAD)
        logger.error("Bitte zuerst: python -m estimateiq.data.preprocess")
        sys.exit(1)

    df = pd.read_parquet(DATEN_PFAD)
    logger.info("[Validierung] %d Datensätze geladen.", len(df))

    # Nur gelabelte Projekte (mit Budget)
    df = df[df["budget_eur"].notna()].reset_index(drop=True)
    logger.info("[Validierung] %d Projekte mit budget_eur nach Filter.", len(df))

    # Optionale Filter
    if args.region:
        df = df[df["land"].astype(str).str.upper() == args.region.upper()].reset_index(drop=True)
        logger.info("[Validierung] Region-Filter '%s': %d Projekte.", args.region, len(df))

    if args.quelle and "datenquelle" in df.columns:
        df = df[df["datenquelle"].astype(str) == args.quelle].reset_index(drop=True)
        logger.info("[Validierung] Quellen-Filter '%s': %d Projekte.", args.quelle, len(df))

    if args.n and args.n < len(df):
        df = df.sample(n=args.n, random_state=args.seed).reset_index(drop=True)
        logger.info("[Validierung] Stichprobe: %d Projekte (Seed=%d).", args.n, args.seed)

    if len(df) == 0:
        logger.error("[Validierung] Keine Projekte nach Filterung.")
        sys.exit(1)

    metriken = validiere_pipeline(df, mit_plot=args.plot)
    drucke_ergebnisse(metriken)


if __name__ == "__main__":
    main()
