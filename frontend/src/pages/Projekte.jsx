import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { getProjekte, createProjekt, deleteProjekt } from '../api/angebot'

const STATUS_PILL = {
  entwurf:       { label: 'Entwurf',       bg: '#fffbeb', color: '#b45309', border: '#fef3c7' },
  angeboten:     { label: 'Angeboten',     bg: '#eef2ff', color: '#4f46e5', border: '#e0e7ff' },
  beauftragt:    { label: 'Beauftragt',    bg: '#ecfdf5', color: '#047857', border: '#d1fae5' },
  abgeschlossen: { label: 'Abgeschlossen', bg: '#f8fafc', color: '#64748b', border: '#e2e8f0' },
}

function StatusPill({ status }) {
  const s = STATUS_PILL[status] || STATUS_PILL.entwurf
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', height: 22, padding: '0 9px',
      fontSize: 11.5, fontWeight: 600, borderRadius: 999,
      background: s.bg, color: s.color, border: `1px solid ${s.border}`, whiteSpace: 'nowrap',
    }}>
      {s.label}
    </span>
  )
}

export default function Projekte() {
  const [projekte,     setProjekte]     = useState([])
  const [loading,      setLoading]      = useState(true)
  const [showForm,     setShowForm]     = useState(false)
  const [name,         setName]         = useState('')
  const [beschreibung, setBeschreibung] = useState('')
  const [kunde,        setKunde]        = useState('')
  const [saving,       setSaving]       = useState(false)
  const [search,       setSearch]       = useState('')
  const navigate = useNavigate()

  const load = () => getProjekte().then(setProjekte).finally(() => setLoading(false))
  useEffect(() => { load() }, [])

  const handleCreate = async (e) => {
    e.preventDefault()
    if (!name.trim()) return
    setSaving(true)
    try {
      const neu = await createProjekt({ name: name.trim(), beschreibung: beschreibung.trim(), kunde: kunde.trim() })
      navigate(`/projekte/${neu.id}`)
    } finally { setSaving(false) }
  }

  const handleDelete = async (id) => {
    if (!confirm('Projekt und alle Positionen löschen?')) return
    await deleteProjekt(id)
    load()
  }

  const visible = projekte
    .filter(p => p.name !== '__historisch__' && !p.ist_referenz)
    .filter(p => !search || p.name.toLowerCase().includes(search.toLowerCase()) || p.kunde?.toLowerCase().includes(search.toLowerCase()))

  return (
    <div className="p-8 pb-16 max-w-[1360px]">
      {/* Page header */}
      <div className="flex items-end justify-between gap-4 mb-6">
        <div>
          <h1 className="text-[24px] font-bold tracking-tight text-slate-900 m-0">Projekte & Angebote</h1>
          <p className="mt-1.5 text-[13.5px] text-slate-500">
            {visible.length} Projekt{visible.length !== 1 ? 'e' : ''} · Leistungserfassung und Angebotskalkulation
          </p>
        </div>
        <button
          onClick={() => setShowForm(v => !v)}
          className="h-10 inline-flex items-center gap-2 px-4 bg-accent hover:bg-accent-hover text-white text-[13.5px] font-semibold rounded-lg transition-colors shadow-accent"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"/></svg>
          Neues Projekt
        </button>
      </div>

      {/* Create form */}
      {showForm && (
        <form onSubmit={handleCreate} className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs mb-5 flex flex-col gap-4">
          <h2 className="text-[14px] font-semibold text-slate-900">Projekt anlegen</h2>
          <div className="grid sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Projektname *</label>
              <input
                value={name} onChange={e => setName(e.target.value)} required
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"
              />
            </div>
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Kunde</label>
              <input
                value={kunde} onChange={e => setKunde(e.target.value)}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"
              />
            </div>
          </div>
          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Projektbeschreibung</label>
            <textarea
              value={beschreibung} onChange={e => setBeschreibung(e.target.value)} rows={2}
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent resize-none"
            />
            <p className="text-[11px] text-slate-400 mt-1">Wird für die Ähnlichkeitssuche nach Referenzprojekten genutzt.</p>
          </div>
          <div className="flex gap-2 justify-end">
            <button type="button" onClick={() => setShowForm(false)} className="h-9 px-4 bg-white border border-slate-200 rounded-lg text-sm font-semibold text-slate-700 hover:bg-slate-50 transition-colors">Abbrechen</button>
            <button type="submit" disabled={saving} className="h-9 px-4 bg-accent hover:bg-accent-hover text-white rounded-lg text-sm font-semibold transition-colors disabled:opacity-50">
              {saving ? 'Speichern…' : 'Anlegen'}
            </button>
          </div>
        </form>
      )}

      {/* Filter bar */}
      <div className="flex items-center gap-3 mb-4">
        <div className="flex items-center gap-2 h-9 px-3 bg-white border border-slate-200 rounded-lg w-64">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" className="text-slate-400 flex-none">
            <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2"/>
            <path d="m20 20-3-3" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
          </svg>
          <input
            value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Projekt oder Kunde …"
            className="flex-1 text-[13px] bg-transparent outline-none text-slate-900 placeholder:text-slate-400"
          />
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <div className="text-slate-400 text-center py-20 text-sm">Lade…</div>
      ) : visible.length === 0 ? (
        <div className="bg-white border border-slate-200 rounded-xl p-16 text-center shadow-xs">
          <p className="text-[15px] font-semibold text-slate-900 mb-1">Noch keine Projekte</p>
          <p className="text-sm text-slate-500">Lege dein erstes Projekt an oder importiere historische Daten.</p>
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
          {/* Table head */}
          <div className="grid gap-0 items-center px-5 py-2.5 bg-slate-50 border-b border-slate-200"
            style={{ gridTemplateColumns: '2fr 1.4fr 110px 1fr 40px' }}>
            {['Projekt', 'Kunde', 'Status', 'Beschreibung', ''].map(h => (
              <span key={h} className="text-[10.5px] font-semibold uppercase tracking-[0.04em] text-slate-400">{h}</span>
            ))}
          </div>

          {visible.map((p, i) => (
            <div
              key={p.id}
              className="grid items-center px-5 py-3.5 border-t border-slate-100 hover:bg-slate-50 transition-colors cursor-pointer group"
              style={{ gridTemplateColumns: '2fr 1.4fr 110px 1fr 40px' }}
              onClick={() => navigate(`/projekte/${p.id}`)}
            >
              <div className="min-w-0 pr-4">
                <div className="text-[13px] font-semibold text-slate-900 truncate">{p.name}</div>
                <div className="text-[11px] text-slate-400 mt-0.5">{new Date(p.erstellt_am).toLocaleDateString('de-DE')}</div>
              </div>
              <div className="text-[12.5px] text-slate-700 truncate pr-3">{p.kunde || '–'}</div>
              <div><StatusPill status={p.status} /></div>
              <div className="text-[12px] text-slate-500 truncate pr-4 italic">{p.beschreibung || '–'}</div>
              <div className="text-right flex items-center justify-end gap-2">
                <button
                  onClick={e => { e.stopPropagation(); handleDelete(p.id) }}
                  className="opacity-0 group-hover:opacity-100 text-[11px] text-red-400 hover:text-red-600 px-1.5 py-1 transition-opacity"
                >✕</button>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" className="text-slate-300 group-hover:text-slate-500 transition-colors">
                  <path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </div>
            </div>
          ))}

          {/* Footer */}
          <div className="flex items-center justify-between px-5 py-3 border-t border-slate-200">
            <span className="text-[12px] text-slate-400 tabular-nums">{visible.length} Projekt{visible.length !== 1 ? 'e' : ''}</span>
          </div>
        </div>
      )}
    </div>
  )
}
