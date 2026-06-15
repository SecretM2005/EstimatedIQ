"""
EstimateIQ – Tagespreis-Modell (Stufe 2 der zweistufigen Kostenschätzung).

Konzept:
  Statt Budget direkt zu schätzen, modellieren wir den Tagespreis:

    tagespreis = budget_eur / dauer_tage   [EUR/Tag]

  Vorteile gegenüber Overhead-Faktor-Ansatz:
    - Keine Teamgrößen-Schätzung nötig → eliminiert größte Fehlerquelle
    - Tagespreis ist project-type-abhängig und aus Features vorhersagbar
    - Konsistent mit realer IT-Projektkalkulation (Tagessätze)

  Pipeline:
    budget_expected = dauer_predicted × tagespreis_p50
    budget_range    = dauer_predicted × [tagespreis_p10, tagespreis_p90]

  Typische DACH IT-Tagespreise:
    p25 ≈   700 €/Tag  (1 Berater / kleines Projekt)
    p50 ≈ 1.500 €/Tag  (Kleines Team / mittleres Projekt)
    p75 ≈ 6.000 €/Tag  (Größeres Team / Infrastrukturprojekt)

Features (57):
  Kategoriale  (3): projekttyp, land, datenquelle
  Numerische   (4): cpv_num, beschreibung_laenge, beschreibung_wortanzahl, log_dauer
  SVD-Text    (50): TruncatedSVD aus TF-IDF auf 'beschreibung'

Artefakte (unter models/):
  overhead_model.pkl    – {modell, tfidf, svd, residual-quantile, tagespreis_stats}
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
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OrdinalEncoder
from xgboost import XGBRegressor

logger = logging.getLogger(__name__)

MODELL_DIR   = Path("models")
MODELL_PKL   = MODELL_DIR / "overhead_model.pkl"
ENCODER_PKL  = MODELL_DIR / "overhead_encoders.pkl"
PLOT_PNG     = MODELL_DIR / "tagespreis_distribution.png"

STUNDEN_PRO_TAG   = 8.0     # Arbeitsstunden/Tag (für personalkosten-Reporting)
TAGESPREIS_MIN    = 100     # 100 €/Tag: absolutes Minimum
TAGESPREIS_MAX    = 200_000 # 200k €/Tag: Großrahmenprojekte
N_SVD             = 50

KATEGORIALE  = ["projekttyp", "land", "datenquelle"]
NUMERISCHE   = ["cpv_num", "beschreibung_laenge", "beschreibung_wortanzahl", "log_dauer"]

# Teamgröße-Defaults (für Reporting/Personalkosten-Ausweis, NICHT für Kostenschätzung)
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

_TEAMGROESSE_MUSTER = [
    r"(\d+)\s*(?:vollzeit[-\s]?)?entwickler(?:innen)?",
    r"(\d+)\s*software[-\s]?(?:entwickler|ingenieure?)(?:innen)?",
    r"(\d+)[-\s]?köpfig(?:es?|em|en)?\s+\w*team",
    r"(\d+)[-\s]?köpfig(?:es?|em|en)?\s+team",
    r"team\s+(?:aus\s+|von\s+)?(\d+)",
    r"(\d+)\s*(?:fte|vollzeitstellen?|vollzeitäquivalente?)",
    r"(\d+)\s*(?:personen|mitarbeiter(?:innen)?|berater(?:innen)?)",
    r"(\d+)\s*(?:developers?|engineers?|consultants?)",
    r"(\d+)[-\s]?person\s+team",
    r"team\s+of\s+(\d+)",
]
_MUSTER_KOMPILIERT = [re.compile(p, re.IGNORECASE) for p in _TEAMGROESSE_MUSTER]

# Solo/Freelancer-Erkennung → gibt immer 1 Person zurück
_SOLO_MUSTER = re.compile(
    r"\b("
    r"solo|allein\w*|freelancer?\w*|freiberuflich\w*|selbständig\w*|"
    r"einzelperson|1[\s-]person|one[\s-]person|"
    r"sole\s+developer|indie\s+developer|solo\s+developer|"
    r"nur\s+ich|als\s+einzelner\w*|als\s+entwicklerin?"
    r")\b",
    re.IGNORECASE,
)


def extract_teamgroesse(beschreibung: str, projekttyp: str = "Softwareentwicklung") -> float:
    """Schätzt Teamgröße via Regex oder Projekttyp-Heuristik. Nur für Reporting."""
    text = beschreibung or ""

    # Solo/Freelancer-Angaben haben Vorrang
    if _SOLO_MUSTER.search(text):
        return 1.0

    # Explizite Teamgröße aus Text extrahieren
    for muster in _MUSTER_KOMPILIERT:
        treffer = muster.search(text)
        if treffer:
            n = int(treffer.group(1))
            if 1 <= n <= 100:
                return float(n)

    return PROJEKTTYP_TEAMGROESSE.get(projekttyp, 2.0)


def berechne_personalkosten(dauer_tage: float, teamgroesse: float, stundensatz_eur_h: float) -> float:
    """Reine Personalkosten (ohne Overhead). Nur für Reporting-Zwecke."""
    return dauer_tage * teamgroesse * stundensatz_eur_h * STUNDEN_PRO_TAG


# ---------------------------------------------------------------------------
# Feature Engineering
# ---------------------------------------------------------------------------

def _feature_engineering(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "datenquelle" not in df.columns:
        df["datenquelle"] = "ted"
    df["beschreibung_laenge"]     = df["beschreibung"].str.len().fillna(0).astype("float32")
    df["beschreibung_wortanzahl"] = df["beschreibung"].str.split().str.len().fillna(0).astype("float32")
    df["cpv_num"] = pd.to_numeric(df["cpv_code"], errors="coerce").fillna(72_000_000).astype("float32")
    # log(dauer_tage) als Feature: längere Projekte haben oft andere Tagespreisstruktur
    dauer = pd.to_numeric(df.get("dauer_tage", pd.Series([180] * len(df))), errors="coerce").fillna(180.0).clip(lower=1.0)
    df["log_dauer"] = np.log1p(dauer).astype("float32")
    return df


def _erstelle_feature_matrix(
    df: pd.DataFrame,
    encoder: OrdinalEncoder | None = None,
    tfidf: TfidfVectorizer | None = None,
    svd: TruncatedSVD | None = None,
) -> tuple[np.ndarray, OrdinalEncoder, TfidfVectorizer, TruncatedSVD]:
    fit = encoder is None

    if fit:
        encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1, dtype=np.float32)
        kat = encoder.fit_transform(df[KATEGORIALE].astype(str).fillna("unbekannt"))
    else:
        kat = encoder.transform(df[KATEGORIALE].astype(str).fillna("unbekannt"))

    num = df[NUMERISCHE].apply(pd.to_numeric, errors="coerce").fillna(0.0).values.astype(np.float32)

    texte = df["beschreibung"].fillna("").tolist()
    if fit:
        tfidf = TfidfVectorizer(max_features=15_000, min_df=2, sublinear_tf=True, ngram_range=(1, 2))
        mat   = tfidf.fit_transform(texte)
        n_k   = min(N_SVD, mat.shape[1] - 1, mat.shape[0] - 1)
        svd   = TruncatedSVD(n_components=n_k, random_state=42)
        txt   = svd.fit_transform(mat).astype(np.float32)
        logger.info("[Tagespreis] TF-IDF Vokabular: %d | SVD: %d Komp. (%.1f%% Textvarianz)",
                    len(tfidf.vocabulary_), n_k, svd.explained_variance_ratio_.sum() * 100)
    else:
        txt = svd.transform(tfidf.transform(texte)).astype(np.float32)

    return np.hstack([kat, num, txt]), encoder, tfidf, svd


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(df: pd.DataFrame, test_anteil: float = 0.20) -> dict:
    """
    Trainiert das Tagespreis-Modell auf ALLEN Budget-Projekten.

    Zielgröße: log(budget_eur / dauer_tage) = log(tagespreis in EUR/Tag)

    Für Projekte OHNE tatsächliche dauer_tage wird das trainierte Duration-Modell
    verwendet, um Laufzeiten vorherzusagen. Dadurch steigt das Training von ~710
    (nur Budget+Laufzeit) auf ~2.241 (alle Budget-Projekte) – 3× mehr Daten und
    vor allem die korrekte Verteilung inkl. großer Rahmenverträge.
    """
    logger.info("[Tagespreis] Starte Training (Ziel: log(budget/dauer_tage))...")

    df = _feature_engineering(df)

    # Alle Budget-Projekte als Basis (nicht nur jene mit tatsächlicher Laufzeit).
    # PROMISE + COSMIC ausschließen: synthetische Budgets (effort × Stundensatz) verzerren
    # die Tagespreis-Verteilung und stimmen nicht mit echten Marktpreisen überein.
    SYNTHETISCHE_QUELLEN = {"promise", "cosmic"}
    maske_budget = df["budget_eur"].notna()
    if "datenquelle" in df.columns:
        maske_budget &= ~df["datenquelle"].isin(SYNTHETISCHE_QUELLEN)
    df_sauber = df[maske_budget].reset_index(drop=True)
    logger.info("[Tagespreis] %d Budget-Projekte gesamt (aus %d, synthetische Quellen ausgeschlossen).",
                len(df_sauber), len(df))

    if len(df_sauber) < 30:
        raise ValueError(f"Zu wenig Trainingsdaten: {len(df_sauber)} (Minimum: 30).")

    # Laufzeit: tatsächlich wo vorhanden, sonst Duration-Modell-Vorhersage
    hat_echte_dauer = (
        df_sauber["dauer_tage"].notna()
        & (pd.to_numeric(df_sauber["dauer_tage"], errors="coerce") >= 7)
    )
    n_actual = int(hat_echte_dauer.sum())
    n_pred   = int((~hat_echte_dauer).sum())

    dauer_arr = pd.to_numeric(df_sauber["dauer_tage"], errors="coerce").values.astype(np.float64)

    if n_pred > 0:
        try:
            from estimateiq.models.duration_model import predict as _dur_predict
            df_ohne = df_sauber[~hat_echte_dauer].reset_index(drop=True)
            dauer_pred = _dur_predict(df_ohne).astype(np.float64)
            dauer_arr[~hat_echte_dauer.values] = dauer_pred
            # log_dauer-Feature mit vollständiger Laufzeit aktualisieren
            df_sauber = df_sauber.copy()
            df_sauber["dauer_tage"] = dauer_arr
            df_sauber["log_dauer"]  = np.log1p(np.clip(dauer_arr, 1.0, None)).astype("float32")
            logger.info(
                "[Tagespreis] Laufzeiten: %d tatsächlich + %d vorhergesagt = %d Trainingsprojekte.",
                n_actual, n_pred, len(df_sauber),
            )
        except FileNotFoundError:
            logger.warning(
                "[Tagespreis] Duration-Modell fehlt – Fallback auf %d Projekte mit tatsächl. Laufzeit. "
                "Zuerst: python train.py --only duration",
                n_actual,
            )
            df_sauber = df_sauber[hat_echte_dauer].reset_index(drop=True)
            dauer_arr = pd.to_numeric(df_sauber["dauer_tage"], errors="coerce").values.astype(np.float64)

    dauer = np.clip(dauer_arr, 1.0, None)
    tagespreis = pd.Series(
        np.clip(
            df_sauber["budget_eur"].astype(float).values / dauer,
            TAGESPREIS_MIN, TAGESPREIS_MAX,
        )
    )

    # Filtere Ausreißer (Clipping bedeutet: leicht verschobene Werte bleiben)
    maske_valid = tagespreis.between(TAGESPREIS_MIN, TAGESPREIS_MAX)
    gefiltert   = (~maske_valid).sum()
    if gefiltert:
        logger.info("[Tagespreis] %d Datensätze nach Tagespreis-Clipping angepasst.", gefiltert)

    _plot_tagespreis_verteilung(tagespreis)
    logger.info(
        "[Tagespreis] Verteilung (EUR/Tag): Median=%d | p25=%d | p75=%d | Min=%d | Max=%d | n=%d",
        int(tagespreis.median()), int(tagespreis.quantile(0.25)), int(tagespreis.quantile(0.75)),
        int(tagespreis.min()), int(tagespreis.max()), len(tagespreis),
    )

    y_log = np.log(tagespreis.values.astype(np.float64))

    quartile = pd.qcut(pd.Series(y_log), q=4, labels=False, duplicates="drop").fillna(0).values
    idx = np.arange(len(df_sauber))
    idx_train, idx_test = train_test_split(idx, test_size=test_anteil, random_state=42, stratify=quartile)

    df_train, df_test = df_sauber.iloc[idx_train].reset_index(drop=True), df_sauber.iloc[idx_test].reset_index(drop=True)
    y_train, y_test   = y_log[idx_train], y_log[idx_test]

    X_train, encoder, tfidf, svd = _erstelle_feature_matrix(df_train)
    X_test,  _,       _,    _   = _erstelle_feature_matrix(df_test, encoder=encoder, tfidf=tfidf, svd=svd)
    logger.info("[Tagespreis] Split: %d Train / %d Test, %d Features.",
                len(X_train), len(X_test), X_train.shape[1])

    modell = XGBRegressor(
        n_estimators=600,
        learning_rate=0.02,
        max_depth=4,
        min_child_weight=4,
        subsample=0.8,
        colsample_bytree=0.6,
        reg_alpha=0.1,
        reg_lambda=1.5,
        random_state=42,
        n_jobs=-1,
        eval_metric="rmse",
        early_stopping_rounds=40,
    )
    modell.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    y_pred_log = modell.predict(X_test).astype(np.float64)
    residuals  = y_test - y_pred_log   # Test-Set Residuen im log-Raum

    rmse_log   = float(np.sqrt(mean_squared_error(y_test, y_pred_log)))
    r2_log     = float(r2_score(y_test, y_pred_log))
    mae_log    = float(np.mean(np.abs(residuals)))
    # Rückrechnung in €/Tag für intuitive Fehlermetrik
    y_pred_eur = np.exp(y_pred_log)
    y_true_eur = np.exp(y_test)
    mdape      = float(np.median(np.abs(y_true_eur - y_pred_eur) / (y_true_eur + 1)) * 100)

    # Residual-Quantile → Konfidenzintervalle bei predict()
    rq = {
        "p10": float(np.percentile(residuals, 10)),
        "p25": float(np.percentile(residuals, 25)),
        "p75": float(np.percentile(residuals, 75)),
        "p90": float(np.percentile(residuals, 90)),
    }

    logger.info(
        "[Tagespreis] Ergebnis:\n"
        "  RMSE (log):    %8.4f\n"
        "  MAE  (log):    %8.4f\n"
        "  R²   (log):    %8.4f\n"
        "  MdAPE (€/Tag): %7.1f%%\n"
        "  Residual-CI (log): p10=%+.3f  p25=%+.3f  p75=%+.3f  p90=%+.3f\n"
        "  = Tagespreis-Multiplikatoren: p10=%.2f×  p25=%.2f×  p75=%.2f×  p90=%.2f×\n"
        "  Best iteration:%8d",
        rmse_log, mae_log, r2_log, mdape,
        rq["p10"], rq["p25"], rq["p75"], rq["p90"],
        np.exp(rq["p10"]), np.exp(rq["p25"]), np.exp(rq["p75"]), np.exp(rq["p90"]),
        modell.best_iteration,
    )

    MODELL_DIR.mkdir(parents=True, exist_ok=True)
    artefakt = {
        "modell":    modell,
        "tfidf":     tfidf,
        "svd":       svd,
        "rq_p10":    rq["p10"],
        "rq_p25":    rq["p25"],
        "rq_p75":    rq["p75"],
        "rq_p90":    rq["p90"],
        "tagespreis_stats": {
            "median": float(tagespreis.median()),
            "p25":    float(tagespreis.quantile(0.25)),
            "p75":    float(tagespreis.quantile(0.75)),
        },
    }
    with MODELL_PKL.open("wb") as f:
        pickle.dump(artefakt, f)
    with ENCODER_PKL.open("wb") as f:
        pickle.dump(encoder, f)
    logger.info("[Tagespreis] Gespeichert: %s | %s", MODELL_PKL, ENCODER_PKL)

    return {
        "rmse_log":       rmse_log,
        "mae_log":        mae_log,
        "r2_log":         r2_log,
        "mdape":          mdape,
        "rq_p25":         rq["p25"],
        "rq_p75":         rq["p75"],
        "overhead_median": float(tagespreis.median()),
        "overhead_p25":   float(tagespreis.quantile(0.25)),
        "overhead_p75":   float(tagespreis.quantile(0.75)),
        "n_train":        len(X_train),
        "n_test":         len(X_test),
        "best_iteration": modell.best_iteration,
    }


# ---------------------------------------------------------------------------
# Vorhersage
# ---------------------------------------------------------------------------

def predict(df: pd.DataFrame) -> list[dict]:
    """
    Gibt Tagespreis-Verteilung zurück (EUR/Tag).

    Rückgabe: Liste von dicts mit p10, p25, p50, p75, p90 in EUR/Tag.

    Beispiel:
      [{"p10": 320, "p25": 690, "p50": 1480, "p75": 5200, "p90": 14800}]
    """
    modell, artefakt, encoder = _lade_modell()

    df = _feature_engineering(df)
    X, _, _, _ = _erstelle_feature_matrix(df, encoder=encoder,
                                           tfidf=artefakt["tfidf"], svd=artefakt["svd"])
    pred_log = modell.predict(X).astype(np.float64)

    return [
        {
            "p10": float(np.exp(pl + artefakt["rq_p10"])),
            "p25": float(np.exp(pl + artefakt["rq_p25"])),
            "p50": float(np.exp(pl)),
            "p75": float(np.exp(pl + artefakt["rq_p75"])),
            "p90": float(np.exp(pl + artefakt["rq_p90"])),
        }
        for pl in pred_log
    ]


# ---------------------------------------------------------------------------
# Diagnose-Plot
# ---------------------------------------------------------------------------

def _plot_tagespreis_verteilung(tp: pd.Series) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    log_tp = np.log(tp[tp > 0])
    axes[0].hist(log_tp, bins=40, color="#f97316", alpha=0.75, edgecolor="white", linewidth=0.4)
    axes[0].set_xlabel("log(Tagespreis, EUR/Tag)")
    axes[0].set_ylabel("Anzahl Projekte")
    axes[0].set_title("Tagespreis-Verteilung (log-Skala)", fontweight="bold")
    for pv, lbl, farbe in [(0.25, "p25", "#2563eb"), (0.50, "Median", "#ef4444"), (0.75, "p75", "#8b5cf6")]:
        v = np.log(tp.quantile(pv))
        axes[0].axvline(v, color=farbe, linestyle="--", linewidth=1.5,
                        label=f"{lbl}: {tp.quantile(pv):,.0f} €/Tag")
    axes[0].legend(fontsize=9)

    tp_clip = tp.clip(upper=tp.quantile(0.95))
    axes[1].hist(tp_clip / 1000, bins=40, color="#10b981", alpha=0.75, edgecolor="white", linewidth=0.4)
    axes[1].set_xlabel("Tagespreis (T€/Tag, bis p95)")
    axes[1].set_title("Tagespreis-Verteilung (linear, bis p95)", fontweight="bold")

    plt.suptitle("Tagespreis = Budget / Laufzeit (EUR/Tag)", fontsize=12, fontweight="bold")
    plt.tight_layout()
    MODELL_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(PLOT_PNG, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("[Tagespreis] Verteilungs-Plot: %s", PLOT_PNG)


# ---------------------------------------------------------------------------
# Artefakt-Hilfsfunktionen
# ---------------------------------------------------------------------------

def _lade_modell():
    if not MODELL_PKL.exists():
        raise FileNotFoundError(
            f"Kein trainiertes Tagespreis-Modell unter {MODELL_PKL}. "
            "Bitte zuerst: python train.py --only overhead"
        )
    with MODELL_PKL.open("rb") as f:
        art = pickle.load(f)
    with ENCODER_PKL.open("rb") as f:
        enc = pickle.load(f)
    return art["modell"], art, enc
