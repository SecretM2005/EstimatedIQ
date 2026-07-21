-- ============================================================================
-- EstimateIQ – Migration 002: Rollen & Ownership (RBAC innerhalb eines Tenants)
-- ============================================================================
-- Auf bestehende Supabase-Datenbanken anwenden (SQL Editor). Idempotent.
--
--   - tenant_users.rolle : 'admin' (Vollzugriff) | 'mitglied' (nur Eigenes schreiben)
--   - projekte.ersteller_id : Supabase user_id des Erstellers;
--                             NULL = firmenweit / kein Owner (nur Admin editierbar)
-- ============================================================================

alter table tenant_users
    add column if not exists rolle text not null default 'mitglied';

alter table projekte
    add column if not exists ersteller_id text;

create index if not exists ix_projekte_ersteller on projekte(ersteller_id);

-- Bestehende Referenz-/Importdaten bleiben ohne Owner (firmenweit) – kein Update nötig.

-- Optional: einen bestehenden Benutzer zum Admin machen (E-Mail anpassen):
--   update tenant_users set rolle = 'admin' where email = 'demo@estimateiq.de';
