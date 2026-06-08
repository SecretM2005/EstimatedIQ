"""
Random-Forest-Modell zur Risikoklassifikation von IT-Ausschreibungen.
Klassen: 0 = niedriges Risiko, 1 = mittleres Risiko, 2 = hohes Risiko
"""

import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.utils.class_weight import compute_class_weight

logger = logging.getLogger(__name__)

MODEL_PATH = "models/risk_model.joblib"
ENCODERS_PATH = "models/risk_label_encoders.joblib"

CATEGORICAL_COLS = ["cpv_category", "country", "contract_type", "procedure_type"]
NUMERIC_COLS = ["duration_days", "cpv_code", "estimated_value_eur"]

RISK_LABELS = {0: "niedrig", 1: "mittel", 2: "hoch"}


def _assign_risk_label(df: pd.DataFrame) -> np.ndarray:
    """
    Weist Risikoklassen heuristisch zu (wird später durch annotierte Daten ersetzt).
    Kriterien: Auftragswert, Laufzeit, Verfahrensart.
    """
    risk = np.zeros(len(df), dtype=int)

    # Hohe Werte oder sehr kurze Laufzeiten → erhöhtes Risiko
    if "estimated_value_eur" in df.columns:
        high_value = df["estimated_value_eur"].fillna(0) > 1_000_000
        risk = np.where(high_value, np.maximum(risk, 1), risk)

        very_high = df["estimated_value_eur"].fillna(0) > 10_000_000
        risk = np.where(very_high, 2, risk)

    if "duration_days" in df.columns:
        short_contract = (df["duration_days"].fillna(999) < 60)
        risk = np.where(short_contract, np.maximum(risk, 1), risk)

    # Verhandlungsverfahren → erhöhtes Risiko
    if "procedure_type" in df.columns:
        negotiated = df["procedure_type"].astype(str).str.contains("2|3", na=False)
        risk = np.where(negotiated, np.maximum(risk, 1), risk)

    return risk


def _prepare_features(df: pd.DataFrame, embeddings: np.ndarray, encoders: dict | None = None):
    """Feature-Matrix aufbauen (analog zu cost_model, mit Risikomodell-Spalten)."""
    fit_mode = encoders is None
    if fit_mode:
        encoders = {}

    parts = []

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
            known = set(enc.classes_)
            col_values = col_values.map(lambda x: x if x in known else enc.classes_[0])
            encoded = enc.transform(col_values).reshape(-1, 1)
        parts.append(encoded.astype(np.float32))

    for col in NUMERIC_COLS:
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce").fillna(0).values.reshape(-1, 1)
            parts.append(vals.astype(np.float32))

    parts.append(embeddings.astype(np.float32))

    X = np.hstack(parts)
    return X, encoders


def train(df: pd.DataFrame, embeddings: np.ndarray) -> dict:
    """
    Trainiert den Random-Forest-Klassifikator.
    Gibt Evaluationsmetriken zurück.
    """
    df_train = df.reset_index(drop=True)
    y = _assign_risk_label(df_train)

    X, encoders = _prepare_features(df_train, embeddings)
    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.15, random_state=42, stratify=y)

    # Klassengewichte für unbalancierte Verteilung
    classes = np.unique(y_train)
    weights = compute_class_weight("balanced", classes=classes, y=y_train)
    class_weight = dict(zip(classes, weights))

    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=12,
        min_samples_leaf=5,
        class_weight=class_weight,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    accuracy = float((model.predict(X_val) == y_val).mean())
    logger.info("Risikomodell trainiert: Accuracy=%.1f%%", accuracy * 100)

    Path(MODEL_PATH).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    joblib.dump(encoders, ENCODERS_PATH)

    return {"accuracy": accuracy, "n_train": len(X_train), "n_val": len(X_val), "classes": classes.tolist()}


def predict(df: pd.DataFrame, embeddings: np.ndarray) -> dict:
    """
    Gibt Risikoklasse (int) und Wahrscheinlichkeiten pro Klasse zurück.
    """
    model = joblib.load(MODEL_PATH)
    encoders = joblib.load(ENCODERS_PATH)

    X, _ = _prepare_features(df, embeddings, encoders=encoders)
    classes = model.predict(X)
    probas = model.predict_proba(X)

    return {
        "risk_class": classes.tolist(),
        "risk_label": [RISK_LABELS[c] for c in classes],
        "probabilities": probas.tolist(),
    }
