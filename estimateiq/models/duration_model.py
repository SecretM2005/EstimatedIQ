"""
EstimateIQ – Laufzeit-Modell (Stufe 1 der zweistufigen Kostenschätzung).

Ziel:
  Schätzt dauer_tage für IT-Projekte aus Beschreibungstext und Metadaten.

Vorteil gegenüber direkter Budgetschätzung:
  Laufzeit ist deutlich besser durch Textmerkmale vorhersagbar als Budget.
  Durch Training auf ALLEN Projekten (auch ohne Budget) stehen wesentlich
  mehr Trainingsdaten zur Verfügung.

Features (≤ 56):
  Kategoriale  (3): land, projekttyp, datenquelle
  Numerische   (3): beschreibung_laenge, beschreibung_wortanzahl, cpv_num
  SVD-Text    (50): TruncatedSVD aus TF-IDF auf 'beschreibung'

Artefakte (unter models/):
  duration_model.pkl      – {modell, tfidf, svd}
  duration_encoders.pkl   – OrdinalEncoder
"""

import logging
import pickle
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OrdinalEncoder
from xgboost import XGBRegressor

logger = logging.getLogger(__name__)

MODELL_DIR   = Path("models")
MODELL_PKL   = MODELL_DIR / "duration_model.pkl"
ENCODER_PKL  = MODELL_DIR / "duration_encoders.pkl"
PLOT_PNG     = MODELL_DIR / "duration_importance.png"

N_SVD              = 50
KATEGORIALE        = ["land", "projekttyp", "datenquelle"]
NUMERISCHE         = ["beschreibung_laenge", "beschreibung_wortanzahl", "cpv_num"]
DAUER_MIN_TAGE     = 7
DAUER_MAX_TAGE     = 3_650


# ---------------------------------------------------------------------------
# Feature Engineering
# ---------------------------------------------------------------------------

def _feature_engineering(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "datenquelle" not in df.columns:
        df["datenquelle"] = "ted"
    df["beschreibung_laenge"]     = df["beschreibung"].str.len().fillna(0).astype("float32")
    df["beschreibung_wortanzahl"] = df["beschreibung"].str.split().str.len().fillna(0).astype("float32")
    df["cpv_num"] = pd.to_numeric(df["cpv_code"], errors="coerce").fillna(72_000_000).astype("float32")
    return df


def _erstelle_feature_matrix(
    df: pd.DataFrame,
    encoder: OrdinalEncoder | None = None,
    tfidf: TfidfVectorizer | None = None,
    svd: TruncatedSVD | None = None,
) -> tuple[np.ndarray, OrdinalEncoder, TfidfVectorizer, TruncatedSVD]:
    fit = encoder is None

    if fit:
        encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1, dtype=np.float32)
        kat = encoder.fit_transform(df[KATEGORIALE].astype(str).fillna("unbekannt"))
    else:
        kat = encoder.transform(df[KATEGORIALE].astype(str).fillna("unbekannt"))

    num = df[NUMERISCHE].apply(pd.to_numeric, errors="coerce").fillna(0.0).values.astype(np.float32)

    texte = df["beschreibung"].fillna("").tolist()
    if fit:
        tfidf = TfidfVectorizer(max_features=15_000, min_df=2, sublinear_tf=True, ngram_range=(1, 2))
        mat   = tfidf.fit_transform(texte)
        n_k   = min(N_SVD, mat.shape[1] - 1, mat.shape[0] - 1)
        svd   = TruncatedSVD(n_components=n_k, random_state=42)
        txt   = svd.fit_transform(mat).astype(np.float32)
        logger.info("[Dauer] TF-IDF Vokabular: %d | SVD: %d Komp. (%.1f%% Textvarianz)",
                    len(tfidf.vocabulary_), n_k, svd.explained_variance_ratio_.sum() * 100)
    else:
        txt = svd.transform(tfidf.transform(texte)).astype(np.float32)

    return np.hstack([kat, num, txt]), encoder, tfidf, svd


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(df: pd.DataFrame, test_anteil: float = 0.20) -> dict:
    """
    Trainiert das Laufzeit-Modell auf ALLEN Projekten mit gültigem dauer_tage.
    Budget-Spalte wird ignoriert → maximale Trainingsdaten.
    """
    logger.info("[Dauer] Starte Training auf ALLEN Projekten mit dauer_tage...")

    df = _feature_engineering(df)
    df_sauber = df[
        df["dauer_tage"].notna()
        & (pd.to_numeric(df["dauer_tage"], errors="coerce") >= DAUER_MIN_TAGE)
        & (pd.to_numeric(df["dauer_tage"], errors="coerce") <= DAUER_MAX_TAGE)
    ].reset_index(drop=True)

    n_gesamt = len(df_sauber)
    n_mit_budget = df_sauber["budget_eur"].notna().sum() if "budget_eur" in df_sauber.columns else 0
    logger.info("[Dauer] %d Projekte mit dauer_tage (davon %d mit Budget = %d%% Budget-Rate).",
                n_gesamt, n_mit_budget, round(100 * n_mit_budget / n_gesamt) if n_gesamt else 0)

    if n_gesamt < 30:
        raise ValueError(f"Zu wenig Trainingsdaten: {n_gesamt} Projekte mit dauer_tage (Minimum: 30).")

    y = np.log1p(pd.to_numeric(df_sauber["dauer_tage"], errors="coerce").values.astype(np.float64))

    # Stratifizierter Split nach Laufzeit-Quartil
    quartile = pd.qcut(pd.Series(y), q=4, labels=False, duplicates="drop").fillna(0).values
    idx = np.arange(n_gesamt)
    idx_train, idx_test = train_test_split(idx, test_size=test_anteil, random_state=42, stratify=quartile)

    df_train, df_test = df_sauber.iloc[idx_train].reset_index(drop=True), df_sauber.iloc[idx_test].reset_index(drop=True)
    y_train, y_test   = y[idx_train], y[idx_test]

    X_train, encoder, tfidf, svd = _erstelle_feature_matrix(df_train)
    X_test, _, _, _              = _erstelle_feature_matrix(df_test, encoder=encoder, tfidf=tfidf, svd=svd)
    logger.info("[Dauer] Split: %d Train / %d Test, %d Features.", len(X_train), len(X_test), X_train.shape[1])

    modell = XGBRegressor(
        n_estimators=600,
        learning_rate=0.02,
        max_depth=4,
        min_child_weight=5,
        subsample=0.8,
        colsample_bytree=0.6,
        reg_alpha=0.05,
        reg_lambda=1.5,
        random_state=42,
        n_jobs=-1,
        eval_metric="rmse",
        early_stopping_rounds=40,
    )
    modell.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    y_pred_log  = modell.predict(X_test).astype(np.float64)
    y_pred_tage = np.expm1(y_pred_log)
    y_true_tage = np.expm1(y_test)

    rmse_tage = float(np.sqrt(mean_squared_error(y_true_tage, y_pred_tage)))
    mae_tage  = float(np.mean(np.abs(y_true_tage - y_pred_tage)))
    r2        = float(r2_score(y_true_tage, y_pred_tage))
    r2_log    = float(r2_score(y_test, y_pred_log))
    mape      = float(np.median(np.abs(y_true_tage - y_pred_tage) / (y_true_tage + 1)) * 100)

    logger.info(
        "[Dauer] Ergebnis:\n"
        "  RMSE (Tage):   %8.1f\n"
        "  MAE  (Tage):   %8.1f\n"
        "  R²   (linear): %8.4f\n"
        "  R²   (log):    %8.4f\n"
        "  MdAPE:         %7.1f%%\n"
        "  Best iteration:%8d",
        rmse_tage, mae_tage, r2, r2_log, mape, modell.best_iteration,
    )

    MODELL_DIR.mkdir(parents=True, exist_ok=True)
    _speichere_modell(modell, encoder, tfidf, svd)
    _erstelle_importance_plot(modell, X_train.shape[1])

    return {
        "rmse_tage":      rmse_tage,
        "mae_tage":       mae_tage,
        "r2":             r2,
        "r2_log":         r2_log,
        "mape":           mape,
        "n_train":        len(X_train),
        "n_test":         len(X_test),
        "n_mit_budget":   int(n_mit_budget),
        "best_iteration": modell.best_iteration,
        "n_features":     X_train.shape[1],
    }


# ---------------------------------------------------------------------------
# Vorhersage
# ---------------------------------------------------------------------------

def predict(df: pd.DataFrame) -> np.ndarray:
    """Sagt Laufzeit in Tagen voraus. Erwartet Spalten: beschreibung, cpv_code, land, projekttyp."""
    modell, encoder, tfidf, svd = _lade_modell()
    df = _feature_engineering(df)
    X, _, _, _ = _erstelle_feature_matrix(df, encoder=encoder, tfidf=tfidf, svd=svd)
    return np.expm1(modell.predict(X)).clip(DAUER_MIN_TAGE, DAUER_MAX_TAGE)


# ---------------------------------------------------------------------------
# Artefakt-Hilfsfunktionen
# ---------------------------------------------------------------------------

def _speichere_modell(modell, encoder, tfidf, svd) -> None:
    with MODELL_PKL.open("wb") as f:
        pickle.dump({"modell": modell, "tfidf": tfidf, "svd": svd}, f)
    with ENCODER_PKL.open("wb") as f:
        pickle.dump(encoder, f)
    logger.info("[Dauer] Gespeichert: %s | %s", MODELL_PKL, ENCODER_PKL)


def _lade_modell():
    if not MODELL_PKL.exists():
        raise FileNotFoundError(
            f"Kein trainiertes Laufzeit-Modell unter {MODELL_PKL}. "
            "Bitte zuerst: python train.py --only duration"
        )
    with MODELL_PKL.open("rb") as f:
        art = pickle.load(f)
    with ENCODER_PKL.open("rb") as f:
        enc = pickle.load(f)
    return art["modell"], enc, art["tfidf"], art["svd"]


def _erstelle_importance_plot(modell: XGBRegressor, n_features: int) -> None:
    importances = modell.get_booster().get_score(importance_type="gain")
    n_basis = len(KATEGORIALE) + len(NUMERISCHE)
    namen = KATEGORIALE + NUMERISCHE + [f"svd_{i}" for i in range(n_features - n_basis)]
    werte = [importances.get(f"f{i}", 0.0) for i in range(len(namen))]
    gesamt = sum(werte) or 1.0

    sortiert = sorted(zip([100 * w / gesamt for w in werte], namen), reverse=True)[:20]
    prozente, namen_sort = zip(*sortiert)

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(namen_sort, prozente, color=["#2563eb" if p == max(prozente) else "#93c5fd" for p in prozente], height=0.55)
    ax.set_xlabel("Relative Importance (Gain) in %")
    ax.set_title(f"Feature Importance – Laufzeit-Modell (Top 20 von {n_features})", fontweight="bold")
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    fig.savefig(PLOT_PNG, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("[Dauer] Importance-Plot: %s", PLOT_PNG)
