"""
XGBoost-Modell zur Kostenvorhersage für IT-Ausschreibungen.
Kombiniert BERT-Embeddings mit strukturierten Features.
"""

import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBRegressor

logger = logging.getLogger(__name__)

MODEL_PATH = "models/cost_model.joblib"
ENCODERS_PATH = "models/cost_label_encoders.joblib"

# Kategoriale Spalten, die Label-enkodiert werden
CATEGORICAL_COLS = ["cpv_category", "country", "contract_type", "procedure_type", "authority_type"]

# Numerische Spalten ohne Embeddings
NUMERIC_COLS = ["duration_days", "cpv_code"]


def _prepare_features(df: pd.DataFrame, embeddings: np.ndarray, encoders: dict | None = None):
    """
    Erstellt den Feature-Matrix aus DataFrame + BERT-Embeddings.
    Gibt (X, encoders) zurück; encoders wird beim ersten Aufruf befüllt.
    """
    fit_mode = encoders is None
    if fit_mode:
        encoders = {}

    parts = []

    # Kategoriale Features enkodieren
    for col in CATEGORICAL_COLS:
        if col not in df.columns:
            continue
        col_values = df[col].astype(str).fillna("unbekannt")
        if fit_mode:
            enc = LabelEncoder()
            encoded = enc.fit_transform(col_values).reshape(-1, 1)
            encoders[col] = enc
        else:
            enc = encoders[col]
            # Unbekannte Kategorien auf -1 setzen
            known = set(enc.classes_)
            col_values = col_values.map(lambda x: x if x in known else enc.classes_[0])
            encoded = enc.transform(col_values).reshape(-1, 1)
        parts.append(encoded.astype(np.float32))

    # Numerische Features
    for col in NUMERIC_COLS:
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce").fillna(0).values.reshape(-1, 1)
            parts.append(vals.astype(np.float32))

    # BERT-Embeddings anhängen
    parts.append(embeddings.astype(np.float32))

    X = np.hstack(parts)
    return X, encoders


def train(df: pd.DataFrame, embeddings: np.ndarray) -> dict:
    """
    Trainiert das XGBoost-Modell.
    Erwartet, dass df['estimated_value_eur'] die Zielvariable enthält.
    Gibt Evaluationsmetriken zurück.
    """
    # Nur Zeilen mit bekanntem Auftragswert nutzen
    mask = df["has_value"] & df["estimated_value_eur"].notna()
    df_train = df[mask].reset_index(drop=True)
    emb_train = embeddings[mask]

    if len(df_train) < 50:
        raise ValueError(f"Zu wenig Trainingsdaten: {len(df_train)} Zeilen (min. 50 benötigt)")

    # Log-Transformation für rechtsschiefe Werteverteilung
    y = np.log1p(df_train["estimated_value_eur"].values)

    X, encoders = _prepare_features(df_train, emb_train)

    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.15, random_state=42)

    model = XGBRegressor(
        n_estimators=400,
        learning_rate=0.05,
        max_depth=6,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=1.0,
        random_state=42,
        n_jobs=-1,
        eval_metric="rmse",
        early_stopping_rounds=30,
    )

    model.fit(
        X_train,
        y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )

    # Metriken im Log-Raum und Original-Raum berechnen
    y_pred_log = model.predict(X_val)
    y_pred = np.expm1(y_pred_log)
    y_true = np.expm1(y_val)

    mae = float(np.mean(np.abs(y_pred - y_true)))
    mape = float(np.mean(np.abs((y_true - y_pred) / (y_true + 1e-6))) * 100)

    logger.info("Training abgeschlossen: MAE=%.0f EUR, MAPE=%.1f%%", mae, mape)

    # Modell speichern
    Path(MODEL_PATH).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    joblib.dump(encoders, ENCODERS_PATH)

    return {"mae_eur": mae, "mape_pct": mape, "n_train": len(X_train), "n_val": len(X_val)}


def predict(df: pd.DataFrame, embeddings: np.ndarray) -> np.ndarray:
    """
    Sagt Auftragswerte in EUR voraus.
    Gibt ein Array mit vorhergesagten Werten zurück.
    """
    model = joblib.load(MODEL_PATH)
    encoders = joblib.load(ENCODERS_PATH)

    X, _ = _prepare_features(df, embeddings, encoders=encoders)
    log_pred = model.predict(X)
    return np.expm1(log_pred)
