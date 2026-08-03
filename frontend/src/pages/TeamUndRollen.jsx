import { useEffect, useState } from 'react'
import { useAuth } from '../auth/AuthProvider'
import {
  getTeam, createTeamMember, updateTeamMemberRolle, removeTeamMember,
  getTeamrollen, createTeamrolle, updateTeamrolle, deleteTeamrolle,
  getPermissions, getAuditLog,
} from '../api/angebot'

// Backend liefert bereits sprechende deutsche Meldungen in `detail`
// (z. B. Letzter-Owner-Schutz, Rechte-Delegation) – die zuerst zeigen.
function fehlerText(err) {
  const detail = err?.response?.data?.detail
  if (detail) return detail
  const status = err?.response?.status
  if (status === 409) return 'Ein Eintrag mit diesem Namen/dieser E-Mail existiert bereits.'
  if (status === 403) return 'Keine Berechtigung für diese Aktion.'
  if (status === 502) return 'Benutzer konnte bei Supabase nicht angelegt werden.'
  return 'Aktion fehlgeschlagen.'
}

const BEREICH_LABEL = {
  dashboard: 'Dashboard',
  projekte: 'Projekte',
  positionen: 'Positionen',
  rollen: 'Stundensatz-Rollen',
  import: 'Import',
  settings: 'Einstellungen',
}

function StatusPill({ status }) {
  const aktiv = status === 'aktiv'
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', height: 22, padding: '0 10px',
      fontSize: 11.5, fontWeight: 600, borderRadius: 999,
      background: aktiv ? '#f0fdfa' : '#fffbeb',
      color: aktiv ? '#0f766e' : '#b45309',
      border: `1px solid ${aktiv ? '#99f6e4' : '#fef3c7'}`, whiteSpace: 'nowrap',
    }}>
      {aktiv ? 'Aktiv' : 'Eingeladen'}
    </span>
  )
}

function TypPill({ isSystem }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', height: 22, padding: '0 10px',
      fontSize: 11.5, fontWeight: 600, borderRadius: 999,
      background: isSystem ? '#eef2ff' : '#f8fafc',
      color: isSystem ? '#4f46e5' : '#475569',
      border: `1px solid ${isSystem ? '#e0e7ff' : '#e2e8f0'}`, whiteSpace: 'nowrap',
    }}>
      {isSystem ? 'System' : 'Benutzerdefiniert'}
    </span>
  )
}

// ─── Rollen-Editor (Modal) ────────────────────────────────────────────────────

function RollenEditorModal({ rolle, permissions, onSave, onDelete, onCancel }) {
  const istOwner   = rolle?.is_system && rolle.name === 'Owner'
  const istSystem  = !!rolle?.is_system
  const [name, setName] = useState(rolle?.name || '')
  const [beschreibung, setBeschreibung] = useState(rolle?.beschreibung || '')
  const [ausgewaehlt, setAusgewaehlt] = useState(new Set(rolle?.permissions || []))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const bereiche = permissions.reduce((acc, p) => {
    (acc[p.bereich] ||= []).push(p)
    return acc
  }, {})

  const toggle = (key) => {
    if (istOwner) return
    setAusgewaehlt(prev => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  }

  const handleSave = async () => {
    setSaving(true); setError(null)
    try {
      await onSave({
        name: istSystem ? undefined : name.trim(),
        beschreibung: istSystem ? undefined : beschreibung.trim(),
        permissions: Array.from(ausgewaehlt),
      })
    } catch (err) {
      setError(fehlerText(err))
    } finally { setSaving(false) }
  }

  const handleDelete = async () => {
    if (!confirm(`Rolle "${rolle.name}" wirklich löschen?`)) return
    setSaving(true); setError(null)
    try {
      await onDelete()
    } catch (err) {
      setError(fehlerText(err))
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-slate-900/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl border border-slate-200 w-full max-w-lg max-h-[85vh] overflow-y-auto p-6">
        <h3 className="text-[15px] font-semibold text-slate-900 mb-1">
          {rolle ? `Rolle "${rolle.name}"` : 'Neue Rolle anlegen'}
        </h3>

        {istOwner && (
          <p className="text-[12.5px] text-slate-500 mb-4">
            Die Owner-Rolle hat immer alle Berechtigungen und kann nicht geändert werden.
          </p>
        )}
        {istSystem && !istOwner && (
          <p className="text-[12.5px] text-slate-500 mb-4">
            Name und Beschreibung von Systemrollen sind gesperrt. Berechtigungen sind änderbar.
          </p>
        )}

        <div className="grid sm:grid-cols-2 gap-3 mb-4">
          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Name *</label>
            <input
              value={name} onChange={e => setName(e.target.value)} required disabled={istSystem}
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm disabled:bg-slate-50 disabled:text-slate-400 focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"
            />
          </div>
          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Beschreibung</label>
            <input
              value={beschreibung} onChange={e => setBeschreibung(e.target.value)} disabled={istSystem}
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm disabled:bg-slate-50 disabled:text-slate-400 focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"
            />
          </div>
        </div>

        <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-2">Berechtigungen</label>
        <div className="flex flex-col gap-4 mb-4">
          {Object.entries(bereiche).map(([bereich, perms]) => (
            <div key={bereich}>
              <p className="text-[12px] font-semibold text-slate-700 mb-1.5">{BEREICH_LABEL[bereich] || bereich}</p>
              <div className="flex flex-col gap-1.5 pl-1">
                {perms.map(p => (
                  <label key={p.key} className={`flex items-start gap-2 text-[12.5px] ${istOwner ? 'text-slate-400' : 'text-slate-700 cursor-pointer'}`}>
                    <input
                      type="checkbox" checked={ausgewaehlt.has(p.key)}
                      onChange={() => toggle(p.key)} disabled={istOwner}
                      className="mt-0.5 accent-accent"
                    />
                    <span>{p.beschreibung}</span>
                  </label>
                ))}
              </div>
            </div>
          ))}
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg px-3.5 py-2.5 mb-4 text-[12.5px] text-red-700">
            {error}
          </div>
        )}

        <div className="flex gap-2 justify-between">
          <div>
            {rolle && !istSystem && (
              <button onClick={handleDelete} disabled={saving}
                className="h-9 px-3 text-[12.5px] font-semibold text-red-500 hover:text-red-700 transition-colors disabled:opacity-50">
                Löschen
              </button>
            )}
          </div>
          <div className="flex gap-2">
            <button onClick={onCancel} className="h-9 px-4 bg-white border border-slate-200 rounded-lg text-sm font-semibold text-slate-700 hover:bg-slate-50 transition-colors">
              {istOwner ? 'Schließen' : 'Abbrechen'}
            </button>
            {!istOwner && (
              <button onClick={handleSave} disabled={saving || (!istSystem && !name.trim())}
                className="h-9 px-4 bg-accent hover:bg-accent-hover text-white rounded-lg text-sm font-semibold transition-colors disabled:opacity-50">
                {saving ? 'Speichern…' : 'Speichern'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Hauptseite ───────────────────────────────────────────────────────────────

const TABS = [
  { key: 'team',   label: 'Team' },
  { key: 'rollen', label: 'Rollen' },
  { key: 'audit',  label: 'Audit-Log' },
]

export default function TeamUndRollen() {
  const { me } = useAuth()
  const [tab, setTab] = useState('team')

  const [team,        setTeam]        = useState([])
  const [teamrollen,  setTeamrollen]  = useState([])
  const [permissions, setPermissions] = useState([])
  const [auditLog,    setAuditLog]    = useState([])
  const [loading,     setLoading]     = useState(true)
  const [error,       setError]       = useState(null)

  const [showMemberForm, setShowMemberForm] = useState(false)
  const [memberEmail,    setMemberEmail]    = useState('')
  const [memberPasswort, setMemberPasswort] = useState('')
  const [memberRolleId,  setMemberRolleId]  = useState('')
  const [savingMember,   setSavingMember]   = useState(false)
  const [busyUserId,     setBusyUserId]     = useState(null)

  const [editRolle, setEditRolle]     = useState(undefined) // undefined = geschlossen, null = neu

  const ladeAlles = () => {
    setLoading(true)
    Promise.all([getTeam(), getTeamrollen(), getPermissions()])
      .then(([t, r, p]) => {
        setTeam(t); setTeamrollen(r); setPermissions(p); setError(null)
        if (!memberRolleId && r.length) setMemberRolleId(String(r[0].id))
      })
      .catch(err => setError(fehlerText(err)))
      .finally(() => setLoading(false))
  }
  useEffect(() => { ladeAlles() }, [])
  useEffect(() => { if (tab === 'audit') getAuditLog().then(setAuditLog).catch(() => setAuditLog([])) }, [tab])

  const rollenName = (id) => teamrollen.find(r => r.id === id)?.name || '–'

  // ── Team-Aktionen ──
  const handleCreateMember = async (e) => {
    e.preventDefault()
    setSavingMember(true); setError(null)
    try {
      await createTeamMember({ email: memberEmail.trim(), passwort: memberPasswort, teamrolle_id: parseInt(memberRolleId, 10) })
      setShowMemberForm(false); setMemberEmail(''); setMemberPasswort('')
      ladeAlles()
    } catch (err) {
      setError(fehlerText(err))
    } finally { setSavingMember(false) }
  }

  const handleRolleWechsel = async (userId, teamrolleId) => {
    setBusyUserId(userId); setError(null)
    try {
      await updateTeamMemberRolle(userId, parseInt(teamrolleId, 10))
      ladeAlles()
    } catch (err) {
      setError(fehlerText(err))
    } finally { setBusyUserId(null) }
  }

  const handleRemoveMember = async (userId) => {
    if (!confirm('Benutzer aus dem Team entfernen?')) return
    setBusyUserId(userId); setError(null)
    try {
      await removeTeamMember(userId)
      ladeAlles()
    } catch (err) {
      setError(fehlerText(err))
    } finally { setBusyUserId(null) }
  }

  // ── Rollen-Aktionen ──
  const handleSaveRolle = async (body) => {
    if (editRolle?.id) await updateTeamrolle(editRolle.id, body)
    else await createTeamrolle(body)
    setEditRolle(undefined)
    ladeAlles()
  }

  const handleDeleteRolle = async () => {
    await deleteTeamrolle(editRolle.id)
    setEditRolle(undefined)
    ladeAlles()
  }

  const adminCount = teamrollen
    .filter(r => r.permissions.includes('settings.manage_users'))
    .reduce((n, r) => n + team.filter(m => m.teamrolle_id === r.id).length, 0)

  const TEAM_COL   = '1fr 200px 100px 90px'
  const ROLLEN_COL = '1fr 150px 120px 90px'

  return (
    <div className="p-8 pb-16">
      {/* Header */}
      <div className="flex items-end justify-between gap-4 mb-6">
        <div>
          <h1 className="text-[24px] font-bold tracking-tight text-slate-900 m-0">Team & Rollen</h1>
          <p className="mt-1.5 text-[13.5px] text-slate-500">
            {team.length} Mitglieder · {adminCount} mit Verwaltungsrechten
            {me?.tenant_name ? ` · ${me.tenant_name}` : ''}
          </p>
        </div>
        {tab === 'team' && (
          <button onClick={() => setShowMemberForm(s => !s)}
            className="h-10 inline-flex items-center gap-2 px-4 bg-accent hover:bg-accent-hover text-white text-[13.5px] font-semibold rounded-lg transition-colors shadow-accent">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"/></svg>
            Neuer Benutzer
          </button>
        )}
        {tab === 'rollen' && (
          <button onClick={() => setEditRolle(null)}
            className="h-10 inline-flex items-center gap-2 px-4 bg-accent hover:bg-accent-hover text-white text-[13.5px] font-semibold rounded-lg transition-colors shadow-accent">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"/></svg>
            Neue Rolle
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-0 border-b border-slate-200 mb-5">
        {TABS.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`h-10 px-4 text-[13px] font-medium border-b-2 transition-colors ${
              tab === t.key ? 'border-accent text-accent font-semibold' : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 mb-5 text-[13px] text-red-700">{error}</div>
      )}

      {loading ? (
        <div className="text-slate-400 text-center py-20 text-sm">Lade…</div>
      ) : (
        <>
          {/* ── Team-Tab ── */}
          {tab === 'team' && (
            <>
              {showMemberForm && (
                <form onSubmit={handleCreateMember} className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs mb-5 flex flex-col gap-4">
                  <h2 className="text-[14px] font-semibold text-slate-900">Neuen Benutzer anlegen</h2>
                  <div className="grid sm:grid-cols-3 gap-4">
                    <div>
                      <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">E-Mail *</label>
                      <input type="email" value={memberEmail} onChange={e => setMemberEmail(e.target.value)} required
                        placeholder="name@firma.de"
                        className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
                    </div>
                    <div>
                      <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Passwort *</label>
                      <input type="password" value={memberPasswort} onChange={e => setMemberPasswort(e.target.value)} required minLength={6}
                        placeholder="Mindestens 6 Zeichen"
                        className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
                    </div>
                    <div>
                      <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Rolle *</label>
                      <select value={memberRolleId} onChange={e => setMemberRolleId(e.target.value)}
                        className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent">
                        {teamrollen.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
                      </select>
                    </div>
                  </div>
                  <div className="flex gap-2 justify-end">
                    <button type="button" onClick={() => setShowMemberForm(false)} className="h-9 px-4 bg-white border border-slate-200 rounded-lg text-sm font-semibold text-slate-700 hover:bg-slate-50 transition-colors">Abbrechen</button>
                    <button type="submit" disabled={savingMember} className="h-9 px-4 bg-accent hover:bg-accent-hover text-white rounded-lg text-sm font-semibold transition-colors disabled:opacity-50">
                      {savingMember ? 'Anlegen…' : 'Anlegen'}
                    </button>
                  </div>
                </form>
              )}

              {team.length === 0 ? (
                <div className="bg-white border border-slate-200 rounded-xl p-16 text-center shadow-xs">
                  <p className="text-[15px] font-semibold text-slate-900 mb-1">Keine Benutzer</p>
                  <p className="text-sm text-slate-500">Lege Benutzer für deinen Mandanten an.</p>
                </div>
              ) : (
                <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
                  <div className="grid items-center px-5 py-2.5 bg-slate-50 border-b border-slate-200" style={{ gridTemplateColumns: TEAM_COL }}>
                    {['E-Mail', 'Rolle', 'Status', ''].map(h => (
                      <span key={h} className="text-[10.5px] font-semibold uppercase tracking-[0.04em] text-slate-400">{h}</span>
                    ))}
                  </div>
                  {team.map((u) => {
                    const istIch = me?.user_id === u.user_id
                    return (
                      <div key={u.user_id} className="grid items-center px-5 py-3.5 border-t border-slate-100 group" style={{ gridTemplateColumns: TEAM_COL }}>
                        <div className="min-w-0 pr-4 flex items-center gap-2.5">
                          <span className="w-7 h-7 rounded-full bg-slate-100 text-slate-500 text-[10px] font-bold flex items-center justify-center flex-none select-none">
                            {u.email.slice(0, 2).toUpperCase()}
                          </span>
                          <span className="text-[13px] font-semibold text-slate-900 truncate">{u.email}</span>
                          {istIch && <span className="text-[10.5px] text-slate-400 font-medium flex-none">(Sie)</span>}
                        </div>
                        <div>
                          {istIch ? (
                            <span className="text-[12.5px] text-slate-700">{rollenName(u.teamrolle_id)}</span>
                          ) : (
                            <select
                              value={u.teamrolle_id} disabled={busyUserId === u.user_id}
                              onChange={e => handleRolleWechsel(u.user_id, e.target.value)}
                              className="h-8 pl-2.5 pr-7 bg-white border border-slate-200 rounded-lg text-[12.5px] font-medium text-slate-700 appearance-none focus:outline-none focus:ring-2 focus:ring-accent/20 cursor-pointer disabled:opacity-50"
                              style={{
                                backgroundImage: 'url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'11\' height=\'11\' viewBox=\'0 0 24 24\' fill=\'none\'%3E%3Cpath d=\'M6 9l6 6 6-6\' stroke=\'%2394a3b8\' stroke-width=\'2.2\' stroke-linecap=\'round\' stroke-linejoin=\'round\'/%3E%3C/svg%3E")',
                                backgroundRepeat: 'no-repeat', backgroundPosition: 'right 8px center',
                              }}
                            >
                              {teamrollen.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
                            </select>
                          )}
                        </div>
                        <div><StatusPill status={u.status} /></div>
                        <div className="flex items-center justify-end gap-1">
                          {!istIch && (
                            <button onClick={() => handleRemoveMember(u.user_id)} disabled={busyUserId === u.user_id}
                              className="opacity-0 group-hover:opacity-100 text-[11px] text-red-400 hover:text-red-600 px-2 py-1 transition-opacity disabled:opacity-30">
                              Entfernen
                            </button>
                          )}
                        </div>
                      </div>
                    )
                  })}
                  <div className="flex items-center px-5 py-3 border-t border-slate-200">
                    <span className="text-[12px] text-slate-400 tabular-nums">{team.length} Benutzer</span>
                  </div>
                </div>
              )}
            </>
          )}

          {/* ── Rollen-Tab ── */}
          {tab === 'rollen' && (
            <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
              <div className="grid items-center px-5 py-2.5 bg-slate-50 border-b border-slate-200" style={{ gridTemplateColumns: ROLLEN_COL }}>
                {['Name', 'Typ', 'Berechtigungen', ''].map(h => (
                  <span key={h} className="text-[10.5px] font-semibold uppercase tracking-[0.04em] text-slate-400">{h}</span>
                ))}
              </div>
              {teamrollen.map(r => (
                <div key={r.id} className="grid items-center px-5 py-3.5 border-t border-slate-100 group cursor-pointer hover:bg-slate-50 transition-colors"
                  style={{ gridTemplateColumns: ROLLEN_COL }} onClick={() => setEditRolle(r)}>
                  <div className="min-w-0 pr-4">
                    <p className="text-[13px] font-semibold text-slate-900">{r.name}</p>
                    {r.beschreibung && <p className="text-[11.5px] text-slate-400 truncate">{r.beschreibung}</p>}
                  </div>
                  <div><TypPill isSystem={r.is_system} /></div>
                  <div><span className="text-[12.5px] text-slate-600 tabular-nums">{r.permissions.length}</span></div>
                  <div className="flex items-center justify-end">
                    <span className="opacity-0 group-hover:opacity-100 text-[11px] text-accent transition-opacity">Bearbeiten →</span>
                  </div>
                </div>
              ))}
              <div className="flex items-center px-5 py-3 border-t border-slate-200">
                <span className="text-[12px] text-slate-400 tabular-nums">{teamrollen.length} Rollen</span>
              </div>
            </div>
          )}

          {/* ── Audit-Log-Tab ── */}
          {tab === 'audit' && (
            auditLog.length === 0 ? (
              <div className="bg-white border border-slate-200 rounded-xl p-16 text-center shadow-xs">
                <p className="text-[15px] font-semibold text-slate-900 mb-1">Noch keine Einträge</p>
                <p className="text-sm text-slate-500">Rollen- und Rechteänderungen erscheinen hier.</p>
              </div>
            ) : (
              <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
                {auditLog.map(e => (
                  <div key={e.id} className="px-5 py-3 border-t border-slate-100 first:border-t-0">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-[12.5px] font-semibold text-slate-800">{e.aktion.replace(/_/g, ' ')}</span>
                      <span className="text-[11px] text-slate-400 tabular-nums flex-none">
                        {new Date(e.erstellt_am).toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>
                    <p className="text-[11.5px] text-slate-400 mt-0.5">
                      {e.ziel_typ} · {e.ziel_id} · von {e.actor_user_id === me?.user_id ? 'Ihnen' : e.actor_user_id}
                    </p>
                  </div>
                ))}
              </div>
            )
          )}
        </>
      )}

      {editRolle !== undefined && (
        <RollenEditorModal
          rolle={editRolle}
          permissions={permissions}
          onSave={handleSaveRolle}
          onDelete={handleDeleteRolle}
          onCancel={() => setEditRolle(undefined)}
        />
      )}
    </div>
  )
}
