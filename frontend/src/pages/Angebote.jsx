import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getProjekte, createProjekt, deleteProjekt, updateProjektStatus } from '../api/angebot'

const fmtEUR = n =>
  new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(n)

const ANG_NR = p =>
  `ANG-${new Date(p.erstellt_am).getFullYear()}-${String(p.id).padStart(4, '0')}`

const STATUS_META = {
  entwurf:   { label: 'Entwurf',   bg: '#fffbeb', color: '#b45309', border: '#fef3c7' },
  angeboten: { label: 'Angeboten', bg: '#eef2ff', color: '#4f46e5', border: '#e0e7ff' },
  abgelehnt: { label: 'Abgelehnt', bg: '#fef2f2', color: '#b91c1c', border: '#fecaca' },
}

const FILTER_TABS = [
  { key: 'alle',      label: 'Alle' },
  { key: 'entwurf',   label: 'Entwürfe' },
  { key: 'angeboten', label: 'Versendet' },
  { key: 'abgelehnt', label: 'Abgelehnt' },
]

function StatusPill({ status }) {
  const s = STATUS_META[status] || STATUS_META.entwurf
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', height: 22, padding: '0 9px',
      fontSize: 11.5, fontWeight: 600, borderRadius: 999,
      background: s.bg, color: s.color, border: `1px solid ${s.border}`, whiteSpace: 'nowrap',
    }}>{s.label}</span>
  )
}

// Rejection modal
function AblehnungModal({ onConfirm, onCancel }) {
  const [grund, setGrund] = useState('')
  return (
    <div className="fixed inset-0 bg-slate-900/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl border border-slate-200 w-full max-w-md p-6">
        <h3 className="text-[15px] font-semibold text-slate-900 mb-1">Angebot ablehnen</h3>
        <p className="text-[13px] text-slate-500 mb-4">
          Der Ablehnungsgrund wird für die spätere ML-Verbesserung gespeichert.
        </p>
        <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">
          Ablehnungsgrund (optional)
        </label>
        <textarea
          value={grund}
          onChange={e => setGrund(e.target.value)}
          rows={3}
          placeholder="z. B. Preis zu hoch, Vergabe an Mitbewerber, Projekt abgesagt …"
          className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-red-400/30 focus:border-red-400 resize-none"
          autoFocus
        />
        <div className="flex gap-2 mt-4 justify-end">
          <button
            onClick={onCancel}
            className="h-9 px-4 bg-white border border-slate-200 rounded-lg text-[13px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors"
          >
            Abbrechen
          </button>
          <button
            onClick={() => onConfirm(grund)}
            className="h-9 px-4 bg-red-600 hover:bg-red-700 text-white rounded-lg text-[13px] font-semibold transition-colors"
          >
            Als abgelehnt markieren
          </button>
        </div>
      </div>
    </div>
  )
}

export default function Angebote() {
  const [alle,      setAlle]      = useState([])
  const [loading,   setLoading]   = useState(true)
  const [tab,       setTab]       = useState('alle')
  const [search,    setSearch]    = useState('')
  const [nurMeine,  setNurMeine]  = useState(false)
  const [showForm,  setShowForm]  = useState(false)
  const [name,      setName]      = useState('')
  const [beschreibung, setBeschreibung] = useState('')
  const [kunde,     setKunde]     = useState('')
  const [saving,    setSaving]    = useState(false)
  const [actionId,  setActionId]  = useState(null)
  const [ablehnModal, setAblehnModal] = useState(null) // projekt_id
  const navigate = useNavigate()

  const load = () =>
    getProjekte(nurMeine)
      .then(ps => setAlle(ps.filter(p => p.name !== '__historisch__' && !p.ist_referenz)))
      .finally(() => setLoading(false))

  useEffect(() => { setLoading(true); load() }, [nurMeine])

  const angebote = alle.filter(p => ['entwurf', 'angeboten', 'abgelehnt'].includes(p.status))

  const visible = angebote
    .filter(p => tab === 'alle' || p.status === tab)
    .filter(p => !search ||
      p.name.toLowerCase().includes(search.toLowerCase()) ||
      p.kunde?.toLowerCase().includes(search.toLowerCase())
    )

  const handleCreate = async (e) => {
    e.preventDefault()
    if (!name.trim()) return
    setSaving(true)
    try {
      const neu = await createProjekt({ name: name.trim(), beschreibung: beschreibung.trim(), kunde: kunde.trim() })
      navigate(`/angebote/${neu.id}`)
    } finally { setSaving(false) }
  }

  const handleDelete = async (id) => {
    if (!confirm('Angebot und alle Positionen löschen?')) return
    await deleteProjekt(id)
    load()
  }

  const handleStatus = async (id, status, ablehnungsgrund = null) => {
    setActionId(id)
    try {
      await updateProjektStatus(id, { status, ablehnungsgrund })
      load()
    } finally { setActionId(null) }
  }

  const wert = (p) => {
    // Wert not returned from list API — just show 0 for now (detail page has it)
    return null
  }

  const COL = '2.2fr 1.4fr 120px 150px 1.6fr 240px 44px'

  return (
    <div className="p-8 pb-16">
      {/* Header */}
      <div className="flex items-end justify-between gap-4 mb-6">
        <div>
          <h1 className="text-[24px] font-bold tracking-tight text-slate-900 m-0">Angebote</h1>
          <p className="mt-1.5 text-[13.5px] text-slate-500">
            {angebote.length} Angebot{angebote.length !== 1 ? 'e' : ''} · Angebotspipeline und Kalkulation
          </p>
        </div>
        <button
          onClick={() => setShowForm(v => !v)}
          className="h-10 inline-flex items-center gap-2 px-4 bg-accent hover:bg-accent-hover text-white text-[13.5px] font-semibold rounded-lg transition-colors shadow-accent"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"/></svg>
          Neues Angebot
        </button>
      </div>

      {/* Create form */}
      {showForm && (
        <form onSubmit={handleCreate} className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs mb-5 flex flex-col gap-4">
          <h2 className="text-[14px] font-semibold text-slate-900">Angebot anlegen</h2>
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
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        {/* Status tabs */}
        <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-lg">
          {FILTER_TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`h-7 px-3 rounded-md text-[12.5px] font-medium transition-colors ${
                tab === t.key
                  ? 'bg-white text-slate-900 shadow-xs'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              {t.label}
              {t.key !== 'alle' && (
                <span className="ml-1.5 text-[10.5px] text-slate-400 tabular-nums">
                  {angebote.filter(p => p.status === t.key).length}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Search */}
        <div className="flex items-center gap-2 h-9 px-3 bg-white border border-slate-200 rounded-lg w-56">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" className="text-slate-400 flex-none">
            <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2"/>
            <path d="m20 20-3-3" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
          </svg>
          <input
            value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Angebot oder Kunde …"
            className="flex-1 text-[13px] bg-transparent outline-none text-slate-900 placeholder:text-slate-400"
          />
        </div>

        {/* Nur eigene Angebote */}
        <button
          type="button"
          onClick={() => setNurMeine(v => !v)}
          aria-pressed={nurMeine}
          className={`h-9 px-3 rounded-lg text-[12.5px] font-medium transition-colors inline-flex items-center gap-1.5 border ${
            nurMeine
              ? 'bg-accent/10 border-accent/30 text-accent'
              : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-50'
          }`}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="8" r="3.4" stroke="currentColor" strokeWidth="2"/>
            <path d="M5.5 20a6.5 6.5 0 0 1 13 0" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
          </svg>
          Nur meine
        </button>
      </div>

      {/* Table */}
      {loading ? (
        <div className="text-slate-400 text-center py-20 text-sm">Lade…</div>
      ) : visible.length === 0 ? (
        <div className="bg-white border border-slate-200 rounded-xl p-16 text-center shadow-xs">
          <p className="text-[15px] font-semibold text-slate-900 mb-1">
            {tab === 'alle' ? 'Noch keine Angebote' : `Keine Angebote mit Status "${FILTER_TABS.find(t=>t.key===tab)?.label}"`}
          </p>
          <p className="text-sm text-slate-500">Lege ein neues Angebot an und kalkuliere die Leistungspositionen.</p>
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
          {/* Head */}
          <div className="grid items-center px-5 py-2.5 bg-slate-50 border-b border-slate-200"
            style={{ gridTemplateColumns: COL }}>
            {['Angebot', 'Kunde', 'Status', 'Volumen', 'Beschreibung', 'Aktionen', ''].map(h => (
              <span key={h} className="text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-400">{h}</span>
            ))}
          </div>

          {visible.map((p) => (
            <div
              key={p.id}
              className="grid items-center px-5 py-3 border-t border-slate-100 hover:bg-slate-50/70 transition-colors group cursor-pointer"
              style={{ gridTemplateColumns: COL }}
              onClick={() => navigate(`/angebote/${p.id}`)}
            >
              {/* Angebot: name + ANG-Nr + Datum */}
              <div className="min-w-0 pr-4">
                <p className="text-[13.5px] font-semibold text-slate-900 truncate leading-snug">{p.name}</p>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-[11px] text-accent/70 font-semibold tabular-nums">{ANG_NR(p)}</span>
                  <span className="text-[10.5px] text-slate-300">·</span>
                  <span className="text-[10.5px] text-slate-400">{new Date(p.erstellt_am).toLocaleDateString('de-DE')}</span>
                </div>
              </div>

              {/* Kunde */}
              <div className="text-[13px] text-slate-700 truncate pr-3">{p.kunde || '–'}</div>

              {/* Status */}
              <div><StatusPill status={p.status} /></div>

              {/* Volumen */}
              <div>
                {p.soll_kosten > 0
                  ? <span className="text-[13px] font-semibold text-slate-900 tabular-nums">{fmtEUR(p.soll_kosten)}</span>
                  : <span className="text-[13px] text-slate-300">–</span>}
              </div>

              {/* Beschreibung */}
              <div className="text-[12px] text-slate-400 truncate pr-4 italic">{p.beschreibung || '–'}</div>

              {/* Actions */}
              <div className="flex items-center gap-1.5" onClick={e => e.stopPropagation()}>
                {p.darf_bearbeiten !== false && p.status === 'entwurf' && (
                  <button
                    onClick={() => handleStatus(p.id, 'angeboten')}
                    disabled={actionId === p.id}
                    className="h-7 px-2.5 bg-indigo-50 hover:bg-indigo-100 text-accent text-[11.5px] font-semibold rounded-lg border border-indigo-100 transition-colors disabled:opacity-50 whitespace-nowrap"
                  >Versenden →</button>
                )}
                {p.darf_bearbeiten !== false && p.status === 'angeboten' && (
                  <>
                    <button
                      onClick={() => handleStatus(p.id, 'beauftragt')}
                      disabled={actionId === p.id}
                      className="h-7 px-2.5 bg-emerald-50 hover:bg-emerald-100 text-emerald-700 text-[11.5px] font-semibold rounded-lg border border-emerald-100 transition-colors disabled:opacity-50 whitespace-nowrap"
                    >✓ Auftrag</button>
                    <button
                      onClick={() => setAblehnModal(p.id)}
                      disabled={actionId === p.id}
                      className="h-7 px-2.5 bg-red-50 hover:bg-red-100 text-red-600 text-[11.5px] font-semibold rounded-lg border border-red-100 transition-colors disabled:opacity-50 whitespace-nowrap"
                    >Ablehnen</button>
                  </>
                )}
                {p.darf_bearbeiten !== false && p.status === 'abgelehnt' && (
                  <button
                    onClick={() => handleStatus(p.id, 'entwurf')}
                    disabled={actionId === p.id}
                    className="h-7 px-2.5 bg-slate-50 hover:bg-slate-100 text-slate-600 text-[11.5px] font-semibold rounded-lg border border-slate-200 transition-colors disabled:opacity-50 whitespace-nowrap"
                  >Reaktivieren</button>
                )}
              </div>

              {/* Chevron + delete */}
              <div className="flex items-center justify-end gap-1" onClick={e => e.stopPropagation()}>
                {p.darf_bearbeiten !== false && (
                  <button
                    onClick={e => { e.stopPropagation(); handleDelete(p.id) }}
                    className="opacity-0 group-hover:opacity-100 text-[11px] text-red-400 hover:text-red-600 px-1 py-1 transition-opacity"
                    title="Löschen"
                  >✕</button>
                )}
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                  className="text-slate-300 group-hover:text-slate-400 transition-colors flex-none">
                  <path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </div>
            </div>
          ))}

          <div className="flex items-center justify-between px-5 py-3 border-t border-slate-200 bg-slate-50/50">
            <span className="text-[12px] text-slate-400 tabular-nums">
              {visible.length} Angebot{visible.length !== 1 ? 'e' : ''}
            </span>
          </div>
        </div>
      )}

      {/* Rejection modal */}
      {ablehnModal !== null && (
        <AblehnungModal
          onConfirm={async (grund) => {
            await handleStatus(ablehnModal, 'abgelehnt', grund || null)
            setAblehnModal(null)
          }}
          onCancel={() => setAblehnModal(null)}
        />
      )}
    </div>
  )
}
