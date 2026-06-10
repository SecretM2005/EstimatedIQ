"""
XGBoost-Kostenschätzungsmodell – Version 2 (TF-IDF + SVD Textfeatures).

Features:
  Aus v1 (4):    land, projekttyp, dauer_tage, beschreibung_laenge
  Neu SVD (50):  TruncatedSVD-Komponenten aus TF-IDF auf 'beschreibung'
  Neu (4):       komplexitaet, schnittstellen_anzahl, technologien_anzahl, cpv_num
  Gesamt: 58 Features

Kein BERT beim Training nötig → Training dauert < 1 Minute statt Stunden.
TF-IDF + SVD ("Latent Semantic Analysis") liefert ähnlich starke Textfeatures
wie untuned BERT-Embeddings bei einem Bruchteil der Rechenzeit.

Artefakte (unter models/):
  cost_model_v2.pkl     – XGBoost-Modell + TF-IDF-Vektorizer + SVD
  cost_encoders_v2.pkl  – OrdinalEncoder für kategoriale Features
  feature_importance_v2.png
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

# ---------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------

MODELL_DIR   = Path("models")
MODELL_PKL   = MODELL_DIR / "cost_model_v2.pkl"
ENCODER_PKL  = MODELL_DIR / "cost_encoders_v2.pkl"
PLOT_PNG     = MODELL_DIR / "feature_importance_v2.png"

N_SVD_KOMPONENTEN = 50

# ---------------------------------------------------------------------------
# Feature-Definitionen
# ---------------------------------------------------------------------------

KATEGORIALE_FEATURES = ["land", "projekttyp"]
NUMERISCHE_FEATURES  = [
    "dauer_tage",
    "beschreibung_laenge",
    "komplexitaet",
    "schnittstellen_anzahl",
    "technologien_anzahl",
    "cpv_num",
]


# ---------------------------------------------------------------------------
# Feature Engineering
# ---------------------------------------------------------------------------

def _feature_engineering(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["beschreibung_laenge"] = df["beschreibung"].str.len().fillna(0).astype("float32")

    if "technologien" in df.columns:
        df["technologien_anzahl"] = df["technologien"].apply(
            lambda x: len(x) if isinstance(x, list) else 0
        ).astype("float32")
    else:
        df["technologien_anzahl"] = 0.0

    df["cpv_num"] = pd.to_numeric(df["cpv_code"], errors="coerce").fillna(72000000).astype("float32")

    for col, default in [("komplexitaet", 3.0), ("schnittstellen_anzahl", 0.0)]:
        if col not in df.columns:
            df[col] = default
        df[col] = df[col].astype("float32")

    return df


def _erstelle_feature_matrix(
    df: pd.DataFrame,
    encoder: OrdinalEncoder | None = None,
    tfidf: TfidfVectorizer | None = None,
    svd: TruncatedSVD | None = None,
) -> tuple[np.ndarray, OrdinalEncoder, TfidfVectorizer, TruncatedSVD]:
    """
    Baut Feature-Matrix auf:
      [kategoriale (2)] + [numerische (6)] + [SVD-Textfeatures (50)]
    """
    fit_modus = encoder is None

    if fit_modus:
        encoder = OrdinalEncoder(
            handle_unknown="use_encoded_value", unknown_value=-1, dtype=np.float32,
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

    # TF-IDF + SVD auf Beschreibungstext
    texte = df["beschreibung"].fillna("").tolist()
    if fit_modus:
        tfidf = TfidfVectorizer(
            max_features=20_000,
            min_df=2,
            sublinear_tf=True,
            ngram_range=(1, 2),
        )
        tfidf_matrix = tfidf.fit_transform(texte)
        n_komp = min(N_SVD_KOMPONENTEN, tfidf_matrix.shape[1] - 1, tfidf_matrix.shape[0] - 1)
        svd = TruncatedSVD(n_components=n_komp, random_state=42)
        svd_werte = svd.fit_transform(tfidf_matrix).astype(np.float32)
        erklaert = svd.explained_variance_ratio_.sum()
        logger.info(
            "[v2] TF-IDF Vokabular: %d | SVD: %d Komp. erklären %.1f%% Textvarianz.",
            len(tfidf.vocabulary_), n_komp, erklaert * 100,
        )
    else:
        tfidf_matrix = tfidf.transform(texte)
        svd_werte = svd.transform(tfidf_matrix).astype(np.float32)

    X = np.hstack([kat_werte, num_werte, svd_werte])
    return X, encoder, tfidf, svd


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(df: pd.DataFrame, test_anteil: float = 0.20) -> dict:
    """
    Trainiert das XGBoost-Modell v2 mit TF-IDF + SVD Textfeatures.
    Kein BERT nötig – Training dauert < 1 Minute.
    """
    logger.info("[Training v2] Starte XGBoost-Training (TF-IDF + SVD)...")

    df = _feature_engineering(df)
    df_sauber = df[df["budget_eur"].notna()].reset_index(drop=True)
    n_sauber = len(df_sauber)
    logger.info("[Training v2] %d/%d Zeilen mit budget_eur.", n_sauber, len(df))

    if n_sauber < 50:
        raise ValueError(f"Zu wenig Trainingsdaten: {n_sauber} Zeilen (Minimum: 50).")

    y_log = np.log1p(df_sauber["budget_eur"].values.astype(np.float64))
    X, encoder, tfidf, svd = _erstelle_feature_matrix(df_sauber)

    quartile = pd.qcut(y_log, q=4, labels=False, duplicates="drop")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y_log, test_size=test_anteil, random_state=42, stratify=quartile,
    )
    logger.info("[Training v2] Split: %d Training / %d Test, %d Features.",
                len(X_train), len(X_test), X.shape[1])

    modell = XGBRegressor(
        n_estimators=600,
        learning_rate=0.02,
        max_depth=5,
        min_child_weight=5,
        subsample=0.8,
        colsample_bytree=0.5,
        reg_alpha=0.1,
        reg_lambda=2.0,
        random_state=42,
        n_jobs=-1,
        eval_metric="rmse",
        early_stopping_rounds=50,
    )
    modell.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    y_pred_log = modell.predict(X_test)
    y_pred_eur = np.expm1(y_pred_log)
    y_true_eur = np.expm1(y_test)

    rmse_eur = float(np.sqrt(mean_squared_error(y_true_eur, y_pred_eur)))
    r2       = float(r2_score(y_true_eur, y_pred_eur))
    rmse_log = float(np.sqrt(mean_squared_error(y_test, y_pred_log)))

    logger.info(
        "[Training v2] Ergebnis:\n"
        "  RMSE (EUR):      %16s €\n"
        "  RMSE (log):      %16.4f\n"
        "  R²:              %16.4f\n"
        "  Best iteration:  %16d",
        f"{rmse_eur:,.0f}", rmse_log, r2, modell.best_iteration,
    )

    MODELL_DIR.mkdir(parents=True, exist_ok=True)
    _speichere_modell(modell, encoder, tfidf, svd)
    _erstelle_importance_plot(modell, X.shape[1])

    return {
        "rmse_eur":       rmse_eur,
        "rmse_log":       rmse_log,
        "r2":             r2,
        "n_train":        len(X_train),
        "n_test":         len(X_test),
        "best_iteration": modell.best_iteration,
        "n_features":     X.shape[1],
        "n_svd_features": svd.n_components,
    }


# ---------------------------------------------------------------------------
# Vorhersage
# ---------------------------------------------------------------------------

def predict(df: pd.DataFrame, **_kwargs) -> np.ndarray:
    """Sagt Auftragswerte in EUR voraus. Ignoriert unbekannte kwargs (z. B. embeddings)."""
    modell, encoder, tfidf, svd = _lade_modell()
    df = _feature_engineering(df)
    X, _, _, _ = _erstelle_feature_matrix(df, encoder=encoder, tfidf=tfidf, svd=svd)
    return np.expm1(modell.predict(X))


# ---------------------------------------------------------------------------
# Artefakt-Hilfsfunktionen
# ---------------------------------------------------------------------------

def _speichere_modell(modell, encoder, tfidf, svd) -> None:
    with MODELL_PKL.open("wb") as f:
        pickle.dump({"modell": modell, "tfidf": tfidf, "svd": svd}, f)
    with ENCODER_PKL.open("wb") as f:
        pickle.dump(encoder, f)
    logger.info("[Speichern v2] %s | %s", MODELL_PKL, ENCODER_PKL)


def _lade_modell():
    if not MODELL_PKL.exists():
        raise FileNotFoundError(
            f"Kein trainiertes v2-Modell unter {MODELL_PKL}. "
            "Bitte zuerst train() aufrufen."
        )
    with MODELL_PKL.open("rb") as f:
        art = pickle.load(f)
    with ENCODER_PKL.open("rb") as f:
        encoder = pickle.load(f)
    return art["modell"], encoder, art["tfidf"], art["svd"]


def _erstelle_importance_plot(modell: XGBRegressor, n_features: int) -> None:
    importances = modell.get_booster().get_score(importance_type="gain")
    n_basis = len(KATEGORIALE_FEATURES) + len(NUMERISCHE_FEATURES)
    namen = (
        KATEGORIALE_FEATURES
        + NUMERISCHE_FEATURES
        + [f"svd_{i}" for i in range(n_features - n_basis)]
    )
    werte    = [importances.get(f"f{i}", 0.0) for i in range(len(namen))]
    gesamt   = sum(werte) or 1.0
    prozente = [100 * w / gesamt for w in werte]

    sortiert = sorted(zip(prozente, namen), reverse=True)[:20]
    prozente_sort, namen_sort = zip(*sortiert)

    fig, ax = plt.subplots(figsize=(10, 6))
    farben = ["#2563eb" if p == max(prozente_sort) else "#93c5fd" for p in prozente_sort]
    balken = ax.barh(namen_sort, prozente_sort, color=farben, height=0.55)
    for bar, pct in zip(balken, prozente_sort):
        ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                f"{pct:.1f}%", va="center", ha="left", fontsize=8)
    ax.set_xlabel("Relative Importance (Gain) in %", fontsize=11)
    ax.set_title(f"Feature Importance – Cost Model v2 (Top 20 von {n_features})",
                 fontsize=12, fontweight="bold")
    ax.set_xlim(0, max(prozente_sort) * 1.25)
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    fig.savefig(PLOT_PNG, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("[Plot v2] %s", PLOT_PNG)
