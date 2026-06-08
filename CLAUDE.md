# EstimateIQ – ML-Projektkostenschätzung für IT-Dienstleister

## Zweck
EstimateIQ ist ein ML-Tool, das IT-Dienstleistern im DACH-Raum dabei hilft,
Ausschreibungskosten und Projektrisiken automatisch einzuschätzen.
Datenbasis sind öffentliche EU-Ausschreibungen aus dem TED-Portal (ted.europa.eu).

## Projektstruktur

```
estimateiq/
├── data/
│   ├── fetch_ted.py       # TED Europa API Connector (CPV 72000000–72900000)
│   └── preprocess.py      # Bereinigung → Parquet DataFrame
├── models/
│   ├── bert_extractor.py  # bert-base-german-cased Embeddings ([CLS]-Token)
│   ├── cost_model.py      # XGBoost Regression (log1p-Transformation)
│   └── risk_model.py      # Random Forest Klassifikation (3 Risikoklassen)
├── api/
│   └── main.py            # FastAPI: POST /api/estimate
├── requirements.txt
└── data/                  # Laufzeit-Artefakte (gitignore'd)
    ├── raw_notices.jsonl
    └── processed_notices.parquet
```

## ML-Pipeline

1. **Daten holen**: `python -m estimateiq.data.fetch_ted`
   → schreibt `data/raw_notices.jsonl`

2. **Vorverarbeitung**: `python -m estimateiq.data.preprocess`
   → schreibt `data/processed_notices.parquet`

3. **Training** (noch zu implementieren: `train.py`):
   - BERT-Embeddings extrahieren
   - cost_model.train(df, embeddings)
   - risk_model.train(df, embeddings)

4. **API starten**: `uvicorn estimateiq.api.main:app --reload`

## Tech Stack
- Python 3.11
- FastAPI + Pydantic v2
- HuggingFace Transformers (bert-base-german-cased)
- XGBoost (Kostenregression, log-transformiert)
- Random Forest (Risikoklassifikation, 0/1/2)
- Supabase (Persistenz, noch zu integrieren)
- TED Europa REST API v3

## Wichtige Konventionen
- Kommentare und Log-Meldungen auf Deutsch
- Alle Währungen werden intern in EUR umgerechnet
- Modelle werden unter `models/*.joblib` gespeichert (nicht im Git)
- TED-Daten werden als JSON Lines gespeichert (streambar, append-fähig)

## Nächste Schritte
- [ ] `train.py` – vollständiger Trainings-Workflow
- [ ] Supabase-Integration für Persistenz von Requests/Responses
- [ ] `evaluate.py` – Backtesting auf historischen Ausschreibungen
- [ ] Docker-Setup für Deployment
- [ ] Frontend (React oder Streamlit)
