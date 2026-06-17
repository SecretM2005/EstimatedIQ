"""
EstimateIQ Bau – Vollständiger Trainings-Workflow

Ablauf:
  1. Preprocesse Daten laden (data/processed/notices_bau.parquet)
  2. BERT-Embeddings extrahieren (bert-base-german-cased, [CLS]-Token)
  3. Kostenmodell trainieren  (XGBoost → log budget_eur)
  4. Laufzeitmodell trainieren (XGBoost → log dauer_tage)
  5. Validierung mit 5 Beispielprojekten
  6. Feature Importance anzeigen

Aufruf:
  python train_bau.py [--kein-bert] [--max-samples N]
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

PARQUET_PFAD = Path("data/processed/notices_bau.parquet")


# ---------------------------------------------------------------------------
# BERT-Embeddings
# ---------------------------------------------------------------------------

def extrahiere_embeddings(texte: list[str], batch_size: int = 32) -> np.ndarray:
    """
    Extrahiert [CLS]-Token-Embeddings via bert-base-german-cased.
    Gibt numpy-Array der Form (n_samples, 768) zurück.
    """
    from transformers import AutoTokenizer, AutoModel
    import torch

    logger.info("[BERT] Lade Modell bert-base-german-cased...")
    tokenizer = AutoTokenizer.from_pretrained("bert-base-german-cased")
    modell    = AutoModel.from_pretrained("bert-base-german-cased")
    modell.eval()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    modell  = modell.to(device)
    logger.info("[BERT] Gerät: %s | %d Texte | Batch-Größe: %d", device, len(texte), batch_size)

    alle_embeddings: list[np.ndarray] = []

    for i in range(0, len(texte), batch_size):
        batch = texte[i : i + batch_size]
        encoded = tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        ).to(device)

        with torch.no_grad():
            ausgabe = modell(**encoded)

        cls_tokens = ausgabe.last_hidden_state[:, 0, :].cpu().numpy()
        alle_embeddings.append(cls_tokens)

        if (i // batch_size) % 10 == 0:
            logger.info("[BERT] %d/%d Texte verarbeitet...", min(i + batch_size, len(texte)), len(texte))

    embeddings = np.vstack(alle_embeddings)
    logger.info("[BERT] Embeddings extrahiert: %s", embeddings.shape)
    return embeddings


# ---------------------------------------------------------------------------
# Validierungsbeispiele
# ---------------------------------------------------------------------------

VALIDIERUNGS_PROJEKTE = [
    {
        "name":        "Badezimmer-Renovation München",
        "beschreibung": "Badezimmer-Renovation 15m² Fliesen Sanitär Wände Boden komplett",
        "gewerk":       "Fliesen/Boden",
        "projekttyp":   "Ausbauarbeiten",
        "land":         "DE",
        "bundesland":   "Bayern",
        "ist_metropole": True,
        "ist_grossstadt": True,
        "bbsr_index":   118.5,
        "latitude":     48.15,
        "longitude":    11.58,
        "jahr":         2024,
        "budget_erwartung": (8_000, 15_000),
        "dauer_erwartung":  (14, 28),
    },
    {
        "name":        "Einfamilienhaus Hamburg",
        "beschreibung": "Neubau Einfamilienhaus 150m² KfW-55 Energiestandard schlüsselfertig inkl. Keller",
        "gewerk":       "Hochbau/Neubau",
        "projekttyp":   "Hoch- und Tiefbau",
        "land":         "DE",
        "bundesland":   "Hamburg",
        "ist_metropole": True,
        "ist_grossstadt": True,
        "bbsr_index":   113.8,
        "latitude":     53.55,
        "longitude":    9.99,
        "jahr":         2024,
        "budget_erwartung": (350_000, 500_000),
        "dauer_erwartung":  (365, 548),
    },
    {
        "name":        "Elektroinstallation Leipzig",
        "beschreibung": "Elektroinstallation Bürogebäude 500m² Vollverkabelung Unterverteilung Beleuchtung",
        "gewerk":       "Elektro",
        "projekttyp":   "Technische Gebäudeausrüstung",
        "land":         "DE",
        "bundesland":   "Sachsen",
        "ist_metropole": False,
        "ist_grossstadt": True,
        "bbsr_index":   92.1,
        "latitude":     51.33,
        "longitude":    12.38,
        "jahr":         2024,
        "budget_erwartung": (20_000, 40_000),
        "dauer_erwartung":  (21, 42),
    },
    {
        "name":        "Dachausbau Wien",
        "beschreibung": "Dachausbau 80m² mit Velux-Dachfenstern Dämmung Trockenbau Elektro Fußbodenheizung",
        "gewerk":       "Ausbau allgemein",
        "projekttyp":   "Ausbauarbeiten",
        "land":         "AT",
        "bundesland":   "AT",
        "ist_metropole": True,
        "ist_grossstadt": True,
        "bbsr_index":   108.0,
        "latitude":     48.21,
        "longitude":    16.36,
        "jahr":         2024,
        "budget_erwartung": (55_000, 95_000),
        "dauer_erwartung":  (56, 98),
    },
    {
        "name":        "Malerarbeiten Berlin",
        "beschreibung": "Malerarbeiten Innen 200m² Altbau Wohnräume Decken Wände Tapete abziehen Grundierung",
        "gewerk":       "Maler",
        "projekttyp":   "Ausbauarbeiten",
        "land":         "DE",
        "bundesland":   "Berlin",
        "ist_metropole": True,
        "ist_grossstadt": True,
        "bbsr_index":   105.8,
        "latitude":     52.52,
        "longitude":    13.40,
        "jahr":         2024,
        "budget_erwartung": (7_000, 13_000),
        "dauer_erwartung":  (7, 14),
    },
]


def validiere_modelle(mit_bert: bool = False) -> None:
    """Testet beide Modelle mit den 5 Validierungsbeispielen."""
    from estimateiq.models.cost_model_bau     import predict as predict_kosten
    from estimateiq.models.duration_model_bau import predict as predict_dauer

    df_val = pd.DataFrame(VALIDIERUNGS_PROJEKTE)
    df_val["beschreibung_laenge"] = df_val["beschreibung"].str.len()

    if mit_bert:
        embeddings = extrahiere_embeddings(df_val["beschreibung"].tolist())
    else:
        embeddings = None

    kosten = predict_kosten(df_val, embeddings=embeddings)
    dauer  = predict_dauer(df_val, embeddings=embeddings)

    print("\n" + "═" * 70)
    print("  Validierung – EstimateIQ Bau")
    print("═" * 70)

    for i, projekt in enumerate(VALIDIERUNGS_PROJEKTE):
        b_low, b_high = projekt["budget_erwartung"]
        d_low, d_high = projekt["dauer_erwartung"]
        b_pred = kosten[i]
        d_pred = dauer[i]

        b_ok = "✓" if b_low <= b_pred <= b_high else "✗"
        d_ok = "✓" if d_low <= d_pred <= d_high else "✗"

        print(f"\n  [{i+1}] {projekt['name']}")
        print(f"       Kosten:  {b_pred:>12,.0f} €  (Erwartung: {b_low:,}–{b_high:,} €)  {b_ok}")
        print(f"       Dauer:   {d_pred:>8,.0f} Tage  (Erwartung: {d_low}–{d_high} Tage)  {d_ok}")

    print("\n" + "═" * 70 + "\n")


# ---------------------------------------------------------------------------
# Haupt-Pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="EstimateIQ Bau – Trainings-Pipeline")
    parser.add_argument(
        "--kein-bert", action="store_true",
        help="BERT-Embeddings überspringen (schneller, weniger akkurat)",
    )
    parser.add_argument(
        "--max-samples", type=int, default=None,
        help="Maximale Anzahl Trainingsbeispiele (None=alle; für Tests z.B. 5000)",
    )
    parser.add_argument(
        "--nur-validierung", action="store_true",
        help="Nur Validierung ausführen (Modelle müssen bereits trainiert sein)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.nur_validierung:
        validiere_modelle(mit_bert=not args.kein_bert)
        return

    # ── 1. Daten laden ───────────────────────────────────────────────────────
    if not PARQUET_PFAD.exists():
        logger.error("Parquet nicht gefunden: %s", PARQUET_PFAD)
        logger.error("Bitte zuerst: python -m estimateiq.data.preprocess_bau")
        sys.exit(1)

    logger.info("Lade %s ...", PARQUET_PFAD)
    df = pd.read_parquet(PARQUET_PFAD)
    logger.info("Geladen: %d Zeilen, %d Spalten", len(df), len(df.columns))

    if args.max_samples and len(df) > args.max_samples:
        df = df.sample(args.max_samples, random_state=42).reset_index(drop=True)
        logger.info("Eingeschränkt auf %d Samples.", args.max_samples)

    # ── 2. BERT-Embeddings (optional) ───────────────────────────────────────
    embeddings: np.ndarray | None = None
    if not args.kein_bert:
        texte = df["beschreibung"].fillna("").tolist()
        embeddings = extrahiere_embeddings(texte)
        # Cache für spätere Nutzung
        embed_pfad = Path("data/processed/embeddings_bau.npy")
        np.save(embed_pfad, embeddings)
        logger.info("[BERT] Embeddings gecacht: %s", embed_pfad)

    # ── 3. Kostenmodell ──────────────────────────────────────────────────────
    from estimateiq.models.cost_model_bau import train as train_kosten
    logger.info("\n" + "─" * 50)
    logger.info("  Training: Kostenmodell (budget_eur)")
    logger.info("─" * 50)
    metriken_kosten = train_kosten(df, embeddings=embeddings)

    # ── 4. Laufzeitmodell ────────────────────────────────────────────────────
    from estimateiq.models.duration_model_bau import train as train_dauer
    logger.info("\n" + "─" * 50)
    logger.info("  Training: Laufzeitmodell (dauer_tage)")
    logger.info("─" * 50)
    metriken_dauer = train_dauer(df, embeddings=embeddings)

    # ── 5. Ergebnis-Zusammenfassung ──────────────────────────────────────────
    print("\n" + "═" * 54)
    print("  EstimateIQ Bau – Trainings-Ergebnis")
    print("═" * 54)
    print(f"\n  Kostenmodell (budget_eur):")
    print(f"    RMSE:       {metriken_kosten['rmse_eur']:>14,.0f} €")
    print(f"    R²:         {metriken_kosten['r2']:>14.4f}")
    print(f"    MdAPE:      {metriken_kosten['mdape']:>13.1f} %")
    print(f"    Trainings-N:{metriken_kosten['n_train']:>14,}")
    print(f"\n  Laufzeitmodell (dauer_tage):")
    print(f"    RMSE:       {metriken_dauer['rmse_tage']:>12.1f} Tage")
    print(f"    R²:         {metriken_dauer['r2']:>14.4f}")
    print(f"    MdAPE:      {metriken_dauer['mdape']:>13.1f} %")
    print(f"    Trainings-N:{metriken_dauer['n_train']:>14,}")
    print(f"\n  BERT-Embeddings: {'Ja' if not args.kein_bert else 'Nein'}")
    print("═" * 54 + "\n")

    # ── 6. Validierung ───────────────────────────────────────────────────────
    validiere_modelle(mit_bert=not args.kein_bert)


if __name__ == "__main__":
    main()
