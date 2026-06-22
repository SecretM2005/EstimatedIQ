"""
ML-Grössenklassifikator für IT-Projekte.

Modell: XGBoost Klassifikator
Features: TF-IDF (10.000 Terms, Bigramme) + TruncatedSVD (30 Komponenten)
Klassen: klein (0) / mittel (1) / gross (2)
Training: data/size_labels.jsonl

Artefakte: models/size_classifier.pkl
"""

import logging
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, confusion_matrix
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

logger = logging.getLogger(__name__)

MODELL_DIR  = Path("models")
MODELL_PKL  = MODELL_DIR / "size_classifier.pkl"

KLASSEN     = ["klein", "mittel", "gross"]
KLASSEN_IDX = {k: i for i, k in enumerate(KLASSEN)}
N_SVD       = 30


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(df: pd.DataFrame) -> dict:
    """
    Trainiert den Grössenklassifikator auf einem DataFrame.

    Args:
        df: DataFrame mit Spalten 'beschreibung' und 'groesse'

    Returns:
        Metriken: accuracy, confusion_matrix, n_train, n_test, n_per_class
    """
    logger.info("[Groesse] Starte Training Grössenklassifikator...")

    # Eingabedaten validieren
    if "beschreibung" not in df.columns or "groesse" not in df.columns:
        raise ValueError("DataFrame benötigt Spalten 'beschreibung' und 'groesse'.")

    df = df[df["beschreibung"].notna() & df["groesse"].notna()].copy()
    df["beschreibung"] = df["beschreibung"].astype(str)
    df["groesse"] = df["groesse"].str.strip().str.lower()
    df = df[df["groesse"].isin(KLASSEN)].reset_index(drop=True)

    n_gesamt = len(df)
    logger.info("[Groesse] %d gültige Trainingsbeispiele nach Filterung.", n_gesamt)

    if n_gesamt < 10:
        raise ValueError(
            f"Zu wenig Trainingsdaten: {n_gesamt} (Minimum: 10). "
            "Bitte zuerst: python -m estimateiq.data.fetch_size_labels"
        )

    n_per_class = {k: int((df["groesse"] == k).sum()) for k in KLASSEN}
    logger.info("[Groesse] Klassenverteilung: %s", n_per_class)

    y = df["groesse"].map(KLASSEN_IDX).values

    # Stratifizierter Train/Test-Split
    idx = np.arange(n_gesamt)
    try:
        idx_train, idx_test = train_test_split(
            idx, test_size=0.20, random_state=42, stratify=y
        )
    except ValueError:
        # Fallback ohne Stratifizierung bei sehr kleinen Datensätzen
        idx_train, idx_test = train_test_split(idx, test_size=0.20, random_state=42)

    df_train = df.iloc[idx_train].reset_index(drop=True)
    df_test  = df.iloc[idx_test].reset_index(drop=True)
    y_train  = y[idx_train]
    y_test   = y[idx_test]

    # TF-IDF + SVD Features
    texte_train = df_train["beschreibung"].tolist()
    texte_test  = df_test["beschreibung"].tolist()

    tfidf = TfidfVectorizer(
        max_features=10_000,
        min_df=1,
        sublinear_tf=True,
        ngram_range=(1, 2),
        analyzer="word",
    )
    mat_train = tfidf.fit_transform(texte_train)

    n_k = min(N_SVD, mat_train.shape[1] - 1, mat_train.shape[0] - 1)
    svd = TruncatedSVD(n_components=n_k, random_state=42)
    X_train = svd.fit_transform(mat_train).astype(np.float32)

    mat_test = tfidf.transform(texte_test)
    X_test   = svd.transform(mat_test).astype(np.float32)

    logger.info(
        "[Groesse] TF-IDF Vokabular: %d | SVD: %d Komponenten | "
        "Split: %d Train / %d Test",
        len(tfidf.vocabulary_), n_k, len(X_train), len(X_test),
    )

    # XGBoost Klassifikator
    modell = XGBClassifier(
        objective="multi:softmax",
        num_class=3,
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=-1,
        eval_metric="mlogloss",
        early_stopping_rounds=30,
    )
    modell.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )

    y_pred = modell.predict(X_test)
    acc    = float(accuracy_score(y_test, y_pred))
    cm     = confusion_matrix(y_test, y_pred, labels=[0, 1, 2]).tolist()

    logger.info("[Groesse] Accuracy: %.1f%%", acc * 100)
    logger.info("[Groesse] Konfusionsmatrix (klein/mittel/gross):\n%s", cm)

    # Modell speichern
    MODELL_DIR.mkdir(parents=True, exist_ok=True)
    _speichere_modell(modell, tfidf, svd)

    return {
        "accuracy":         acc,
        "confusion_matrix": cm,
        "n_train":          len(X_train),
        "n_test":           len(X_test),
        "n_per_class":      n_per_class,
    }


# ---------------------------------------------------------------------------
# Vorhersage
# ---------------------------------------------------------------------------

def predict(beschreibungen: list[str]) -> list[str]:
    """
    Klassifiziert eine Liste von Projektbeschreibungen.

    Args:
        beschreibungen: Liste von Projektbeschreibungstexten

    Returns:
        Liste von Grössenklassen: "klein", "mittel" oder "gross"
    """
    modell, tfidf, svd = _lade_modell()
    mat = tfidf.transform(beschreibungen)
    X   = svd.transform(mat).astype(np.float32)
    idx = modell.predict(X).astype(int)
    return [KLASSEN[i] for i in idx]


def predict_proba(beschreibungen: list[str]) -> list[dict]:
    """
    Gibt Klassenwahrscheinlichkeiten für eine Liste von Beschreibungen zurück.

    Args:
        beschreibungen: Liste von Projektbeschreibungstexten

    Returns:
        Liste von Dictionaries: [{klein: p, mittel: p, gross: p}, ...]
    """
    modell, tfidf, svd = _lade_modell()
    mat    = tfidf.transform(beschreibungen)
    X      = svd.transform(mat).astype(np.float32)
    probas = modell.predict_proba(X)

    ergebnisse = []
    for proba_zeile in probas:
        ergebnisse.append({
            k: round(float(proba_zeile[i]), 4)
            for i, k in enumerate(KLASSEN)
        })
    return ergebnisse


# ---------------------------------------------------------------------------
# Artefakt-Hilfsfunktionen
# ---------------------------------------------------------------------------

def _speichere_modell(modell, tfidf, svd) -> None:
    """Speichert Modell-Artefakte als Pickle."""
    with MODELL_PKL.open("wb") as f:
        pickle.dump({"modell": modell, "tfidf": tfidf, "svd": svd}, f)
    logger.info("[Groesse] Modell gespeichert: %s", MODELL_PKL)


def _lade_modell() -> tuple:
    """
    Lädt (modell, tfidf, svd).

    Raises:
        FileNotFoundError: wenn das Modell noch nicht trainiert wurde
    """
    if not MODELL_PKL.exists():
        raise FileNotFoundError(
            f"Kein trainiertes Grössenklassifikator-Modell unter {MODELL_PKL}. "
            "Bitte zuerst: python train.py --only size"
        )
    with MODELL_PKL.open("rb") as f:
        art = pickle.load(f)
    return art["modell"], art["tfidf"], art["svd"]


# ---------------------------------------------------------------------------
# CLI Hauptprogramm
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    labels_pfad = Path("data/size_labels.jsonl")
    if not labels_pfad.exists():
        logger.info("[Groesse] Labels nicht gefunden – erstelle via fetch_size_labels...")
        from estimateiq.data.fetch_size_labels import erstelle_labels
        erstelle_labels()

    # Labels laden
    eintraege = []
    with labels_pfad.open("r", encoding="utf-8") as f:
        for zeile in f:
            zeile = zeile.strip()
            if zeile:
                try:
                    eintraege.append(json.loads(zeile))
                except json.JSONDecodeError:
                    pass

    if not eintraege:
        logger.error("[Groesse] Keine Labels in %s gefunden.", labels_pfad)
        sys.exit(1)

    df_labels = pd.DataFrame(eintraege)
    metriken  = train(df_labels)

    print(f"\n[Groesse] Training abgeschlossen:")
    print(f"  Accuracy:  {metriken['accuracy']:.1%}")
    print(f"  Train:     {metriken['n_train']}")
    print(f"  Test:      {metriken['n_test']}")
    print(f"  Klassen:   {metriken['n_per_class']}")
    print(f"  Konfusionsmatrix (klein/mittel/gross):")
    for i, zeile in enumerate(metriken["confusion_matrix"]):
        print(f"    {KLASSEN[i]:<8}: {zeile}")

    # Testprojekte
    testfaelle = [
        ("WooCommerce-Shop 500 Produkte Stripe PayPal", "klein"),
        ("SAP HR Portal 800 Nutzer React Java Backend SSO", "gross"),
        ("Buchungssystem Physiotherapie 5 Therapeuten", "klein"),
        ("CRM-System Vertrieb 50 Nutzer Pipelines Reporting", "mittel"),
        ("ERP-Einfuehrung Konzern 1500 Anwender Migration", "gross"),
    ]

    print("\n[Groesse] Testprojekte:")
    for beschreibung, erwartet in testfaelle:
        probas = predict_proba([beschreibung])[0]
        vorhergesagt = max(probas, key=probas.get)
        ok = "OK" if vorhergesagt == erwartet else "FEHLER"
        print(
            f"  [{ok}] {beschreibung[:45]:<45} → {vorhergesagt} "
            f"(erwartet: {erwartet}, "
            f"klein={probas['klein']:.2f} mittel={probas['mittel']:.2f} gross={probas['gross']:.2f})"
        )
