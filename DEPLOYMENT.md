# Deployment – EstimateIQ

Die App besteht aus drei Teilen, die getrennt betrieben werden:

```
Frontend (Vercel/Netlify)  ──HTTPS──▶  Backend-API (Railway/Render)  ──▶  Supabase (Postgres + pgvector, Auth)
   React/Vite (statisch)                FastAPI + sentence-transformers        DB + Login
```

> Diese Anleitung bereitet nur die Konfiguration vor. Das eigentliche Deployen
> machst du selbst über die jeweilige Plattform.

---

## 0. Voraussetzung: Supabase einrichten

1. Supabase-Projekt anlegen (Datenbank-Passwort notieren).
2. Im **SQL Editor** nacheinander ausführen:
   - `migrations/001_supabase_schema.sql`
   - `migrations/002_rbac.sql`
3. Werte bereitlegen (Project Settings → API / Database):
   - Project URL, `anon`/publishable Key, `service_role`/secret Key
   - Connection String (**Session pooler**, Port 5432 – IPv4-tauglich)

Der Demo-Seed folgt in Schritt 3, nachdem das Backend läuft.

---

## 1. Backend – Railway oder Render

Beide bauen direkt aus dem `Dockerfile` im Repo-Root (das Embedding-Modell wird
ins Image gebacken → schneller, netzunabhängiger Start).

**Railway:** New Project → Deploy from GitHub Repo → Branch `pivot/angebotskalkulation-mvp`.
Railway erkennt das Dockerfile automatisch.

**Render:** New → Web Service → Repo verbinden → Runtime „Docker".

### Umgebungsvariablen (im Plattform-Dashboard setzen)

| Variable | Wert |
|---|---|
| `DATABASE_URL` | Supabase **Session-Pooler**-String, `[YOUR-PASSWORD]` ersetzt |
| `SUPABASE_URL` | `https://<ref>.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | Secret Key (für Benutzeranlage) |
| `SUPABASE_JWT_SECRET` | nur falls Login-Verifikation über JWKS fehlschlägt (Legacy-Projekte) |
| `AUTH_DISABLED` | `false` |
| `CORS_ORIGINS` | die Frontend-URL, z. B. `https://estimateiq.vercel.app` (nach Schritt 2 nachtragen) |

- **Health-Check:** Pfad `/health` (liefert `{"status":"ok",...}`).
- **Port:** wird über `$PORT` bereitgestellt; das Dockerfile nutzt ihn automatisch.
- **RAM:** sentence-transformers zieht `torch` (~1–2 GB Speicherbedarf). **Free-Tier
  (512 MB) reicht nicht** – eine kleine bezahlte Instanz (Railway: ausreichend RAM,
  Render: mind. „Standard") wählen, sonst OOM beim Start.

Nach dem ersten Deploy die Backend-URL notieren (z. B. `https://estimateiq-api.up.railway.app`).

---

## 2. Frontend – Vercel oder Netlify

**Vercel:** New Project → Repo importieren → **Root Directory = `frontend`**.
`frontend/vercel.json` liefert Build-Command, Output (`dist`) und SPA-Rewrites.

**Netlify:** New site → Repo → Base directory `frontend`. `frontend/netlify.toml`
liefert Build und SPA-Redirects.

### Umgebungsvariablen (im Plattform-Dashboard setzen)

| Variable | Wert |
|---|---|
| `VITE_API_URL` | die Backend-URL aus Schritt 1 (ohne `/api/v2`) |
| `VITE_SUPABASE_URL` | `https://<ref>.supabase.co` |
| `VITE_SUPABASE_ANON_KEY` | `anon`/publishable Key |

Nach dem Deploy die Frontend-URL beim Backend als `CORS_ORIGINS` eintragen
(Schritt 1) und das Backend neu starten – sonst blockiert der Browser die API-Aufrufe.

---

## 3. Demo-Daten + Login-User in Supabase

Am einfachsten lokal gegen die Supabase-DB (dieselben Env-Variablen wie beim Backend
in einer lokalen `.env`):

```bash
pip install -r requirements.txt
python -m estimateiq.angebot.seed --reset
```

Legt Demo-Tenant, Rollen und 7 Referenzprojekte an. Mit gesetztem
`SUPABASE_SERVICE_ROLE_KEY` wird auch der Login-User `demo@estimateiq.de` /
`Demo1234!` (als **Admin**) angelegt. Falls die automatische Anlage nicht greift,
gibt das Skript die manuellen SQL-Schritte aus.

---

## Reihenfolge auf einen Blick

1. Supabase: Schema (`001` + `002`) einspielen.
2. Backend deployen (Env-Variablen, `AUTH_DISABLED=false`).
3. Frontend deployen (Env-Variablen inkl. `VITE_API_URL`).
4. `CORS_ORIGINS` beim Backend auf die Frontend-URL setzen, Backend neu starten.
5. Seed laufen lassen → mit `demo@estimateiq.de` / `Demo1234!` einloggen.

## Checkliste bei Problemen

- **Login „E-Mail/Passwort falsch":** Seed-User fehlt → Schritt 3, oder User in
  Supabase → Authentication anlegen (Auto Confirm) und in `tenant_users` mit
  `rolle='admin'` zuordnen.
- **API-Aufrufe im Browser blockiert (CORS):** `CORS_ORIGINS` = exakte Frontend-URL.
- **Backend startet nicht / OOM:** zu wenig RAM → größere Instanz.
- **`Network is unreachable` zur DB:** Direct-Connection (IPv6) statt **Session pooler**
  verwendet.
- **Login-Signaturfehler:** `SUPABASE_JWT_SECRET` aus Settings → JWT nachtragen.
