"""
XGBoost-Kostenschätzungsmodell – Version 2 (PCA-reduzierte BERT-Embeddings).

Features:
  Aus v1 (4):   land, projekttyp, dauer_tage, beschreibung_laenge
  Neu (50):     PCA-Komponenten der BERT-Embeddings (768 → 50 Dims)
  Neu (4):      komplexitaet, schnittstellen_anzahl, technologien_anzahl,
                cpv_num (numerischer CPV-Code)
  Gesamt: 58 Features

PCA wird beim Training auf den Trainingszeilen gefittet und zusammen
mit dem XGBoost-Modell serialisiert.

Artefakte (unter models/):
  cost_model_v2.pkl          – trainiertes XGBoost-Modell + PCA
  cost_encoders_v2.pkl       – OrdinalEncoder für kategoriale Features
  feature_importance_v2.png  – Feature-Wichtigkeiten (Top-20)
"""

import logging
import pickle
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
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

N_PCA_KOMPONENTEN = 50

# ---------------------------------------------------------------------------
# Feature-Definitionen (ohne PCA-Komponenten, die dynamisch hinzukommen)
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
    """Leitet Hilfsspalten ab."""
    df = df.copy()
    df["beschreibung_laenge"] = df["beschreibung"].str.len().fillna(0).astype("float32")

    if "technologien" in df.columns:
        df["technologien_anzahl"] = df["technologien"].apply(
            lambda x: len(x) if isinstance(x, list) else 0
        ).astype("float32")
    else:
        df["technologien_anzahl"] = 0.0

    # CPV-Code als Zahl
    df["cpv_num"] = pd.to_numeric(df["cpv_code"], errors="coerce").fillna(72000000).astype("float32")

    for col, default in [("komplexitaet", 3.0), ("schnittstellen_anzahl", 0.0)]:
        if col not in df.columns:
            df[col] = default
        df[col] = df[col].astype("float32")

    return df


def _erstelle_feature_matrix(
    df: pd.DataFrame,
    embeddings: np.ndarray | None,
    encoder: OrdinalEncoder | None = None,
    pca: PCA | None = None,
) -> tuple[np.ndarray, OrdinalEncoder, PCA | None]:
    """
    Baut die Feature-Matrix auf:
      [kategoriale (2)] + [numerische (6)] + [PCA-Komponenten (50)]
    """
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

    teile = [kat_werte, num_werte]

    if embeddings is not None and len(embeddings) > 0:
        if fit_modus:
            n_komp = min(N_PCA_KOMPONENTEN, embeddings.shape[0] - 1, embeddings.shape[1])
            pca = PCA(n_components=n_komp, random_state=42)
            pca_werte = pca.fit_transform(embeddings).astype(np.float32)
            erklaert = pca.explained_variance_ratio_.sum()
            logger.info(
                "[v2] PCA: %d Komponenten erklären %.1f%% der Embedding-Varianz.",
                n_komp, erklaert * 100,
            )
        else:
            pca_werte = pca.transform(embeddings).astype(np.float32)
        teile.append(pca_werte)

    X = np.hstack(teile)
    return X, encoder, pca


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(df: pd.DataFrame, embeddings: np.ndarray | None = None, test_anteil: float = 0.20) -> dict:
    """
    Trainiert das XGBoost-Modell v2.

    Args:
        df:          DataFrame (mit BERT-Scalar-Features falls vorhanden)
        embeddings:  Optional: BERT-Embeddings-Matrix (n_rows × 768).
                     Wenn übergeben, werden PCA-Komponenten als Features verwendet.
        test_anteil: Anteil Testmenge

    Returns:
        dict mit rmse_eur, r2, n_train, n_test, best_iteration, n_pca_features
    """
    logger.info("[Training v2] Starte XGBoost-Training (%s Features)...",
                "PCA-Embeddings + numerisch" if embeddings is not None else "nur numerisch")

    df = _feature_engineering(df)
    df_sauber = df[df["budget_eur"].notna()].reset_index(drop=True)

    # Embeddings auf Zeilen mit bekanntem Budget einschränken
    if embeddings is not None:
        maske = df["budget_eur"].notna().values
        embeddings_sauber = embeddings[maske]
    else:
        embeddings_sauber = None

    n_gesamt = len(df)
    n_sauber = len(df_sauber)
    logger.info("[Training v2] %d/%d Zeilen mit budget_eur.", n_sauber, n_gesamt)

    if n_sauber < 50:
        raise ValueError(f"Zu wenig Trainingsdaten: {n_sauber} Zeilen (Minimum: 50).")

    y_log = np.log1p(df_sauber["budget_eur"].values.astype(np.float64))
    X, encoder, pca = _erstelle_feature_matrix(df_sauber, embeddings_sauber)

    quartile = pd.qcut(y_log, q=4, labels=False, duplicates="drop")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y_log, test_size=test_anteil, random_state=42, stratify=quartile,
    )
    logger.info("[Training v2] Split: %d Training / %d Test, %d Features gesamt.",
                len(X_train), len(X_test), X.shape[1])

    modell = XGBRegressor(
        n_estimators=600,
        learning_rate=0.02,
        max_depth=5,
        min_child_weight=5,
        subsample=0.8,
        colsample_bytree=0.5,   # wichtig: viele Features, zufällig samplen
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
        "  RMSE (EUR):        %16s €\n"
        "  RMSE (log-Raum):   %16.4f\n"
        "  R²:                %16.4f\n"
        "  Best iteration:    %16d",
        f"{rmse_eur:,.0f}", rmse_log, r2, modell.best_iteration,
    )

    MODELL_DIR.mkdir(parents=True, exist_ok=True)
    _speichere_modell(modell, encoder, pca)
    _erstelle_importance_plot(modell, X.shape[1], pca)

    return {
        "rmse_eur":        rmse_eur,
        "rmse_log":        rmse_log,
        "r2":              r2,
        "n_train":         len(X_train),
        "n_test":          len(X_test),
        "best_iteration":  modell.best_iteration,
        "n_features":      X.shape[1],
        "n_pca_features":  pca.n_components_ if pca else 0,
    }


# ---------------------------------------------------------------------------
# Vorhersage
# ---------------------------------------------------------------------------

def predict(df: pd.DataFrame, embeddings: np.ndarray | None = None) -> np.ndarray:
    """
    Sagt Auftragswerte in EUR voraus.

    Args:
        df:          DataFrame (mindestens: beschreibung, land, projekttyp, dauer_tage)
        embeddings:  Optional BERT-Embeddings (1 × 768) für diesen Request.
                     Wenn None und PCA trainiert wurde, werden Nullvektoren verwendet.
    """
    modell, encoder, pca = _lade_modell()
    df = _feature_engineering(df)

    # Embeddings für Predict: falls keine übergeben, Nullvektor (PCA → 0-Komponenten)
    if pca is not None and embeddings is None:
        embeddings = np.zeros((len(df), 768), dtype=np.float32)

    X, _, _ = _erstelle_feature_matrix(df, embeddings, encoder=encoder, pca=pca)
    y_pred_log = modell.predict(X)
    return np.expm1(y_pred_log)


# ---------------------------------------------------------------------------
# Artefakt-Hilfsfunktionen
# ---------------------------------------------------------------------------

def _speichere_modell(modell: XGBRegressor, encoder: OrdinalEncoder, pca: PCA | None) -> None:
    with MODELL_PKL.open("wb") as f:
        pickle.dump({"modell": modell, "pca": pca}, f)
    with ENCODER_PKL.open("wb") as f:
        pickle.dump(encoder, f)
    logger.info("[Speichern v2] Modell → %s | Encoder → %s", MODELL_PKL, ENCODER_PKL)


def _lade_modell() -> tuple[XGBRegressor, OrdinalEncoder, PCA | None]:
    if not MODELL_PKL.exists():
        raise FileNotFoundError(
            f"Kein trainiertes v2-Modell unter {MODELL_PKL}. "
            "Bitte zuerst train() aufrufen."
        )
    with MODELL_PKL.open("rb") as f:
        artefakte = pickle.load(f)
    modell = artefakte["modell"]
    pca    = artefakte.get("pca")
    with ENCODER_PKL.open("rb") as f:
        encoder = pickle.load(f)
    return modell, encoder, pca


def _erstelle_importance_plot(modell: XGBRegressor, n_features: int, pca: PCA | None) -> None:
    """Top-20 Features nach Gain, PCA-Komponenten zusammengefasst."""
    importances = modell.get_booster().get_score(importance_type="gain")

    # Feature-Namen: kategoriale + numerische + PCA-Komponenten
    n_pca = pca.n_components_ if pca else 0
    n_basis = len(KATEGORIALE_FEATURES) + len(NUMERISCHE_FEATURES)
    feature_namen = (
        KATEGORIALE_FEATURES
        + NUMERISCHE_FEATURES
        + [f"pca_{i}" for i in range(n_pca)]
    )

    werte = [importances.get(f"f{i}", 0.0) for i in range(len(feature_namen))]
    gesamt = sum(werte) or 1.0
    prozente = [100 * w / gesamt for w in werte]

    # Top-20 nach Wichtigkeit
    sortiert = sorted(zip(prozente, feature_namen), reverse=True)[:20]
    prozente_sort, namen_sort = zip(*sortiert)

    fig, ax = plt.subplots(figsize=(10, 6))
    farben = ["#2563eb" if p == max(prozente_sort) else "#93c5fd" for p in prozente_sort]
    balken = ax.barh(namen_sort, prozente_sort, color=farben, height=0.55)

    for bar, pct in zip(balken, prozente_sort):
        ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                f"{pct:.1f}%", va="center", ha="left", fontsize=8)

    ax.set_xlabel("Relative Importance (Gain) in %", fontsize=11)
    ax.set_title(
        f"Feature Importance – Cost Model v2 (Top 20 von {n_features})",
        fontsize=12, fontweight="bold",
    )
    ax.set_xlim(0, max(prozente_sort) * 1.25)
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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s",
                        datefmt="%H:%M:%S")

    from estimateiq.models.bert_extractor import anreichere_dataframe, berechne_embeddings_gecacht

    eingabe = Path("data/processed/notices.parquet")
    if not eingabe.exists():
        raise SystemExit(f"Nicht gefunden: {eingabe}\nBitte zuerst: python -m estimateiq.data.preprocess")

    df = pd.read_parquet(eingabe)
    logger.info("%d Zeilen geladen.", len(df))

    texte = df["beschreibung"].fillna("").tolist()
    embeddings = berechne_embeddings_gecacht(texte)
    df = anreichere_dataframe(df)

    metriken = train(df, embeddings=embeddings)

    trenner = "─" * 52
    print(f"\n{trenner}")
    print("  EstimateIQ – Cost Model v2 (PCA+BERT)  Ergebnis")
    print(trenner)
    print(f"  RMSE auf Testmenge:  {metriken['rmse_eur']:>14,.0f} €")
    print(f"  R² auf Testmenge:    {metriken['r2']:>14.4f}")
    print(f"  RMSE (log-Raum):     {metriken['rmse_log']:>14.4f}")
    print(f"  Features gesamt:     {metriken['n_features']:>14,}")
    print(f"  davon PCA:           {metriken['n_pca_features']:>14,}")
    print(f"  Train/Test:          {metriken['n_train']:,} / {metriken['n_test']:,}")
    print(f"{trenner}\n")
