"""
XGBoost-Kostenschätzungsmodell – Version 1 (rein numerisch, kein BERT).

Features:  dauer_tage, land (ordinalkodiert), projekttyp (ordinalkodiert),
           beschreibung_laenge
Ziel:      budget_eur  (intern log1p-transformiert, Ausgabe in EUR)

Artefakte  (unter models/):
  cost_model_v1.pkl          – trainiertes XGBoost-Modell
  cost_encoders_v1.pkl       – OrdinalEncoder für land + projekttyp
  feature_importance_v1.png  – Balkendiagramm der Feature-Wichtigkeiten
"""

import logging
import pickle
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # kein Display nötig
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

MODELL_DIR     = Path("models")
MODELL_PKL     = MODELL_DIR / "cost_model_v1.pkl"
ENCODER_PKL    = MODELL_DIR / "cost_encoders_v1.pkl"
PLOT_PNG       = MODELL_DIR / "feature_importance_v1.png"

# ---------------------------------------------------------------------------
# Feature-Definitionen
# ---------------------------------------------------------------------------

KATEGORIALE_FEATURES = ["land", "projekttyp"]
NUMERISCHE_FEATURES  = ["dauer_tage", "beschreibung_laenge"]

# Reihenfolge im Feature-Vektor (muss bei predict identisch sein)
ALLE_FEATURES = KATEGORIALE_FEATURES + NUMERISCHE_FEATURES


# ---------------------------------------------------------------------------
# Schritt 1 – Feature Engineering
# ---------------------------------------------------------------------------

def _feature_engineering(df: pd.DataFrame) -> pd.DataFrame:
    """
    Leitet zusätzliche Spalten ab, die nicht direkt aus den Rohdaten kommen.
    Gibt eine Kopie des DataFrames zurück.
    """
    df = df.copy()
    # Textlänge als Proxy für Ausschreibungsdetailgrad
    df["beschreibung_laenge"] = df["beschreibung"].str.len().fillna(0).astype("float32")
    return df


def _erstelle_feature_matrix(
    df: pd.DataFrame,
    encoder: OrdinalEncoder | None = None,
) -> tuple[np.ndarray, OrdinalEncoder]:
    """
    Baut die Feature-Matrix X auf.

    - Kategoriale Spalten werden mit OrdinalEncoder kodiert
      (unbekannte Werte beim Predict → -1).
    - Numerische Spalten werden auf 0 imputed (NaN-sicher).

    Gibt (X float32, encoder) zurück.
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

    X = np.hstack([kat_werte, num_werte])
    return X, encoder


# ---------------------------------------------------------------------------
# Schritt 2 – Training
# ---------------------------------------------------------------------------

def train(df: pd.DataFrame, test_anteil: float = 0.20) -> dict:
    """
    Trainiert das XGBoost-Modell auf dem bereinigten DataFrame aus preprocess.py.

    Ablauf:
      1. Feature Engineering (beschreibung_laenge ableiten)
      2. Zeilen ohne budget_eur verwerfen
      3. Train/Test-Split (stratifiziert nach log-Budget-Quartilen)
      4. Feature-Matrix aufbauen, OrdinalEncoder fitten
      5. XGBoost mit Early Stopping trainieren
      6. RMSE & R² auf Testmenge berechnen (Original-EUR-Raum)
      7. Modell, Encoder und Feature-Importance-Plot speichern

    Args:
        df:           DataFrame aus preprocess_pipeline()
        test_anteil:  Anteil Testmenge (Standard: 20 %)

    Returns:
        dict mit rmse_eur, r2, n_train, n_test, best_iteration
    """
    logger.info("[Training] Starte XGBoost-Training (v1, rein numerisch)...")

    # --- Feature Engineering ---
    df = _feature_engineering(df)

    # --- Nur Zeilen mit bekanntem Budget ---
    df_sauber = df[df["budget_eur"].notna()].reset_index(drop=True)
    n_gesamt  = len(df)
    n_sauber  = len(df_sauber)
    logger.info(
        "[Training] %d/%d Zeilen mit budget_eur – %d ohne Budget verworfen.",
        n_sauber, n_gesamt, n_gesamt - n_sauber,
    )

    if n_sauber < 50:
        raise ValueError(
            f"Zu wenig Trainingsdaten: {n_sauber} Zeilen mit Budget "
            f"(Minimum: 50). Mehr Daten über fetch_ted.py laden."
        )

    # --- Zielvariable log1p-transformieren (Budget ist rechtsschief) ---
    y_log = np.log1p(df_sauber["budget_eur"].values.astype(np.float64))

    # --- Feature-Matrix ---
    X, encoder = _erstelle_feature_matrix(df_sauber)

    # --- Train/Test-Split (stratifiziert nach Budget-Quartil) ---
    quartile = pd.qcut(y_log, q=4, labels=False, duplicates="drop")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y_log,
        test_size=test_anteil,
        random_state=42,
        stratify=quartile,
    )
    logger.info(
        "[Training] Split: %d Training / %d Test (%.0f%%/%.0f%%).",
        len(X_train), len(X_test),
        100 * (1 - test_anteil), 100 * test_anteil,
    )

    # --- Modell konfigurieren ---
    modell = XGBRegressor(
        n_estimators=500,
        learning_rate=0.03,
        max_depth=5,
        min_child_weight=5,
        subsample=0.8,
        colsample_bytree=1.0,  # alle 4 Features bei jedem Split sichtbar
        reg_alpha=0.05,
        reg_lambda=1.5,
        random_state=42,
        n_jobs=-1,
        eval_metric="rmse",
        early_stopping_rounds=40,
    )

    modell.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )

    # --- Metriken im Original-EUR-Raum ---
    y_pred_log = modell.predict(X_test)
    y_pred_eur = np.expm1(y_pred_log)
    y_true_eur = np.expm1(y_test)

    rmse_eur = float(np.sqrt(mean_squared_error(y_true_eur, y_pred_eur)))
    r2       = float(r2_score(y_true_eur, y_pred_eur))
    # RMSE auch im Log-Raum (skalarunabhängig, gut für relative Güte)
    rmse_log = float(np.sqrt(mean_squared_error(y_test, y_pred_log)))

    logger.info(
        "[Training] Ergebnis:\n"
        "  RMSE (EUR):        %16s €\n"
        "  RMSE (log-Raum):   %16.4f\n"
        "  R²:                %16.4f\n"
        "  Best iteration:    %16d",
        f"{rmse_eur:,.0f}",
        rmse_log,
        r2,
        modell.best_iteration,
    )

    # --- Artefakte speichern ---
    MODELL_DIR.mkdir(parents=True, exist_ok=True)
    _speichere_modell(modell, encoder)
    _erstelle_importance_plot(modell)

    return {
        "rmse_eur":      rmse_eur,
        "rmse_log":      rmse_log,
        "r2":            r2,
        "n_train":       len(X_train),
        "n_test":        len(X_test),
        "best_iteration": modell.best_iteration,
    }


# ---------------------------------------------------------------------------
# Schritt 3 – Vorhersage
# ---------------------------------------------------------------------------

def predict(df: pd.DataFrame, **_kwargs) -> np.ndarray:
    """
    Sagt Auftragswerte in EUR voraus.

    Args:
        df: DataFrame (mindestens: land, projekttyp, dauer_tage, beschreibung)
        **_kwargs: Werden ignoriert (Kompatibilität mit Cost Model v2 Signatur)
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
    """Serialisiert Modell und Encoder als separate .pkl-Dateien."""
    with MODELL_PKL.open("wb") as f:
        pickle.dump(modell, f)
    with ENCODER_PKL.open("wb") as f:
        pickle.dump(encoder, f)
    logger.info("[Speichern] Modell → %s | Encoder → %s", MODELL_PKL, ENCODER_PKL)


def _lade_modell() -> tuple[XGBRegressor, OrdinalEncoder]:
    """Lädt Modell und Encoder aus .pkl-Dateien."""
    if not MODELL_PKL.exists():
        raise FileNotFoundError(
            f"Kein trainiertes Modell unter {MODELL_PKL}. "
            "Bitte zuerst train() aufrufen."
        )
    with MODELL_PKL.open("rb") as f:
        modell = pickle.load(f)
    with ENCODER_PKL.open("rb") as f:
        encoder = pickle.load(f)
    return modell, encoder


def _erstelle_importance_plot(modell: XGBRegressor) -> None:
    """
    Speichert einen horizontalen Balkenplot der Feature Importances (gain).
    Sortiert nach Wichtigkeit, beschriftet mit Prozentwerten.
    """
    importances = modell.get_booster().get_score(importance_type="gain")

    # Fehlende Features (Importance = 0) auffüllen
    for feat in ALLE_FEATURES:
        importances.setdefault(f"f{ALLE_FEATURES.index(feat)}", 0.0)

    # Feature-Namen zuordnen (XGBoost nutzt intern f0, f1, ...)
    namen    = [ALLE_FEATURES[i] for i in range(len(ALLE_FEATURES))]
    werte    = [importances.get(f"f{i}", 0.0) for i in range(len(ALLE_FEATURES))]
    gesamt   = sum(werte) or 1.0
    prozente = [100 * w / gesamt for w in werte]

    # Nach Wichtigkeit sortieren
    sortiert = sorted(zip(prozente, namen), reverse=True)
    prozente_sort, namen_sort = zip(*sortiert)

    fig, ax = plt.subplots(figsize=(8, 4))
    farben = ["#2563eb" if p == max(prozente_sort) else "#93c5fd" for p in prozente_sort]
    balken = ax.barh(namen_sort, prozente_sort, color=farben, height=0.5)

    # Prozentwert rechts neben Balken
    for bar, pct in zip(balken, prozente_sort):
        ax.text(
            bar.get_width() + 0.5,
            bar.get_y() + bar.get_height() / 2,
            f"{pct:.1f}%",
            va="center", ha="left", fontsize=10,
        )

    ax.set_xlabel("Relative Importance (Gain) in %", fontsize=11)
    ax.set_title("Feature Importance – EstimateIQ Cost Model v1", fontsize=13, fontweight="bold")
    ax.set_xlim(0, max(prozente_sort) * 1.20)
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)

    plt.tight_layout()
    fig.savefig(PLOT_PNG, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("[Plot] Feature-Importance gespeichert: %s", PLOT_PNG)


# ---------------------------------------------------------------------------
# Direkt ausführbar: python -m estimateiq.models.cost_model
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    eingabe = Path("data/processed/notices.parquet")
    if not eingabe.exists():
        raise SystemExit(
            f"Datei nicht gefunden: {eingabe}\n"
            "Bitte zuerst ausführen: python -m estimateiq.data.preprocess"
        )

    logger.info("Lade vorverarbeitete Daten aus %s ...", eingabe)
    df = pd.read_parquet(eingabe)
    logger.info("  %d Zeilen geladen.", len(df))

    metriken = train(df)

    trenner = "─" * 46
    print(f"\n{trenner}")
    print("  EstimateIQ – Cost Model v1  Ergebnis")
    print(trenner)
    print(f"  RMSE auf Testmenge:  {metriken['rmse_eur']:>12,.0f} €")
    print(f"  R² auf Testmenge:    {metriken['r2']:>12.4f}")
    print(f"  RMSE (log-Raum):     {metriken['rmse_log']:>12.4f}")
    print(f"  Trainingszeilen:     {metriken['n_train']:>12,}")
    print(f"  Testzeilen:          {metriken['n_test']:>12,}")
    print(f"  Best Iteration:      {metriken['best_iteration']:>12,}")
    print(f"\n  Modell:  {MODELL_PKL}")
    print(f"  Encoder: {ENCODER_PKL}")
    print(f"  Plot:    {PLOT_PNG}")
    print(f"{trenner}\n")
