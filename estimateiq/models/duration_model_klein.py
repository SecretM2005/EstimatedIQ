"""
Spezialisiertes Laufzeit-Modell für kleine Projekte (14–90 Tage).

Kleine Projekte: Solo/2-Personen-Teams, Standard-Features, kurze Laufzeiten.
Trainingsdaten: Projekte mit 14 <= dauer_tage <= 90 (primär GitHub-Daten).

Artefakte:
  models/duration_model_klein.pkl   – {modell, tfidf, svd}
  models/duration_encoders_klein.pkl – OrdinalEncoder
"""

import logging
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from xgboost import XGBRegressor

# Feature-Engineering aus Basis-Modell wiederverwenden
from estimateiq.models.duration_model import (
    KATEGORIALE,
    NUMERISCHE,
    _erstelle_feature_matrix,
    _feature_engineering,
)

logger = logging.getLogger(__name__)

GROESSE      = "klein"
DAUER_MIN    = 14
DAUER_MAX    = 90
KALIBRIERUNG = 1.0    # GitHub-Daten: echte Dev-Dauern, kein Abzug nötig
MODELL_DIR   = Path("models")
MODELL_PKL   = MODELL_DIR / "duration_model_klein.pkl"
ENCODER_PKL  = MODELL_DIR / "duration_encoders_klein.pkl"


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(df: pd.DataFrame, test_anteil: float = 0.20) -> dict:
    """
    Trainiert spezialisiertes Laufzeit-Modell für kleine Projekte.

    Filtert auf Projekte mit DAUER_MIN <= dauer_tage <= DAUER_MAX.

    Args:
        df: DataFrame mit mindestens 'beschreibung', 'dauer_tage' und Meta-Spalten
        test_anteil: Anteil der Testdaten (Standard: 20%)

    Returns:
        Metriken: rmse_tage, mae_tage, r2, r2_log, mape, n_train, n_test
    """
    logger.info("[Dauer-%s] Starte Training für %s-Projekte (%d–%d Tage)...",
                GROESSE, GROESSE, DAUER_MIN, DAUER_MAX)

    df = _feature_engineering(df)

    # Nur Projekte im Grössenbereich
    dauer_num = pd.to_numeric(df["dauer_tage"], errors="coerce")
    maske = (
        dauer_num.notna()
        & (dauer_num >= DAUER_MIN)
        & (dauer_num <= DAUER_MAX)
    )
    df_sauber = df[maske].reset_index(drop=True)
    n_gesamt  = len(df_sauber)

    logger.info("[Dauer-%s] %d Projekte nach Filterung auf %d–%d Tage.",
                GROESSE, n_gesamt, DAUER_MIN, DAUER_MAX)

    if n_gesamt < 20:
        raise ValueError(
            f"Zu wenig {GROESSE}-Projekte: {n_gesamt} (Minimum: 20). "
            "Bitte mehr Trainingsdaten sammeln."
        )

    y = np.log1p(
        pd.to_numeric(df_sauber["dauer_tage"], errors="coerce").values.astype(np.float64)
    )

    # Stratifizierter Split nach Laufzeit-Quartil
    quartile = pd.qcut(pd.Series(y), q=4, labels=False, duplicates="drop").fillna(0).values
    idx      = np.arange(n_gesamt)
    try:
        idx_train, idx_test = train_test_split(
            idx, test_size=test_anteil, random_state=42, stratify=quartile
        )
    except ValueError:
        idx_train, idx_test = train_test_split(idx, test_size=test_anteil, random_state=42)

    df_train = df_sauber.iloc[idx_train].reset_index(drop=True)
    df_test  = df_sauber.iloc[idx_test].reset_index(drop=True)
    y_train  = y[idx_train]
    y_test   = y[idx_test]

    X_train, encoder, tfidf, svd = _erstelle_feature_matrix(df_train)
    X_test, _, _, _              = _erstelle_feature_matrix(df_test, encoder=encoder, tfidf=tfidf, svd=svd)

    logger.info("[Dauer-%s] Split: %d Train / %d Test, %d Features.",
                GROESSE, len(X_train), len(X_test), X_train.shape[1])

    modell = XGBRegressor(
        n_estimators=400,
        learning_rate=0.03,
        max_depth=4,
        min_child_weight=3,
        subsample=0.8,
        colsample_bytree=0.7,
        reg_alpha=0.05,
        reg_lambda=1.5,
        random_state=42,
        n_jobs=-1,
        eval_metric="rmse",
        early_stopping_rounds=30,
    )
    modell.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    y_pred_log  = modell.predict(X_test).astype(np.float64)
    y_pred_tage = np.expm1(y_pred_log).clip(DAUER_MIN, DAUER_MAX)
    y_true_tage = np.expm1(y_test)

    rmse_tage = float(np.sqrt(mean_squared_error(y_true_tage, y_pred_tage)))
    mae_tage  = float(np.mean(np.abs(y_true_tage - y_pred_tage)))
    r2        = float(r2_score(y_true_tage, y_pred_tage))
    r2_log    = float(r2_score(y_test, y_pred_log))
    mape      = float(np.median(np.abs(y_true_tage - y_pred_tage) / (y_true_tage + 1)) * 100)

    logger.info(
        "[Dauer-%s] Ergebnis:\n"
        "  RMSE (Tage):   %8.1f\n"
        "  MAE  (Tage):   %8.1f\n"
        "  R²   (linear): %8.4f\n"
        "  R²   (log):    %8.4f\n"
        "  MdAPE:         %7.1f%%\n"
        "  Best iteration:%8d",
        GROESSE, rmse_tage, mae_tage, r2, r2_log, mape, modell.best_iteration,
    )

    MODELL_DIR.mkdir(parents=True, exist_ok=True)
    _speichere_modell(modell, encoder, tfidf, svd)

    return {
        "groesse":        GROESSE,
        "rmse_tage":      rmse_tage,
        "mae_tage":       mae_tage,
        "r2":             r2,
        "r2_log":         r2_log,
        "mape":           mape,
        "n_train":        len(X_train),
        "n_test":         len(X_test),
        "n_gesamt":       n_gesamt,
        "best_iteration": modell.best_iteration,
        "n_features":     X_train.shape[1],
    }


# ---------------------------------------------------------------------------
# Vorhersage
# ---------------------------------------------------------------------------

def predict(df: pd.DataFrame) -> np.ndarray:
    """
    Sagt Laufzeit in Tagen voraus, geklippt auf [DAUER_MIN, DAUER_MAX].

    Args:
        df: DataFrame mit mindestens 'beschreibung', 'cpv_code', 'land', 'projekttyp'

    Returns:
        Array mit vorhergesagten Tagen
    """
    modell, encoder, tfidf, svd = _lade_modell()
    df = _feature_engineering(df)
    X, _, _, _ = _erstelle_feature_matrix(df, encoder=encoder, tfidf=tfidf, svd=svd)
    return np.expm1(modell.predict(X).astype(np.float64)).clip(DAUER_MIN, DAUER_MAX)


# ---------------------------------------------------------------------------
# Artefakt-Hilfsfunktionen
# ---------------------------------------------------------------------------

def _speichere_modell(modell, encoder, tfidf, svd) -> None:
    """Speichert Modell-Artefakte als Pickle."""
    with MODELL_PKL.open("wb") as f:
        pickle.dump({"modell": modell, "tfidf": tfidf, "svd": svd}, f)
    with ENCODER_PKL.open("wb") as f:
        pickle.dump(encoder, f)
    logger.info("[Dauer-%s] Gespeichert: %s | %s", GROESSE, MODELL_PKL, ENCODER_PKL)


def _lade_modell() -> tuple:
    """
    Lädt (modell, encoder, tfidf, svd).

    Raises:
        FileNotFoundError: wenn das Modell noch nicht trainiert wurde
    """
    if not MODELL_PKL.exists():
        raise FileNotFoundError(
            f"Kein trainiertes {GROESSE}-Laufzeit-Modell unter {MODELL_PKL}. "
            "Bitte zuerst: python train.py --only specialized"
        )
    with MODELL_PKL.open("rb") as f:
        art = pickle.load(f)
    with ENCODER_PKL.open("rb") as f:
        enc = pickle.load(f)
    return art["modell"], enc, art["tfidf"], art["svd"]
