import { useEffect, useState } from 'react'
import { useAuth } from '../auth/AuthProvider'
import { getUsers, createUser, updateUserRole, deleteUser } from '../api/angebot'

const ROLLEN = [
  { value: 'admin',    label: 'Administrator' },
  { value: 'mitglied', label: 'Mitglied' },
]
const rollenLabel = r => ROLLEN.find(x => x.value === r)?.label || r

// API-Fehler in eine verständliche deutsche Meldung übersetzen
function fehlerText(err) {
  const status = err?.response?.status
  if (status === 400) return 'Benutzerverwaltung erfordert Supabase-Konfiguration.'
  if (status === 409) return 'Diese E-Mail-Adresse existiert bereits.'
  if (status === 403) return 'Keine Berechtigung für diese Aktion.'
  if (status === 502) return 'Benutzer konnte bei Supabase nicht angelegt werden.'
  return err?.response?.data?.detail || 'Aktion fehlgeschlagen.'
}

function RollePill({ rolle }) {
  const admin = rolle === 'admin'
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', height: 22, padding: '0 10px',
      fontSize: 11.5, fontWeight: 600, borderRadius: 999,
      background: admin ? '#eef2ff' : '#f8fafc',
      color:      admin ? '#4f46e5' : '#475569',
      border:     `1px solid ${admin ? '#e0e7ff' : '#e2e8f0'}`, whiteSpace: 'nowrap',
    }}>
      {rollenLabel(rolle)}
    </span>
  )
}

export default function Benutzer() {
  const { me } = useAuth()
  const [users,    setUsers]    = useState([])
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState(null)
  const [showForm, setShowForm] = useState(false)

  // Formular für neuen Benutzer
  const [email,    setEmail]    = useState('')
  const [passwort, setPasswort] = useState('')
  const [rolle,    setRolle]    = useState('mitglied')
  const [saving,   setSaving]   = useState(false)
  const [busyId,   setBusyId]   = useState(null)

  const load = () => {
    setLoading(true)
    getUsers()
      .then(u => { setUsers(u); setError(null) })
      .catch(err => setError(fehlerText(err)))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  const openCreate = () => { setEmail(''); setPasswort(''); setRolle('mitglied'); setError(null); setShowForm(true) }
  const cancel     = () => { setShowForm(false); setError(null) }

  const handleCreate = async (e) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await createUser({ email: email.trim(), passwort, rolle })
      cancel(); load()
    } catch (err) {
      setError(fehlerText(err))
    } finally { setSaving(false) }
  }

  const handleRolle = async (id, neueRolle) => {
    setBusyId(id)
    setError(null)
    try {
      await updateUserRole(id, neueRolle)
      load()
    } catch (err) {
      setError(fehlerText(err))
    } finally { setBusyId(null) }
  }

  const handleDelete = async (id) => {
    if (!confirm('Benutzer löschen?')) return
    setBusyId(id)
    setError(null)
    try {
      await deleteUser(id)
      load()
    } catch (err) {
      setError(fehlerText(err))
    } finally { setBusyId(null) }
  }

  const adminCount = users.filter(u => u.rolle === 'admin').length
  const COL = '1fr 180px 160px'

  return (
    <div className="p-8 pb-16">
      {/* Header */}
      <div className="flex items-end justify-between gap-4 mb-6">
        <div>
          <h1 className="text-[24px] font-bold tracking-tight text-slate-900 m-0">Benutzer</h1>
          <p className="mt-1.5 text-[13.5px] text-slate-500">
            {users.length} Benutzer · {adminCount} Administrator{adminCount !== 1 ? 'en' : ''}
            {me?.tenant_name ? ` · ${me.tenant_name}` : ''}
          </p>
        </div>
        <button
          onClick={openCreate}
          className="h-10 inline-flex items-center gap-2 px-4 bg-accent hover:bg-accent-hover text-white text-[13.5px] font-semibold rounded-lg transition-colors shadow-accent"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"/></svg>
          Neuer Benutzer
        </button>
      </div>

      {/* Fehlermeldung */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 mb-5 text-[13px] text-red-700">
          {error}
        </div>
      )}

      {/* Form */}
      {showForm && (
        <form onSubmit={handleCreate} className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs mb-5 flex flex-col gap-4">
          <h2 className="text-[14px] font-semibold text-slate-900">Neuen Benutzer anlegen</h2>
          <div className="grid sm:grid-cols-3 gap-4">
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">E-Mail *</label>
              <input
                type="email" value={email} onChange={e => setEmail(e.target.value)} required
                placeholder="name@firma.de"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"
              />
            </div>
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Passwort *</label>
              <input
                type="password" value={passwort} onChange={e => setPasswort(e.target.value)} required minLength={6}
                placeholder="Mindestens 6 Zeichen"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"
              />
            </div>
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Rolle *</label>
              <select
                value={rolle} onChange={e => setRolle(e.target.value)}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"
              >
                {ROLLEN.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
              </select>
            </div>
          </div>
          <div className="flex gap-2 justify-end">
            <button type="button" onClick={cancel} className="h-9 px-4 bg-white border border-slate-200 rounded-lg text-sm font-semibold text-slate-700 hover:bg-slate-50 transition-colors">Abbrechen</button>
            <button type="submit" disabled={saving} className="h-9 px-4 bg-accent hover:bg-accent-hover text-white rounded-lg text-sm font-semibold transition-colors disabled:opacity-50">
              {saving ? 'Anlegen…' : 'Anlegen'}
            </button>
          </div>
        </form>
      )}

      {/* Table */}
      {loading ? (
        <div className="text-slate-400 text-center py-20 text-sm">Lade…</div>
      ) : users.length === 0 ? (
        <div className="bg-white border border-slate-200 rounded-xl p-16 text-center shadow-xs">
          <p className="text-[15px] font-semibold text-slate-900 mb-1">Keine Benutzer</p>
          <p className="text-sm text-slate-500">Lege Benutzer für deinen Mandanten an.</p>
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
          {/* Head */}
          <div className="grid items-center px-5 py-2.5 bg-slate-50 border-b border-slate-200"
            style={{ gridTemplateColumns: COL }}>
            {['E-Mail', 'Rolle', ''].map(h => (
              <span key={h} className="text-[10.5px] font-semibold uppercase tracking-[0.04em] text-slate-400">{h}</span>
            ))}
          </div>

          {users.map((u) => {
            const istIch = me?.user_id === u.user_id
            return (
              <div
                key={u.user_id}
                className="grid items-center px-5 py-3.5 border-t border-slate-100 group"
                style={{ gridTemplateColumns: COL }}
              >
                {/* E-Mail */}
                <div className="min-w-0 pr-4 flex items-center gap-2.5">
                  <span className="w-7 h-7 rounded-full bg-slate-100 text-slate-500 text-[10px] font-bold flex items-center justify-center flex-none select-none">
                    {u.email.slice(0, 2).toUpperCase()}
                  </span>
                  <span className="text-[13px] font-semibold text-slate-900 truncate">{u.email}</span>
                  {istIch && <span className="text-[10.5px] text-slate-400 font-medium flex-none">(Sie)</span>}
                </div>

                {/* Rolle */}
                <div>
                  {istIch ? (
                    <RollePill rolle={u.rolle} />
                  ) : (
                    <select
                      value={u.rolle}
                      disabled={busyId === u.user_id}
                      onChange={e => handleRolle(u.user_id, e.target.value)}
                      className="h-8 pl-2.5 pr-7 bg-white border border-slate-200 rounded-lg text-[12.5px] font-medium text-slate-700 appearance-none focus:outline-none focus:ring-2 focus:ring-accent/20 cursor-pointer disabled:opacity-50"
                      style={{
                        backgroundImage: 'url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'11\' height=\'11\' viewBox=\'0 0 24 24\' fill=\'none\'%3E%3Cpath d=\'M6 9l6 6 6-6\' stroke=\'%2394a3b8\' stroke-width=\'2.2\' stroke-linecap=\'round\' stroke-linejoin=\'round\'/%3E%3C/svg%3E")',
                        backgroundRepeat: 'no-repeat',
                        backgroundPosition: 'right 8px center',
                      }}
                    >
                      {ROLLEN.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
                    </select>
                  )}
                </div>

                {/* Aktionen */}
                <div className="flex items-center justify-end gap-1">
                  {!istIch && (
                    <button
                      onClick={() => handleDelete(u.user_id)}
                      disabled={busyId === u.user_id}
                      className="opacity-0 group-hover:opacity-100 text-[11px] text-red-400 hover:text-red-600 px-2 py-1 transition-opacity disabled:opacity-30"
                    >Löschen</button>
                  )}
                </div>
              </div>
            )
          })}

          <div className="flex items-center px-5 py-3 border-t border-slate-200">
            <span className="text-[12px] text-slate-400 tabular-nums">{users.length} Benutzer</span>
          </div>
        </div>
      )}
    </div>
  )
}
