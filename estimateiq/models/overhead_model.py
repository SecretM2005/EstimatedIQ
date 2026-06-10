"""
EstimateIQ – Overhead-Modell (Stufe 2 der zweistufigen Kostenschätzung).

Konzept:
  Statt Budget direkt zu schätzen, modellieren wir den Overhead-Faktor:

    overhead_faktor = budget_eur / personalkosten

  Wobei:
    personalkosten = dauer_tage × teamgroesse × stundensatz × STUNDEN_PRO_TAG

  Der Overhead-Faktor > 1 erfasst alles jenseits reiner Personalkosten:
    - Infrastruktur & Hardware
    - Software-Lizenzen
    - Projektmanagement-Overhead (15–30%)
    - Gewinnmarge und Risikopuffer
    - Externe Dienstleister

  Typische Werte für DACH IT-Projekte:
    overhead_faktor ≈ 0.8–5.0  (Median ca. 1.3–2.0)

  Training auf log(overhead_faktor) → log-normale Verteilungsannahme.

Features (9):
  Kategoriale (3): projekttyp, land, datenquelle
  Numerische  (6): cpv_num, beschreibung_laenge, teamgroesse,
                   stundensatz_eur_h, log_personalkosten, hat_deadline

Artefakte (unter models/):
  overhead_model.pkl   – {modell, residual_quantile_p25, residual_quantile_p75, overhead_stats}
  overhead_encoders.pkl – OrdinalEncoder
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
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OrdinalEncoder
from xgboost import XGBRegressor

logger = logging.getLogger(__name__)

MODELL_DIR   = Path("models")
MODELL_PKL   = MODELL_DIR / "overhead_model.pkl"
ENCODER_PKL  = MODELL_DIR / "overhead_encoders.pkl"
PLOT_PNG     = MODELL_DIR / "overhead_distribution.png"

STUNDEN_PRO_TAG      = 8.0     # Produktive Stunden/Arbeitstag
OVERHEAD_MIN         = 0.05    # Budget < 5% der Personalkosten → Datenfehler
OVERHEAD_MAX         = 100.0   # Budget > 100× Personalkosten → Framework-Vertrag o.ä.

KATEGORIALE          = ["projekttyp", "land", "datenquelle"]
NUMERISCHE           = ["cpv_num", "beschreibung_laenge", "teamgroesse",
                        "stundensatz_eur_h", "log_personalkosten", "hat_deadline"]

# Standardwerte Teamgröße je Projekttyp (kalibriert auf DACH-Marktdaten)
PROJEKTTYP_TEAMGROESSE: dict[str, float] = {
    "Softwareentwicklung":           3.0,
    "Datenverarbeitung & Analytics": 2.5,
    "Internet- & Cloud-Dienste":     2.5,
    "IT-Betrieb & Wartung":         2.0,
    "IT-Beratung & Support":         1.5,
    "Netzwerk & Infrastruktur":      2.5,
    "IT-Prüfung & Testing":          1.5,
    "Datenmigration & Backup":       2.0,
    "IT-Hardware & Systeme":         1.5,
    "Sonstige IT":                   2.0,
}


# ---------------------------------------------------------------------------
# Teamgröße-Extraktion
# ---------------------------------------------------------------------------

# Regex-Muster zur Extraktion expliziter Teamgrößen (Deutsch + Englisch)
_TEAMGROESSE_MUSTER = [
    r"(\d+)\s*(?:vollzeit[-\s]?)?entwickler(?:innen)?",
    r"(\d+)\s*software[-\s]?(?:entwickler|ingenieure?)(?:innen)?",
    r"(\d+)[-\s]?köpfig(?:es?|em|en)?\s+\w*team",   # 8-köpfiges Entwicklerteam
    r"(\d+)[-\s]?köpfig(?:es?|em|en)?\s+team",
    r"team\s+(?:aus\s+|von\s+)?(\d+)",
    r"(\d+)\s*(?:fte|vollzeitstellen?|vollzeitäquivalente?)",
    r"(\d+)\s*(?:personen|mitarbeiter(?:innen)?|berater(?:innen)?)",
    r"(\d+)\s*(?:developers?|engineers?|consultants?)",
    r"(\d+)[-\s]?person\s+team",
    r"team\s+of\s+(\d+)",
]
_MUSTER_KOMPILIERT = [re.compile(p, re.IGNORECASE) for p in _TEAMGROESSE_MUSTER]


def extract_teamgroesse(beschreibung: str, projekttyp: str = "Softwareentwicklung") -> float:
    """
    Schätzt Teamgröße aus Beschreibungstext (Regex) oder Projekttyp-Heuristik.

    Rückgabe: Durchschnittliche Anzahl Vollzeit-Äquivalente (FTE), mindestens 1.0.
    """
    for muster in _MUSTER_KOMPILIERT:
        treffer = muster.search(beschreibung or "")
        if treffer:
            n = int(treffer.group(1))
            if 1 <= n <= 100:
                return float(n)
    return PROJEKTTYP_TEAMGROESSE.get(projekttyp, 2.0)


# ---------------------------------------------------------------------------
# Personalkosten-Berechnung
# ---------------------------------------------------------------------------

def berechne_personalkosten(
    dauer_tage: float,
    teamgroesse: float,
    stundensatz_eur_h: float,
) -> float:
    """personalkosten = dauer_tage × teamgroesse × stundensatz × STUNDEN_PRO_TAG"""
    return dauer_tage * teamgroesse * stundensatz_eur_h * STUNDEN_PRO_TAG


# ---------------------------------------------------------------------------
# Feature Engineering
# ---------------------------------------------------------------------------

def _feature_engineering(df: pd.DataFrame, stundensatz_lookup: dict | None = None) -> pd.DataFrame:
    """
    Reichert DataFrame mit Overhead-spezifischen Features an.
    stundensatz_lookup: {land: stundensatz_eur_h}; None → lädt aus fetch_salary_data
    """
    df = df.copy()

    if "datenquelle" not in df.columns:
        df["datenquelle"] = "ted"

    df["beschreibung_laenge"] = df["beschreibung"].str.len().fillna(0).astype("float32")
    df["hat_deadline"]        = df["dauer_tage"].notna().astype("float32")
    df["cpv_num"] = pd.to_numeric(df["cpv_code"], errors="coerce").fillna(72_000_000).astype("float32")

    # Teamgröße
    projekttyp_col = df["projekttyp"].astype(str) if "projekttyp" in df.columns else pd.Series(["Softwareentwicklung"] * len(df))
    df["teamgroesse"] = [
        extract_teamgroesse(str(b), str(p))
        for b, p in zip(df["beschreibung"].fillna(""), projekttyp_col)
    ]
    df["teamgroesse"] = df["teamgroesse"].astype("float32")

    # Stundensatz je Land
    if stundensatz_lookup:
        df["stundensatz_eur_h"] = df["land"].astype(str).map(stundensatz_lookup).fillna(47.5).astype("float32")
    else:
        # Lazy-Import vermeidet zirkuläre Abhängigkeiten
        try:
            from estimateiq.data.fetch_salary_data import get_stundensatz as _get_stundensatz
            df["stundensatz_eur_h"] = df["land"].astype(str).apply(
                lambda l: _get_stundensatz(l, "all")["stundensatz_median"]
            ).astype("float32")
        except Exception:
            df["stundensatz_eur_h"] = 47.5

    # Log-Personalkosten als Feature (hilft Modell, Korrekturrichtung zu lernen)
    dauer = pd.to_numeric(df["dauer_tage"], errors="coerce").fillna(180.0).clip(lower=1.0)
    pk    = berechne_personalkosten(dauer, df["teamgroesse"], df["stundensatz_eur_h"])
    df["log_personalkosten"] = np.log1p(pk).astype("float32")

    return df


def _erstelle_feature_matrix(
    df: pd.DataFrame,
    encoder: OrdinalEncoder | None = None,
) -> tuple[np.ndarray, OrdinalEncoder]:
    fit = encoder is None
    if fit:
        encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1, dtype=np.float32)
        kat = encoder.fit_transform(df[KATEGORIALE].astype(str).fillna("unbekannt"))
    else:
        kat = encoder.transform(df[KATEGORIALE].astype(str).fillna("unbekannt"))

    num = df[NUMERISCHE].apply(pd.to_numeric, errors="coerce").fillna(0.0).values.astype(np.float32)
    return np.hstack([kat, num]), encoder


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(df: pd.DataFrame, test_anteil: float = 0.20) -> dict:
    """
    Trainiert das Overhead-Modell auf Projekten mit Budget UND Laufzeit.

    Overhead-Faktor = budget_eur / personalkosten
    Ziel-Variable   = log(overhead_faktor)
    """
    logger.info("[Overhead] Starte Training (Projekten mit Budget + Laufzeit)...")

    df = _feature_engineering(df)
    maske = (
        df["budget_eur"].notna()
        & df["dauer_tage"].notna()
        & (pd.to_numeric(df["dauer_tage"], errors="coerce") >= 7)
    )
    df_sauber = df[maske].reset_index(drop=True)
    logger.info("[Overhead] %d / %d Projekte mit Budget + Laufzeit.", len(df_sauber), len(df))

    if len(df_sauber) < 30:
        raise ValueError(f"Zu wenig Trainingsdaten: {len(df_sauber)} (Minimum: 30).")

    # Overhead-Faktor berechnen
    dauer = pd.to_numeric(df_sauber["dauer_tage"], errors="coerce").astype(float)
    pk    = berechne_personalkosten(dauer, df_sauber["teamgroesse"], df_sauber["stundensatz_eur_h"])
    pk    = pk.clip(lower=1.0)
    of    = df_sauber["budget_eur"].astype(float) / pk

    # Ausreißer-Filter
    maske_valid = (of >= OVERHEAD_MIN) & (of <= OVERHEAD_MAX) & of.notna()
    gefiltert   = (~maske_valid).sum()
    if gefiltert:
        logger.info("[Overhead] %d Datensätze mit Overhead-Faktor außerhalb [%.2f, %.0f] gefiltert.",
                    gefiltert, OVERHEAD_MIN, OVERHEAD_MAX)

    df_sauber = df_sauber[maske_valid].reset_index(drop=True)
    of        = of[maske_valid].reset_index(drop=True)

    _plot_overhead_verteilung(of)
    logger.info(
        "[Overhead] Verteilung Overhead-Faktor:\n"
        "  Median:  %6.2f  |  p25: %5.2f  |  p75: %5.2f\n"
        "  Minimum: %6.2f  |  Maximum: %5.1f  |  n=%d",
        of.median(), of.quantile(0.25), of.quantile(0.75),
        of.min(), of.max(), len(of),
    )

    y_log = np.log(of.values.astype(np.float64))

    quartile = pd.qcut(pd.Series(y_log), q=4, labels=False, duplicates="drop").fillna(0).values
    idx = np.arange(len(df_sauber))
    idx_train, idx_test = train_test_split(idx, test_size=test_anteil, random_state=42, stratify=quartile)

    df_train, df_test = df_sauber.iloc[idx_train].reset_index(drop=True), df_sauber.iloc[idx_test].reset_index(drop=True)
    y_train, y_test   = y_log[idx_train], y_log[idx_test]

    X_train, encoder = _erstelle_feature_matrix(df_train)
    X_test, _        = _erstelle_feature_matrix(df_test, encoder=encoder)
    logger.info("[Overhead] Split: %d Train / %d Test, %d Features.", len(X_train), len(X_test), X_train.shape[1])

    modell = XGBRegressor(
        n_estimators=500,
        learning_rate=0.02,
        max_depth=4,
        min_child_weight=4,
        subsample=0.8,
        colsample_bytree=0.7,
        reg_alpha=0.1,
        reg_lambda=1.5,
        random_state=42,
        n_jobs=-1,
        eval_metric="rmse",
        early_stopping_rounds=40,
    )
    modell.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    y_pred_log = modell.predict(X_test).astype(np.float64)
    residuals  = y_test - y_pred_log   # Residuen im Log-Raum (test set)

    rmse_log = float(np.sqrt(mean_squared_error(y_test, y_pred_log)))
    r2       = float(r2_score(y_test, y_pred_log))
    mae_log  = float(np.mean(np.abs(residuals)))

    # Residual-Quantile → dienen später als Konfidenzintervall
    rq_p10 = float(np.percentile(residuals, 10))
    rq_p25 = float(np.percentile(residuals, 25))
    rq_p75 = float(np.percentile(residuals, 75))
    rq_p90 = float(np.percentile(residuals, 90))

    logger.info(
        "[Overhead] Ergebnis:\n"
        "  RMSE (log):    %8.4f\n"
        "  MAE  (log):    %8.4f\n"
        "  R²   (log):    %8.4f\n"
        "  Residual-Quantile (log-Raum): p10=%+.3f  p25=%+.3f  p75=%+.3f  p90=%+.3f\n"
        "  Entspricht Multiplikatoren:   p10=%.2f×  p25=%.2f×  p75=%.2f×  p90=%.2f×\n"
        "  Best iteration:%8d",
        rmse_log, mae_log, r2,
        rq_p10, rq_p25, rq_p75, rq_p90,
        np.exp(rq_p10), np.exp(rq_p25), np.exp(rq_p75), np.exp(rq_p90),
        modell.best_iteration,
    )

    MODELL_DIR.mkdir(parents=True, exist_ok=True)
    artefakt = {
        "modell":     modell,
        "rq_p10":     rq_p10,
        "rq_p25":     rq_p25,
        "rq_p75":     rq_p75,
        "rq_p90":     rq_p90,
        "overhead_stats": {
            "median": float(of.median()),
            "p25":    float(of.quantile(0.25)),
            "p75":    float(of.quantile(0.75)),
        },
    }
    with MODELL_PKL.open("wb") as f:
        pickle.dump(artefakt, f)
    with ENCODER_PKL.open("wb") as f:
        pickle.dump(encoder, f)
    logger.info("[Overhead] Gespeichert: %s | %s", MODELL_PKL, ENCODER_PKL)

    return {
        "rmse_log":       rmse_log,
        "mae_log":        mae_log,
        "r2_log":         r2,
        "rq_p25":         rq_p25,
        "rq_p75":         rq_p75,
        "overhead_median": float(of.median()),
        "overhead_p25":   float(of.quantile(0.25)),
        "overhead_p75":   float(of.quantile(0.75)),
        "n_train":        len(X_train),
        "n_test":         len(X_test),
        "best_iteration": modell.best_iteration,
    }


# ---------------------------------------------------------------------------
# Vorhersage
# ---------------------------------------------------------------------------

def predict(df: pd.DataFrame) -> list[dict]:
    """
    Gibt Overhead-Faktor als Verteilung zurück.

    Rückgabe: Liste von dicts mit:
      {"p25": float, "p50": float, "p75": float, "p10": float, "p90": float}
    """
    modell, artefakt, encoder = _lade_modell()

    df = _feature_engineering(df)
    X, _ = _erstelle_feature_matrix(df, encoder=encoder)
    pred_log = modell.predict(X).astype(np.float64)

    ergebnisse = []
    for pl in pred_log:
        ergebnisse.append({
            "p10": float(np.exp(pl + artefakt["rq_p10"])),
            "p25": float(np.exp(pl + artefakt["rq_p25"])),
            "p50": float(np.exp(pl)),
            "p75": float(np.exp(pl + artefakt["rq_p75"])),
            "p90": float(np.exp(pl + artefakt["rq_p90"])),
        })
    return ergebnisse


# ---------------------------------------------------------------------------
# Diagnose-Plot
# ---------------------------------------------------------------------------

def _plot_overhead_verteilung(of: pd.Series) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    log_of = np.log(of[of > 0])
    axes[0].hist(log_of, bins=40, color="#f97316", alpha=0.75, edgecolor="white", linewidth=0.4)
    axes[0].set_xlabel("log(Overhead-Faktor)")
    axes[0].set_ylabel("Anzahl Projekte")
    axes[0].set_title("Overhead-Verteilung (log-Skala)", fontweight="bold")
    for pct_val, label, farbe in [(0.25, "p25", "#2563eb"), (0.50, "Median", "#ef4444"), (0.75, "p75", "#8b5cf6")]:
        v = np.log(of.quantile(pct_val))
        axes[0].axvline(v, color=farbe, linestyle="--", linewidth=1.5, label=f"{label}: {of.quantile(pct_val):.2f}×")
    axes[0].legend(fontsize=9)

    axes[1].hist(of.clip(upper=10), bins=40, color="#10b981", alpha=0.75, edgecolor="white", linewidth=0.4)
    axes[1].set_xlabel("Overhead-Faktor (bis 10×)")
    axes[1].set_title("Overhead-Verteilung (linear, bis 10×)", fontweight="bold")
    axes[1].axvline(1.0, color="#ef4444", linestyle="-", linewidth=2.0, label="Overhead-Faktor = 1")
    axes[1].legend(fontsize=9)

    plt.suptitle("Overhead-Faktor = Budget / Personalkosten", fontsize=12, fontweight="bold")
    plt.tight_layout()
    MODELL_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(PLOT_PNG, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("[Overhead] Verteilungs-Plot: %s", PLOT_PNG)


# ---------------------------------------------------------------------------
# Artefakt-Hilfsfunktionen
# ---------------------------------------------------------------------------

def _lade_modell():
    if not MODELL_PKL.exists():
        raise FileNotFoundError(
            f"Kein trainiertes Overhead-Modell unter {MODELL_PKL}. "
            "Bitte zuerst: python train.py --only overhead"
        )
    with MODELL_PKL.open("rb") as f:
        art = pickle.load(f)
    with ENCODER_PKL.open("rb") as f:
        enc = pickle.load(f)
    return art["modell"], art, enc
