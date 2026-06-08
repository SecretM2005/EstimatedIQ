"""
XGBoost-Kostenschätzungsmodell – Version 2 (BERT-angereichert).

Erweitert v1 um vier BERT-basierte Features:
  projekttyp_bert    (kategorial, zero-shot klassifiziert)
  komplexitaet       (numerisch, 1–5)
  schnittstellen_anzahl (numerisch)
  technologien_anzahl   (numerisch, Anzahl erkannter Technologien)

Artefakte (unter models/):
  cost_model_v2.pkl          – trainiertes XGBoost-Modell
  cost_encoders_v2.pkl       – OrdinalEncoder für land + projekttyp + projekttyp_bert
  feature_importance_v2.png  – Balkendiagramm der Feature-Wichtigkeiten
"""

import logging
import pickle
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OrdinalEncoder
from xgboost import XGBRegressor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------

MODELL_DIR   = Path("models")
MODELL_PKL   = MODELL_DIR / "cost_model_v2.pkl"
ENCODER_PKL  = MODELL_DIR / "cost_encoders_v2.pkl"
PLOT_PNG     = MODELL_DIR / "feature_importance_v2.png"

# ---------------------------------------------------------------------------
# Feature-Definitionen
# ---------------------------------------------------------------------------

KATEGORIALE_FEATURES = ["land", "projekttyp", "projekttyp_bert"]
NUMERISCHE_FEATURES  = [
    "dauer_tage",
    "beschreibung_laenge",
    "komplexitaet",
    "schnittstellen_anzahl",
    "technologien_anzahl",
]
ALLE_FEATURES = KATEGORIALE_FEATURES + NUMERISCHE_FEATURES


# ---------------------------------------------------------------------------
# Feature Engineering
# ---------------------------------------------------------------------------

def _feature_engineering(df: pd.DataFrame) -> pd.DataFrame:
    """Leitet Hilfsspalten ab, die nicht direkt in den Rohdaten stehen."""
    df = df.copy()
    df["beschreibung_laenge"] = df["beschreibung"].str.len().fillna(0).astype("float32")

    # Anzahl erkannter Technologien aus der Listen-Spalte
    if "technologien" in df.columns:
        df["technologien_anzahl"] = df["technologien"].apply(
            lambda x: len(x) if isinstance(x, list) else 0
        ).astype("float32")
    else:
        df["technologien_anzahl"] = 0.0

    # Fehlende BERT-Spalten mit Standardwerten auffüllen
    if "projekttyp_bert" not in df.columns:
        df["projekttyp_bert"] = "Sonstiges"
    if "komplexitaet" not in df.columns:
        df["komplexitaet"] = 3.0
    if "schnittstellen_anzahl" not in df.columns:
        df["schnittstellen_anzahl"] = 0.0

    df["komplexitaet"]        = df["komplexitaet"].astype("float32")
    df["schnittstellen_anzahl"] = df["schnittstellen_anzahl"].astype("float32")

    return df


def _erstelle_feature_matrix(
    df: pd.DataFrame,
    encoder: OrdinalEncoder | None = None,
) -> tuple[np.ndarray, OrdinalEncoder]:
    """Baut die Feature-Matrix X auf (kategoriale + numerische Features)."""
    fit_modus = encoder is None

    if fit_modus:
        encoder = OrdinalEncoder(
            handle_unknown="use_encoded_value",
            unknown_value=-1,
            dtype=np.float32,
        )
        kat_werte = encoder.fit_transform(
            df[KATEGORIALE_FEATURES].astype(str).fillna("unbekannt")
        )
    else:
        kat_werte = encoder.transform(
            df[KATEGORIALE_FEATURES].astype(str).fillna("unbekannt")
        )

    num_werte = (
        df[NUMERISCHE_FEATURES]
        .apply(pd.to_numeric, errors="coerce")
        .fillna(0.0)
        .values.astype(np.float32)
    )

    X = np.hstack([kat_werte, num_werte])
    return X, encoder


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(df: pd.DataFrame, test_anteil: float = 0.20) -> dict:
    """
    Trainiert das XGBoost-Modell v2 auf BERT-angereicherten Daten.

    Erwartet einen DataFrame, der bereits die Spalten
    projekttyp_bert, technologien, komplexitaet, schnittstellen_anzahl
    enthält (erzeugt von bert_extractor.anreichere_dataframe).

    Returns:
        dict mit rmse_eur, r2, n_train, n_test, best_iteration
    """
    logger.info("[Training v2] Starte XGBoost-Training (BERT-Features)...")

    df = _feature_engineering(df)

    df_sauber = df[df["budget_eur"].notna()].reset_index(drop=True)
    n_gesamt  = len(df)
    n_sauber  = len(df_sauber)
    logger.info(
        "[Training v2] %d/%d Zeilen mit budget_eur – %d verworfen.",
        n_sauber, n_gesamt, n_gesamt - n_sauber,
    )

    if n_sauber < 50:
        raise ValueError(
            f"Zu wenig Trainingsdaten: {n_sauber} Zeilen (Minimum: 50)."
        )

    y_log = np.log1p(df_sauber["budget_eur"].values.astype(np.float64))
    X, encoder = _erstelle_feature_matrix(df_sauber)

    quartile = pd.qcut(y_log, q=4, labels=False, duplicates="drop")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y_log,
        test_size=test_anteil,
        random_state=42,
        stratify=quartile,
    )
    logger.info(
        "[Training v2] Split: %d Training / %d Test.",
        len(X_train), len(X_test),
    )

    modell = XGBRegressor(
        n_estimators=600,
        learning_rate=0.025,
        max_depth=5,
        min_child_weight=5,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.05,
        reg_lambda=1.5,
        random_state=42,
        n_jobs=-1,
        eval_metric="rmse",
        early_stopping_rounds=50,
    )

    modell.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )

    y_pred_log = modell.predict(X_test)
    y_pred_eur = np.expm1(y_pred_log)
    y_true_eur = np.expm1(y_test)

    rmse_eur = float(np.sqrt(mean_squared_error(y_true_eur, y_pred_eur)))
    r2       = float(r2_score(y_true_eur, y_pred_eur))
    rmse_log = float(np.sqrt(mean_squared_error(y_test, y_pred_log)))

    logger.info(
        "[Training v2] Ergebnis:\n"
        "  RMSE (EUR):        %16s €\n"
        "  RMSE (log-Raum):   %16.4f\n"
        "  R²:                %16.4f\n"
        "  Best iteration:    %16d",
        f"{rmse_eur:,.0f}",
        rmse_log,
        r2,
        modell.best_iteration,
    )

    MODELL_DIR.mkdir(parents=True, exist_ok=True)
    _speichere_modell(modell, encoder)
    _erstelle_importance_plot(modell)

    return {
        "rmse_eur":       rmse_eur,
        "rmse_log":       rmse_log,
        "r2":             r2,
        "n_train":        len(X_train),
        "n_test":         len(X_test),
        "best_iteration": modell.best_iteration,
    }


# ---------------------------------------------------------------------------
# Vorhersage
# ---------------------------------------------------------------------------

def predict(df: pd.DataFrame) -> np.ndarray:
    """
    Sagt Auftragswerte in EUR voraus (BERT-Features werden automatisch ergänzt
    falls fehlend; für beste Qualität vorher anreichere_dataframe() aufrufen).
    """
    modell, encoder = _lade_modell()
    df = _feature_engineering(df)
    X, _ = _erstelle_feature_matrix(df, encoder=encoder)
    y_pred_log = modell.predict(X)
    return np.expm1(y_pred_log)


# ---------------------------------------------------------------------------
# Artefakt-Hilfsfunktionen
# ---------------------------------------------------------------------------

def _speichere_modell(modell: XGBRegressor, encoder: OrdinalEncoder) -> None:
    with MODELL_PKL.open("wb") as f:
        pickle.dump(modell, f)
    with ENCODER_PKL.open("wb") as f:
        pickle.dump(encoder, f)
    logger.info("[Speichern v2] Modell → %s | Encoder → %s", MODELL_PKL, ENCODER_PKL)


def _lade_modell() -> tuple[XGBRegressor, OrdinalEncoder]:
    if not MODELL_PKL.exists():
        raise FileNotFoundError(
            f"Kein trainiertes v2-Modell unter {MODELL_PKL}. "
            "Bitte zuerst train() aufrufen."
        )
    with MODELL_PKL.open("rb") as f:
        modell = pickle.load(f)
    with ENCODER_PKL.open("rb") as f:
        encoder = pickle.load(f)
    return modell, encoder


def _erstelle_importance_plot(modell: XGBRegressor) -> None:
    importances = modell.get_booster().get_score(importance_type="gain")

    for feat in ALLE_FEATURES:
        importances.setdefault(f"f{ALLE_FEATURES.index(feat)}", 0.0)

    namen    = [ALLE_FEATURES[i] for i in range(len(ALLE_FEATURES))]
    werte    = [importances.get(f"f{i}", 0.0) for i in range(len(ALLE_FEATURES))]
    gesamt   = sum(werte) or 1.0
    prozente = [100 * w / gesamt for w in werte]

    sortiert = sorted(zip(prozente, namen), reverse=True)
    prozente_sort, namen_sort = zip(*sortiert)

    fig, ax = plt.subplots(figsize=(9, 5))
    farben = ["#2563eb" if p == max(prozente_sort) else "#93c5fd" for p in prozente_sort]
    balken = ax.barh(namen_sort, prozente_sort, color=farben, height=0.55)

    for bar, pct in zip(balken, prozente_sort):
        ax.text(
            bar.get_width() + 0.5,
            bar.get_y() + bar.get_height() / 2,
            f"{pct:.1f}%",
            va="center", ha="left", fontsize=9,
        )

    ax.set_xlabel("Relative Importance (Gain) in %", fontsize=11)
    ax.set_title("Feature Importance – EstimateIQ Cost Model v2 (BERT)", fontsize=13, fontweight="bold")
    ax.set_xlim(0, max(prozente_sort) * 1.20)
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)

    plt.tight_layout()
    fig.savefig(PLOT_PNG, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("[Plot v2] Feature-Importance gespeichert: %s", PLOT_PNG)


# ---------------------------------------------------------------------------
# Direkt ausführbar: python -m estimateiq.models.cost_model_v2
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    from estimateiq.models.bert_extractor import anreichere_dataframe

    eingabe = Path("data/processed/notices.parquet")
    if not eingabe.exists():
        raise SystemExit(
            f"Datei nicht gefunden: {eingabe}\n"
            "Bitte zuerst ausführen: python -m estimateiq.data.preprocess"
        )

    logger.info("Lade vorverarbeitete Daten aus %s ...", eingabe)
    df = pd.read_parquet(eingabe)
    logger.info("  %d Zeilen geladen.", len(df))

    logger.info("BERT-Features extrahieren (dauert ca. 5–15 Min. ohne GPU)...")
    df = anreichere_dataframe(df)

    metriken = train(df)

    trenner = "─" * 50
    print(f"\n{trenner}")
    print("  EstimateIQ – Cost Model v2 (BERT)  Ergebnis")
    print(trenner)
    print(f"  RMSE auf Testmenge:  {metriken['rmse_eur']:>14,.0f} €")
    print(f"  R² auf Testmenge:    {metriken['r2']:>14.4f}")
    print(f"  RMSE (log-Raum):     {metriken['rmse_log']:>14.4f}")
    print(f"  Trainingszeilen:     {metriken['n_train']:>14,}")
    print(f"  Testzeilen:          {metriken['n_test']:>14,}")
    print(f"  Best Iteration:      {metriken['best_iteration']:>14,}")
    print(f"\n  Modell:  {MODELL_PKL}")
    print(f"  Encoder: {ENCODER_PKL}")
    print(f"  Plot:    {PLOT_PNG}")
    print(f"{trenner}\n")
