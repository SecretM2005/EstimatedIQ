"""
XGBoost-Kostenschätzungsmodell – Version 3 (TF-IDF + SVD + erweiterte Features).

Verbesserungen gegenüber v2:
  1. Budget-Distributions-Plot (Ausreißer-Diagnose) → models/budget_distribution.png
  2. Neue Features:
       beschreibung_wortanzahl  – Wortanzahl der Beschreibung
       hat_deadline             – Bool: hat ein Enddatum
       tag_rate_ref             – Target-Encoding: medianer Tagespreis je Projekttyp
                                  (nur auf Trainingsdaten berechnet → kein Leakage)
     HINWEIS: "budget_pro_tag = budget / dauer_tage" wäre Target-Leakage (budget ist
     die Zielvariable), daher ersetzt durch target-encodierten Referenzwert.
  3. Huber-Loss (reg:pseudohubererror) – robust gegen extreme Budget-Ausreißer
  4. 75 SVD-Komponenten statt 50
  5. Mehr TF-IDF-Features (25.000 statt 20.000)
  6. Beide RMSE-Metriken: gesamt und ohne extreme Ausreißer (≤p95)

Features gesamt (86):
  Kategoriale (2):  land, projekttyp
  Numerische  (9):  dauer_tage, beschreibung_laenge, beschreibung_wortanzahl,
                    hat_deadline, tag_rate_ref, komplexitaet,
                    schnittstellen_anzahl, technologien_anzahl, cpv_num
  SVD-Text   (75):  TruncatedSVD aus TF-IDF auf 'beschreibung'

Artefakte (unter models/):
  cost_model_v3.pkl       – {modell, tfidf, svd, tag_rate_lookup}
  cost_encoders_v3.pkl    – OrdinalEncoder
  budget_distribution.png – Diagnose-Plot der Budgetverteilung
  feature_importance_v3.png
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

MODELL_DIR  = Path("models")
MODELL_PKL  = MODELL_DIR / "cost_model_v3.pkl"
ENCODER_PKL = MODELL_DIR / "cost_encoders_v3.pkl"
PLOT_PNG    = MODELL_DIR / "feature_importance_v3.png"
BUDGET_PNG  = MODELL_DIR / "budget_distribution.png"

N_SVD_KOMPONENTEN = 75

# ---------------------------------------------------------------------------
# Feature-Definitionen
# ---------------------------------------------------------------------------

KATEGORIALE_FEATURES = ["land", "projekttyp"]
NUMERISCHE_FEATURES  = [
    "dauer_tage",
    "beschreibung_laenge",
    "beschreibung_wortanzahl",   # NEU v3
    "hat_deadline",              # NEU v3
    "tag_rate_ref",              # NEU v3 (target-encoded Tagespreis je Projekttyp)
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

    # Wortanzahl der Beschreibung
    df["beschreibung_wortanzahl"] = (
        df["beschreibung"].str.split().str.len().fillna(0).astype("float32")
    )

    # hat_deadline: vor fillna berechnen, damit NaN-Status korrekt ist
    df["hat_deadline"] = df["dauer_tage"].notna().astype("float32")

    # tag_rate_ref: Platzhalter; wird in train() via target-encoding gesetzt,
    # in predict() via gespeichertem Lookup.
    if "tag_rate_ref" not in df.columns:
        df["tag_rate_ref"] = 0.0
    df["tag_rate_ref"] = df["tag_rate_ref"].astype("float32")

    if "technologien" in df.columns:
        df["technologien_anzahl"] = df["technologien"].apply(
            lambda x: len(x) if isinstance(x, list) else 0
        ).astype("float32")
    else:
        df["technologien_anzahl"] = 0.0

    df["cpv_num"] = (
        pd.to_numeric(df["cpv_code"], errors="coerce").fillna(72000000).astype("float32")
    )

    for col, default in [("komplexitaet", 3.0), ("schnittstellen_anzahl", 0.0)]:
        if col not in df.columns:
            df[col] = default
        df[col] = df[col].astype("float32")

    return df


def _compute_tag_rate_lookup(df_train: pd.DataFrame) -> dict:
    """
    Berechnet medianen Tagespreis (budget_eur / dauer_tage) je Projekttyp.
    Nur auf Trainingsdaten → verhindert Target-Leakage.
    Projekttypen mit < 3 Datenpunkten erhalten den globalen Median.
    """
    maske = (
        df_train["dauer_tage"].notna()
        & df_train["budget_eur"].notna()
        & (pd.to_numeric(df_train["dauer_tage"], errors="coerce") > 0)
    )
    if maske.sum() < 10:
        return {"__global__": 5000.0}

    df_r = df_train[maske].copy()
    df_r["tagesrate"] = (
        df_r["budget_eur"].astype(float)
        / pd.to_numeric(df_r["dauer_tage"], errors="coerce").astype(float)
    )

    # Nur Typen mit ≥3 Datenpunkten bekommen eigenen Median
    gruppengroessen = df_r.groupby("projekttyp").size()
    valide = gruppengroessen[gruppengroessen >= 3].index
    lookup = (
        df_r[df_r["projekttyp"].isin(valide)]
        .groupby("projekttyp")["tagesrate"]
        .median()
        .to_dict()
    )
    lookup["__global__"] = float(df_r["tagesrate"].median())
    return lookup


def _wende_tag_rate_an(df: pd.DataFrame, lookup: dict) -> pd.DataFrame:
    df = df.copy()
    global_rate = lookup.get("__global__", 5000.0)
    df["tag_rate_ref"] = (
        df["projekttyp"].map(lookup).fillna(global_rate).astype("float32")
    )
    return df


def _erstelle_feature_matrix(
    df: pd.DataFrame,
    encoder: OrdinalEncoder | None = None,
    tfidf: TfidfVectorizer | None = None,
    svd: TruncatedSVD | None = None,
) -> tuple[np.ndarray, OrdinalEncoder, TfidfVectorizer, TruncatedSVD]:
    """
    [kategoriale (2)] + [numerische (9)] + [SVD-Textfeatures (≤75)]
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

    texte = df["beschreibung"].fillna("").tolist()
    if fit_modus:
        tfidf = TfidfVectorizer(
            max_features=25_000,
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
            "[v3] TF-IDF Vokabular: %d | SVD: %d Komp. erklären %.1f%% Textvarianz.",
            len(tfidf.vocabulary_), n_komp, erklaert * 100,
        )
    else:
        tfidf_matrix = tfidf.transform(texte)
        svd_werte = svd.transform(tfidf_matrix).astype(np.float32)

    X = np.hstack([kat_werte, num_werte, svd_werte])
    return X, encoder, tfidf, svd


# ---------------------------------------------------------------------------
# Diagnose-Plot: Budget-Verteilung
# ---------------------------------------------------------------------------

def _plot_budget_verteilung(df: pd.DataFrame) -> None:
    """
    Speichert ein zweiteiliges Histogramm der Budget-Verteilung.
    Zeigt das Ausreißer-Problem: linearer Bereich vs. log-Skala.
    """
    budget = df["budget_eur"].dropna().astype(float)
    if len(budget) < 10:
        return

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # --- Links: linearer x-Bereich, log y-Achse → zeigt den langen Schwanz ---
    axes[0].hist(
        budget / 1e6, bins=60, color="#2563eb", alpha=0.75,
        edgecolor="white", linewidth=0.4,
    )
    axes[0].set_yscale("log")
    axes[0].set_xlabel("Budget (Mio €)", fontsize=11)
    axes[0].set_ylabel("Anzahl Projekte (log-Skala)", fontsize=11)
    axes[0].set_title("Budget-Verteilung (linear)", fontsize=12, fontweight="bold")

    for pct_val, pct_label, farbe in [
        (0.50, "Median", "#ef4444"),
        (0.90, "p90",    "#f97316"),
        (0.99, "p99",    "#8b5cf6"),
    ]:
        val = budget.quantile(pct_val) / 1e6
        axes[0].axvline(val, color=farbe, linestyle="--", linewidth=1.5,
                        label=f"{pct_label}: {val:.1f} M €")
    axes[0].legend(fontsize=9)

    # --- Rechts: log₁₀-Skala → zeigt die eigentliche Verteilungsform ---
    log_budget = np.log10(budget[budget > 0])
    axes[1].hist(
        log_budget, bins=40, color="#10b981", alpha=0.75,
        edgecolor="white", linewidth=0.4,
    )
    axes[1].set_xlabel("Budget (EUR, log₁₀-Skala)", fontsize=11)
    axes[1].set_ylabel("Anzahl Projekte", fontsize=11)
    axes[1].set_title("Budget-Verteilung (log₁₀)", fontsize=12, fontweight="bold")

    tick_map = {4: "10K", 5: "100K", 6: "1M", 7: "10M", 8: "100M"}
    tick_pos = [k for k in tick_map if log_budget.min() - 0.5 <= k <= log_budget.max() + 0.5]
    if tick_pos:
        axes[1].set_xticks(tick_pos)
        axes[1].set_xticklabels([tick_map[k] for k in tick_pos])

    stats_text = (
        f"n = {len(budget):,}\n"
        f"Median:  {budget.median()/1e3:,.0f} K €\n"
        f"Mittel:  {budget.mean()/1e6:.2f} M €\n"
        f"p90:     {budget.quantile(0.90)/1e6:.1f} M €\n"
        f"p99:     {budget.quantile(0.99)/1e6:.1f} M €\n"
        f"Maximum: {budget.max()/1e6:.1f} M €"
    )
    axes[1].text(
        0.97, 0.97, stats_text, transform=axes[1].transAxes,
        va="top", ha="right", fontsize=9,
        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.6),
    )

    plt.suptitle(
        "Budget-Verteilung im Trainingsdatensatz – EstimateIQ v3",
        fontsize=13, fontweight="bold",
    )
    plt.tight_layout()
    MODELL_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(BUDGET_PNG, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("[v3] Budget-Verteilungsplot: %s", BUDGET_PNG)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(df: pd.DataFrame, test_anteil: float = 0.20) -> dict:
    """
    Trainiert Cost Model v3.
    Huber-Loss, 75 SVD-Komp., neue Features (Wortanzahl, Deadline, Tagesrate-Ref.).
    """
    logger.info("[Training v3] Starte (TF-IDF+SVD, Huber-Loss, 86 Features)...")

    df = _feature_engineering(df)
    df_sauber = df[df["budget_eur"].notna()].reset_index(drop=True)
    n_sauber = len(df_sauber)
    logger.info("[Training v3] %d/%d Zeilen mit budget_eur.", n_sauber, len(df))

    if n_sauber < 50:
        raise ValueError(f"Zu wenig Trainingsdaten: {n_sauber} Zeilen (Minimum: 50).")

    # Budget-Verteilungsplot vor dem Training
    _plot_budget_verteilung(df_sauber)

    y_log = np.log1p(df_sauber["budget_eur"].values.astype(np.float64))

    # Stratifizierter Split auf Index-Ebene
    # (Split zuerst, dann Target-Encoding – verhindert Leakage)
    quartile = (
        pd.qcut(pd.Series(y_log), q=4, labels=False, duplicates="drop")
        .fillna(0)
        .values
    )
    idx_alle = np.arange(n_sauber)
    idx_train, idx_test = train_test_split(
        idx_alle, test_size=test_anteil, random_state=42, stratify=quartile,
    )
    df_train = df_sauber.iloc[idx_train].reset_index(drop=True)
    df_test  = df_sauber.iloc[idx_test].reset_index(drop=True)
    y_train  = y_log[idx_train]
    y_test   = y_log[idx_test]

    # Target-Encoding: Tagespreis-Referenz je Projekttyp (nur Trainingsdaten)
    tag_rate_lookup = _compute_tag_rate_lookup(df_train)
    df_train = _wende_tag_rate_an(df_train, tag_rate_lookup)
    df_test  = _wende_tag_rate_an(df_test,  tag_rate_lookup)
    logger.info(
        "[v3] Tag-Rate-Lookup: %d Projekttypen | globale Tagesrate: %,.0f €/Tag",
        len(tag_rate_lookup) - 1, tag_rate_lookup.get("__global__", 0),
    )

    # Feature-Matrizen
    X_train, encoder, tfidf, svd = _erstelle_feature_matrix(df_train)
    X_test,  _,       _,    _   = _erstelle_feature_matrix(
        df_test, encoder=encoder, tfidf=tfidf, svd=svd,
    )
    logger.info("[Training v3] Split: %d Training / %d Test, %d Features.",
                len(X_train), len(X_test), X_train.shape[1])

    modell = XGBRegressor(
        n_estimators=800,
        learning_rate=0.015,
        max_depth=5,
        min_child_weight=5,
        subsample=0.8,
        colsample_bytree=0.5,
        reg_alpha=0.1,
        reg_lambda=2.0,
        objective="reg:pseudohubererror",
        huber_slope=1.0,
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

    # Metriken auf p95-Subset: Zeigt Modellgüte ohne extreme Großprojekte
    p95_grenze = float(np.percentile(y_true_eur, 95))
    maske_p95  = y_true_eur <= p95_grenze
    rmse_p95   = float(np.sqrt(mean_squared_error(y_true_eur[maske_p95], y_pred_eur[maske_p95])))
    r2_p95     = float(r2_score(y_true_eur[maske_p95], y_pred_eur[maske_p95]))

    logger.info(
        "[Training v3] Ergebnis:\n"
        "  RMSE (EUR, gesamt):  %16s €\n"
        "  RMSE (EUR, ≤p95):    %16s €   (p95 = %s €)\n"
        "  RMSE (log):          %16.4f\n"
        "  R²  (gesamt):        %16.4f\n"
        "  R²  (≤p95):          %16.4f\n"
        "  Best iteration:      %16d",
        f"{rmse_eur:,.0f}", f"{rmse_p95:,.0f}", f"{p95_grenze:,.0f}",
        rmse_log, r2, r2_p95, modell.best_iteration,
    )

    MODELL_DIR.mkdir(parents=True, exist_ok=True)
    _speichere_modell(modell, encoder, tfidf, svd, tag_rate_lookup)
    _erstelle_importance_plot(modell, X_train.shape[1])

    return {
        "rmse_eur":       rmse_eur,
        "rmse_p95":       rmse_p95,
        "rmse_log":       rmse_log,
        "r2":             r2,
        "r2_p95":         r2_p95,
        "n_train":        len(X_train),
        "n_test":         len(X_test),
        "best_iteration": modell.best_iteration,
        "n_features":     X_train.shape[1],
        "n_svd_features": svd.n_components,
        "p95_budget_eur": p95_grenze,
    }


# ---------------------------------------------------------------------------
# Vorhersage
# ---------------------------------------------------------------------------

def predict(df: pd.DataFrame, **_kwargs) -> np.ndarray:
    """Sagt Auftragswerte in EUR voraus. Ignoriert unbekannte kwargs (z. B. embeddings)."""
    modell, encoder, tfidf, svd, tag_rate_lookup = _lade_modell()
    df = _feature_engineering(df)
    df = _wende_tag_rate_an(df, tag_rate_lookup)
    X, _, _, _ = _erstelle_feature_matrix(df, encoder=encoder, tfidf=tfidf, svd=svd)
    return np.expm1(modell.predict(X))


# ---------------------------------------------------------------------------
# Artefakt-Hilfsfunktionen
# ---------------------------------------------------------------------------

def _speichere_modell(modell, encoder, tfidf, svd, tag_rate_lookup) -> None:
    with MODELL_PKL.open("wb") as f:
        pickle.dump(
            {"modell": modell, "tfidf": tfidf, "svd": svd,
             "tag_rate_lookup": tag_rate_lookup},
            f,
        )
    with ENCODER_PKL.open("wb") as f:
        pickle.dump(encoder, f)
    logger.info("[Speichern v3] %s | %s", MODELL_PKL, ENCODER_PKL)


def _lade_modell():
    if not MODELL_PKL.exists():
        raise FileNotFoundError(
            f"Kein trainiertes v3-Modell unter {MODELL_PKL}. "
            "Bitte zuerst train() aufrufen."
        )
    with MODELL_PKL.open("rb") as f:
        art = pickle.load(f)
    with ENCODER_PKL.open("rb") as f:
        encoder = pickle.load(f)
    return art["modell"], encoder, art["tfidf"], art["svd"], art["tag_rate_lookup"]


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
        ax.text(
            bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
            f"{pct:.1f}%", va="center", ha="left", fontsize=8,
        )
    ax.set_xlabel("Relative Importance (Gain) in %", fontsize=11)
    ax.set_title(
        f"Feature Importance – Cost Model v3 (Top 20 von {n_features})",
        fontsize=12, fontweight="bold",
    )
    ax.set_xlim(0, max(prozente_sort) * 1.25)
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    fig.savefig(PLOT_PNG, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("[Plot v3] %s", PLOT_PNG)
