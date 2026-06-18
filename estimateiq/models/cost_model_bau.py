"""
XGBoost-Kostenschätzungsmodell für Bauprojekte.

Zielvariable: log(budget_eur)
Features:     BERT-Embeddings + tabularische Geo/CPV/BBSR-Features
Ausgabe:      Vorhersage in EUR (rücktransformiert via exp)

Artefakte (unter models/):
  cost_model_bau.pkl      – trainiertes XGBoost-Modell
  cost_encoders_bau.pkl   – OrdinalEncoder für kategoriale Spalten
  cost_importance_bau.png – Feature-Importance-Plot (Top 15)
"""

import logging
import pickle
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error, r2_score, median_absolute_error
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OrdinalEncoder
from xgboost import XGBRegressor

logger = logging.getLogger(__name__)

MODELL_DIR   = Path("models")
MODELL_PKL   = MODELL_DIR / "cost_model_bau.pkl"
ENCODER_PKL  = MODELL_DIR / "cost_encoders_bau.pkl"
PLOT_PNG     = MODELL_DIR / "cost_importance_bau.png"

KATEGORIALE_FEATURES = ["gewerk", "projekttyp", "land", "bundesland"]
NUMERISCHE_FEATURES  = [
    "latitude", "longitude", "bbsr_index",
    "ist_metropole", "ist_grossstadt",
    "beschreibung_laenge", "jahr",
    "flaeche_m2", "einheiten", "laenge_m", "hat_flaeche",
    "log_flaeche", "flaeche_je_m2_budget_proxy",
    # Direkte (nicht-log) Skalierungsfeatures: helfen XGBoost bei Großprojekten
    "flaeche_bbsr_raw", "einheiten_bbsr", "log_einheiten",
    "n_gewerke_in_text", "is_generalsanierung", "is_neubau",
]


def _extrahiere_flaeche(text: str) -> float:
    """m² aus Text: '2500m²', '1.500 m²', '500qm', etc."""
    for pat, faktor in [
        (r"(\d[\d.]*)\s*[,.]?\d*\s*(?:m\s*[²2]|qm|Quadratmeter)", 1.0),
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                val = float(m.group(1).replace(".", "").replace(",", "")) * faktor
                if 10 <= val <= 500_000:
                    return val
            except ValueError:
                pass
    return 0.0


def _extrahiere_einheiten(text: str) -> float:
    """Anzahl Wohneinheiten/Wohnungen aus Text."""
    for pat in [
        r"(\d+)\s*(?:Wohneinheit|Wohnung|Appartement|WE\b)",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                val = float(m.group(1))
                if 1 <= val <= 10_000:
                    return val
            except ValueError:
                pass
    return 0.0


def _extrahiere_laenge(text: str) -> float:
    """Länge in Metern aus Text: '2 km', '1,5km', '500 lm'."""
    m = re.search(r"(\d+(?:[,.]\d+)?)\s*km", text, re.IGNORECASE)
    if m:
        try:
            val = float(m.group(1).replace(",", ".")) * 1000
            if 50 <= val <= 200_000:
                return val
        except ValueError:
            pass
    m = re.search(r"(\d+)\s*(?:lm|lfm|Laufmeter)", text, re.IGNORECASE)
    if m:
        try:
            val = float(m.group(1))
            if 10 <= val <= 50_000:
                return val
        except ValueError:
            pass
    return 0.0


def _feature_engineering(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["beschreibung_laenge"] = df["beschreibung"].str.len().fillna(0).astype("float32")
    df["ist_metropole"]  = df.get("ist_metropole",  pd.Series(False, index=df.index)).fillna(False).astype(float)
    df["ist_grossstadt"] = df.get("ist_grossstadt", pd.Series(False, index=df.index)).fillna(False).astype(float)
    texte = df["beschreibung"].fillna("")
    df["flaeche_m2"]  = texte.apply(_extrahiere_flaeche).astype("float32")
    df["einheiten"]   = texte.apply(_extrahiere_einheiten).astype("float32")
    df["laenge_m"]    = texte.apply(_extrahiere_laenge).astype("float32")
    df["hat_flaeche"] = (df["flaeche_m2"] > 0).astype("float32")
    # log-Fläche: linearisiert den Effekt kleiner vs. großer Projekte
    df["log_flaeche"] = np.log1p(df["flaeche_m2"]).astype("float32")
    # Näherungsweise Kosten/m² Proxy: trennt kleine Handwerks- von Großprojekten
    # (ohne Budget-Info, nur als Feature-Signal aus Fläche × BBSR)
    bbsr = df.get("bbsr_index", pd.Series(100.0, index=df.index)).fillna(100.0).astype(float)
    df["flaeche_je_m2_budget_proxy"] = (df["log_flaeche"] * bbsr / 100.0).astype("float32")
    # Direkte Skalierungsfeatures: bessere Diskriminierung von Groß- vs. Kleinprojekten
    df["flaeche_bbsr_raw"] = (df["flaeche_m2"] * bbsr / 100.0).astype("float32")
    df["einheiten_bbsr"]   = (df["einheiten"]  * bbsr / 100.0).astype("float32")
    df["log_einheiten"]    = np.log1p(df["einheiten"]).astype("float32")
    # Semantische Komplexitäts-Flags (ergänzen BERT-Embeddings)
    _texte_lower = texte.str.lower()
    _gewerke_kw = ["elektro", "sanitär", "heizung", "lüftung", "klima", "dach",
                   "fassade", "fenster", "boden", "fliesen", "maler", "putz"]
    df["n_gewerke_in_text"] = sum(
        _texte_lower.str.contains(kw, regex=False).astype("float32")
        for kw in _gewerke_kw
    ).astype("float32")
    df["is_generalsanierung"] = _texte_lower.str.contains(
        "generalsanierung|komplettsanierung|kernsanierung|vollsanierung", regex=True
    ).astype("float32")
    df["is_neubau"] = _texte_lower.str.contains(
        r"\bneubau\b|neuerrichtung|errichtung\s+eines", regex=True
    ).astype("float32")
    return df


def _erstelle_feature_matrix(
    df: pd.DataFrame,
    encoder: OrdinalEncoder | None = None,
    embeddings: np.ndarray | None = None,
) -> tuple[np.ndarray, OrdinalEncoder]:
    fit_modus = encoder is None

    kat_df = df[KATEGORIALE_FEATURES].astype(str).fillna("unbekannt")
    if fit_modus:
        encoder = OrdinalEncoder(
            handle_unknown="use_encoded_value",
            unknown_value=-1,
            dtype=np.float32,
        )
        kat_werte = encoder.fit_transform(kat_df)
    else:
        kat_werte = encoder.transform(kat_df)

    num_werte = (
        df[NUMERISCHE_FEATURES]
        .apply(pd.to_numeric, errors="coerce")
        .fillna(0.0)
        .values.astype(np.float32)
    )

    teile = [kat_werte, num_werte]
    if embeddings is not None:
        teile.append(embeddings.astype(np.float32))

    X = np.hstack(teile)
    return X, encoder


def train(
    df: pd.DataFrame,
    embeddings: np.ndarray | None = None,
    test_anteil: float = 0.20,
) -> dict:
    """
    Trainiert XGBoost-Kostenmodell für Bauprojekte.

    Args:
        df:          DataFrame aus preprocess_bau_pipeline()
        embeddings:  BERT-Embeddings (n_samples × 768), optional
        test_anteil: Anteil Testmenge

    Returns:
        dict mit rmse_eur, r2, mdape, n_train, n_test, best_iteration
    """
    logger.info("[Training] Starte Bau-Kostenmodell-Training...")

    df = _feature_engineering(df)
    df_sauber = df[df["budget_eur"].notna()].reset_index(drop=True)

    if embeddings is not None:
        embeddings = embeddings[df["budget_eur"].notna().values]

    n = len(df_sauber)
    logger.info("[Training] %d Zeilen mit budget_eur.", n)

    if n < 50:
        raise ValueError(f"Zu wenig Trainingsdaten: {n} Zeilen (Minimum: 50).")

    y_log = np.log1p(df_sauber["budget_eur"].values.astype(np.float64))
    X, encoder = _erstelle_feature_matrix(df_sauber, embeddings=embeddings)

    quartile = pd.qcut(y_log, q=4, labels=False, duplicates="drop")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y_log,
        test_size=test_anteil,
        random_state=42,
        stratify=quartile,
    )
    logger.info("[Training] Split: %d Train / %d Test", len(X_train), len(X_test))

    modell = XGBRegressor(
        n_estimators=800,
        learning_rate=0.02,
        max_depth=6,
        min_child_weight=5,
        subsample=0.8,
        colsample_bytree=0.8,
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
    # Median Absolute Percentage Error
    mdape    = float(np.median(np.abs(y_pred_eur - y_true_eur) / np.maximum(y_true_eur, 1)) * 100)

    logger.info(
        "[Training] RMSE: %s € | R²: %.4f | MdAPE: %.1f%% | Best Iter: %d",
        f"{rmse_eur:,.0f}", r2, mdape, modell.best_iteration,
    )

    MODELL_DIR.mkdir(parents=True, exist_ok=True)
    _speichere_modell(modell, encoder)
    _erstelle_importance_plot(modell, embeddings is not None)

    return {
        "rmse_eur":       rmse_eur,
        "r2":             r2,
        "mdape":          mdape,
        "n_train":        len(X_train),
        "n_test":         len(X_test),
        "best_iteration": modell.best_iteration,
    }


def predict(df: pd.DataFrame, embeddings: np.ndarray | None = None) -> np.ndarray:
    """Sagt Projektkosten in EUR voraus."""
    modell, encoder = _lade_modell()
    df = _feature_engineering(df)
    X, _ = _erstelle_feature_matrix(df, encoder=encoder, embeddings=embeddings)
    return np.expm1(modell.predict(X))


def _speichere_modell(modell: XGBRegressor, encoder: OrdinalEncoder) -> None:
    with MODELL_PKL.open("wb") as f:
        pickle.dump(modell, f)
    with ENCODER_PKL.open("wb") as f:
        pickle.dump(encoder, f)
    logger.info("[Speichern] Modell → %s | Encoder → %s", MODELL_PKL, ENCODER_PKL)


def _lade_modell() -> tuple[XGBRegressor, OrdinalEncoder]:
    if not MODELL_PKL.exists():
        raise FileNotFoundError(f"Kein trainiertes Modell unter {MODELL_PKL}.")
    with MODELL_PKL.open("rb") as f:
        modell = pickle.load(f)
    with ENCODER_PKL.open("rb") as f:
        encoder = pickle.load(f)
    return modell, encoder


def _erstelle_importance_plot(modell: XGBRegressor, mit_bert: bool = False) -> None:
    """Feature-Importance-Plot (Top 15, nach Gain)."""
    alle_features = KATEGORIALE_FEATURES + NUMERISCHE_FEATURES
    if mit_bert:
        alle_features += [f"bert_{i}" for i in range(768)]

    try:
        importances = modell.get_booster().get_score(importance_type="gain")
    except Exception:
        return

    paare = []
    for key, val in importances.items():
        try:
            idx = int(key.replace("f", ""))
            name = alle_features[idx] if idx < len(alle_features) else key
        except (ValueError, IndexError):
            name = key
        paare.append((name, val))

    if not paare:
        return

    gesamt = sum(v for _, v in paare) or 1.0
    paare_pct = [(n, 100 * v / gesamt) for n, v in paare]
    paare_pct.sort(key=lambda x: -x[1])
    top15 = paare_pct[:15]

    namen, werte = zip(*top15)

    fig, ax = plt.subplots(figsize=(10, 6))
    farben = ["#1d4ed8" if i == 0 else "#93c5fd" for i in range(len(werte))]
    balken = ax.barh(namen[::-1], werte[::-1], color=farben[::-1], height=0.6)

    for bar, pct in zip(balken, werte[::-1]):
        ax.text(
            bar.get_width() + 0.3,
            bar.get_y() + bar.get_height() / 2,
            f"{pct:.1f}%",
            va="center", ha="left", fontsize=9,
        )

    ax.set_xlabel("Relative Importance (Gain) in %", fontsize=11)
    ax.set_title("Feature Importance – Bau Cost Model (Top 15)", fontsize=13, fontweight="bold")
    ax.set_xlim(0, max(werte) * 1.25)
    ax.grid(axis="x", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)

    plt.tight_layout()
    fig.savefig(PLOT_PNG, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("[Plot] Feature-Importance gespeichert: %s", PLOT_PNG)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")

    eingabe = Path("data/processed/notices_bau.parquet")
    if not eingabe.exists():
        raise SystemExit(f"Datei nicht gefunden: {eingabe}")

    df = pd.read_parquet(eingabe)
    metriken = train(df)

    print(f"\n{'─'*46}")
    print("  Bau Cost Model – Ergebnis")
    print(f"{'─'*46}")
    print(f"  RMSE:          {metriken['rmse_eur']:>14,.0f} €")
    print(f"  R²:            {metriken['r2']:>14.4f}")
    print(f"  MdAPE:         {metriken['mdape']:>13.1f} %")
    print(f"  Trainings-N:   {metriken['n_train']:>14,}")
    print(f"  Test-N:        {metriken['n_test']:>14,}")
    print(f"  Best Iter:     {metriken['best_iteration']:>14,}")
    print(f"{'─'*46}\n")
