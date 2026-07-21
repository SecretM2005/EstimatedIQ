---
title: EstimateIQ API
emoji: 📊
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 8000
pinned: false
---

# EstimateIQ

B2B-SaaS-Tool zur Angebots- und Projektkalkulation für IT-Dienstleister und
Agenturen im DACH-Raum. Kern ist eine embedding-basierte Ähnlichkeitssuche:
aus historischen Projektpositionen werden für neue Angebote Aufwandsschätzungen
und Referenzvorlagen vorgeschlagen.

> Dieses Repository enthält das **Backend** (FastAPI). Bei einem Hugging-Face-Space
> wird daraus über das `Dockerfile` die API gebaut. Das Frontend (`frontend/`,
> React/Vite) wird separat deployt (z. B. Vercel).

## Architektur

```
Frontend (Vercel)  ──HTTPS──▶  Backend-API (dieses Repo)  ──▶  Supabase (Postgres + pgvector, Auth)
```

- Python 3.11, FastAPI + SQLAlchemy 2.0, Pydantic v2
- Supabase (Postgres + pgvector) in Produktion, SQLite als lokaler Fallback
- Supabase Auth (JWT), strikte Multi-Tenancy (jede Query auf `tenant_id` gefiltert)
- sentence-transformers (`paraphrase-multilingual-MiniLM-L12-v2`, 384 Dims, nur Inferenz)
- reportlab (Angebots-PDF)

## Lokal starten

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
AUTH_DISABLED=true uvicorn estimateiq.api.main:app --port 8000
# Frontend:
cd frontend && npm install && npm run dev
```

Health-Check: `GET /health`. Endpunkte unter `/api/v2/*`. Swagger: `/docs`.

## Umgebungsvariablen (Supabase-Betrieb)

| Variable | Zweck |
|---|---|
| `DATABASE_URL` | Supabase-Postgres (Session-Pooler) |
| `SUPABASE_URL` | Projekt-URL (JWT-Verifikation) |
| `SUPABASE_SERVICE_ROLE_KEY` | Benutzerverwaltung/Seed |
| `SUPABASE_JWT_SECRET` | nur falls JWKS-Verifikation nicht greift |
| `AUTH_DISABLED` | `false` in Produktion |
| `CORS_ORIGINS` | Frontend-Origin(s), Standard `*` |

## Tests

```bash
pip install -r requirements-test.txt && pytest    # Backend (14 Tests)
cd frontend && npm install && npm test            # Frontend (Vitest)
```

## Deployment

Siehe `DEPLOYMENT.md`. Demo-Daten via `python -m estimateiq.angebot.seed`.

## Lizenz

MIT
