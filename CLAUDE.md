# EstimateIQ – Angebots- & Projektkalkulation für IT-Dienstleister

## Zweck
EstimateIQ ist ein B2B-SaaS-Tool, mit dem IT-Dienstleister und Agenturen im
DACH-Raum Angebote und Projekte kalkulieren. Kern ist eine embedding-basierte
Ähnlichkeitssuche: aus historischen Projektpositionen werden für neue Angebote
Aufwandsschätzungen und Referenzvorlagen vorgeschlagen.

> Hinweis: Das Projekt ist aus einem früheren ML-Kostenschätzer (TED-Daten,
> XGBoost, BERT) hervorgegangen. Dieser Teil wurde entfernt – der aktuelle
> Stand ist ausschließlich die Angebotskalkulation.

## Projektstruktur

```
estimateiq/
├── angebot/
│   ├── config.py       # .env-Konfiguration (DB-Umschaltung, Auth, CORS)
│   ├── database.py     # SQLAlchemy Engine: Supabase-Postgres ODER SQLite
│   ├── models.py       # ORM: Tenant, TenantUser, Rolle, Projekt,
│   │                   #      Leistungsposition, Angebot
│   ├── auth.py         # get_tenant_id(): Supabase-JWT → tenant_id
│   ├── router.py       # FastAPI-Endpunkte unter /api/v2/*
│   ├── similarity.py   # Cosine-Suche (pgvector-SQL bzw. numpy-Fallback)
│   ├── embeddings.py   # Sentence-Transformer (Inferenz, kein Training)
│   ├── csv_import.py   # CSV/Excel-Import historischer Positionen
│   └── pdf_export.py   # Angebots-PDF (reportlab)
├── api/
│   └── main.py         # FastAPI-App: Router + /health + Lifespan
frontend/               # React (Vite), Tailwind, react-router
migrations/
└── 001_supabase_schema.sql   # Postgres-Schema inkl. pgvector + RLS
data/                   # Laufzeit-Artefakte (gitignore'd): SQLite, PDFs
```

## Kern-Workflow
1. **Import**: Historische Projekte als CSV/Excel hochladen
   (`POST /api/v2/import/positionen`) → Positionen + Embeddings, als
   Referenzprojekte (`ist_referenz=true`) gespeichert.
2. **Kalkulation**: Neues Angebot anlegen, Positionen erfassen. Pro Position
   findet die Ähnlichkeitssuche vergleichbare historische Positionen und
   schlägt Stunden vor (`POST /api/v2/positionen/suche`).
3. **Referenzvorlage**: Ähnlichstes Referenzprojekt übernehmen
   (`POST /api/v2/projekte/{id}/positionen/aus-referenz/{ref_id}`).
4. **Angebot/PDF**: `POST /api/v2/projekte/{id}/angebote` → PDF-Export.

## Tech Stack
- Python 3.11, FastAPI + Pydantic v2, SQLAlchemy 2.0
- Supabase (Postgres + pgvector) in Produktion; SQLite als lokaler Fallback
- Supabase Auth (JWT) für Login und Tenant-Zuordnung
- sentence-transformers (`paraphrase-multilingual-MiniLM-L12-v2`, 384 Dims)
- reportlab (PDF), React + Vite + Tailwind (Frontend)

## Multi-Tenancy (nicht verhandelbar)
- Alle Geschäftstabellen tragen `tenant_id`.
- **Jede** Query wird auf `tenant_id` gefiltert; die einzige Tenant-Quelle ist
  `get_tenant_id()` (Dependency in jedem Endpunkt). Objekte fremder Tenants
  verhalten sich wie nicht existent (404).
- In Postgres zusätzlich RLS als Deny-All (anon-Key hat keinen Tabellenzugriff).

## Lokal vs. Supabase
- **Lokal**: `AUTH_DISABLED=true` → fester Dev-Tenant, kein Login, SQLite.
- **Supabase**: `DATABASE_URL` + `SUPABASE_URL` (+ `AUTH_DISABLED=false`).
  Schema via `migrations/001_supabase_schema.sql` einspielen.
- Struktur: `.env.example` (Backend) und `frontend/.env.example` (Vite).

## Starten
```bash
# Backend
AUTH_DISABLED=true uvicorn estimateiq.api.main:app --reload
# Frontend
cd frontend && npm run dev
```

## Demo-Daten (Seed)
```bash
# Legt Demo-Tenant, Rollen und 7 Referenzprojekte (44 Positionen) inkl.
# Embeddings an. Nutzt dieselbe DB-Umschaltung wie die App.
python -m estimateiq.angebot.seed            # idempotent
python -m estimateiq.angebot.seed --reset    # Tenant-Daten vorher löschen
```
- **Lokal** (`AUTH_DISABLED=true`): seedet in den Dev-Tenant, sofort ohne Login sichtbar.
- **Supabase**: seedet in "Demo IT-Solutions GmbH"; mit `SUPABASE_SERVICE_ROLE_KEY`
  wird zusätzlich ein Login-User (`demo@estimateiq.de`) angelegt und zugeordnet.

## Wichtige Konventionen
- Kommentare und Log-Meldungen auf Deutsch
- Alle Beträge in EUR
- Embeddings: pgvector-Spalte `embedding` (Postgres) bzw. JSON-Text (SQLite);
  Zugriff immer über `get_embedding()` / `set_embedding()`
- PDFs unter `data/angebote_pdf/` (nicht im Git)

## Deployment
Siehe `DEPLOYMENT.md` – Backend via `Dockerfile` (Railway/Render), Frontend via
`frontend/vercel.json` bzw. `netlify.toml`, Supabase-Migrationen `001`+`002`.

## Nächste Schritte
- [x] Seed-Skript für Demo-Tenants mit realistischen Projektdaten
- [x] Rollen & Ownership (RBAC) innerhalb eines Tenants
- [x] Deployment-Konfiguration (Backend: Railway/Render, Frontend: Vercel/Netlify)
- [ ] Angebots-Duplikate vermeiden (PDF-Klick legt aktuell je ein Angebot an)
