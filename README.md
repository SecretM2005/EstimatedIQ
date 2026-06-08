# EstimateIQ

ML-Tool zur Projektkostenschätzung für IT-Dienstleister im DACH-Raum,
basierend auf öffentlichen EU-Ausschreibungen (TED Europa).

## Voraussetzungen

- Python 3.11+
- 4 GB RAM (BERT-Modell)
- Optional: CUDA-GPU für schnellere Embedding-Extraktion

## Installation

```bash
# Repository klonen
git clone https://github.com/dein-user/estimateiq.git
cd estimateiq

# Virtuelle Umgebung anlegen
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Abhängigkeiten installieren
pip install -r requirements.txt
```

## Konfiguration

Lege eine `.env`-Datei im Projektroot an:

```env
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=your-anon-key
```

## Daten laden & vorverarbeiten

```bash
# Schritt 1: TED-Ausschreibungen laden (DACH, 2024, max. 10 Seiten zum Test)
python -m estimateiq.data.fetch_ted

# Schritt 2: Bereinigen und als Parquet speichern
python -m estimateiq.data.preprocess
```

## API starten

```bash
uvicorn estimateiq.api.main:app --host 0.0.0.0 --port 8000 --reload
```

Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)

## API-Beispiel

```bash
curl -X POST http://localhost:8000/api/estimate \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Entwicklung eines ERP-Systems für Bundesbehörde",
    "description": "Gegenstand der Ausschreibung ist die Entwicklung, Implementierung und Wartung eines webbasierten ERP-Systems...",
    "cpv_code": 72263000,
    "country": "DE",
    "duration_days": 365
  }'
```

Beispielantwort:

```json
{
  "estimated_cost_eur": 485000.00,
  "cost_range_low_eur": 388000.00,
  "cost_range_high_eur": 654750.00,
  "risk": {
    "risk_class": 1,
    "risk_label": "mittel",
    "probability_low": 0.22,
    "probability_medium": 0.61,
    "probability_high": 0.17
  },
  "cpv_category": "software",
  "model_version": "1.0.0"
}
```

## Projektstruktur

```
estimateiq/
├── data/
│   ├── fetch_ted.py       TED Europa API Connector
│   └── preprocess.py      Datenbereinigung & Feature Engineering
├── models/
│   ├── bert_extractor.py  BERT Embeddings (bert-base-german-cased)
│   ├── cost_model.py      XGBoost Kostenvorhersage
│   └── risk_model.py      Random Forest Risikoklassifikation
├── api/
│   └── main.py            FastAPI Endpunkte
├── requirements.txt
├── CLAUDE.md              Projektbeschreibung für Claude Code
└── README.md
```

## Lizenz

MIT
