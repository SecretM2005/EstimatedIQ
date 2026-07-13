import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getProjekte, createProjekt, deleteProjekt } from '../api/angebot'

const fmtH = n => new Intl.NumberFormat('de-DE', { maximumFractionDigits: 0 }).format(n)

const STATUS_CFG = {
  beauftragt:    { label: 'In Arbeit',     bg: '#f0fdfa', color: '#0f766e', border: '#99f6e4' },
  abgeschlossen: { label: 'Abgeschlossen', bg: '#1e293b', color: '#f8fafc', border: '#1e293b' },
}

const PRJ_NR = p =>
  `PRJ-${new Date(p.erstellt_am).getFullYear()}-${String(p.id).padStart(4, '0')}`

function StatusPill({ status }) {
  const s = STATUS_CFG[status] || STATUS_CFG.beauftragt
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', height: 22, padding: '0 10px',
      fontSize: 11.5, fontWeight: 600, borderRadius: 999,
      background: s.bg, color: s.color, border: `1px solid ${s.border}`, whiteSpace: 'nowrap',
    }}>
      {s.label}
    </span>
  )
}

// Avatar with hash-based color per person
const AVATAR_COLORS = [
  { bg: '#dbeafe', text: '#1d4ed8' },
  { bg: '#d1fae5', text: '#065f46' },
  { bg: '#ede9fe', text: '#6d28d9' },
  { bg: '#fce7f3', text: '#9d174d' },
  { bg: '#fef3c7', text: '#92400e' },
  { bg: '#e0f2fe', text: '#0369a1' },
]
function Initials({ name }) {
  if (!name) return <span className="text-[12px] text-slate-300">–</span>
  const parts = name.trim().split(/\s+/)
  const ini = ((parts[0]?.[0] || '') + (parts[parts.length - 1]?.[0] || '')).toUpperCase()
  const idx = (ini.charCodeAt(0) + (ini.charCodeAt(1) || 0)) % AVATAR_COLORS.length
  const { bg, text } = AVATAR_COLORS[idx]
  return (
    <span className="w-6 h-6 rounded-full text-[10px] font-bold flex items-center justify-center flex-none select-none"
      style={{ background: bg, color: text }}>
      {ini}
    </span>
  )
}

function IstFortschritt({ soll, ist }) {
  if (!soll) {
    return (
      <div className="min-w-0">
        <span className="text-[13px] text-slate-300 tabular-nums font-bold">–</span>
        <div className="h-1.5 bg-slate-100 rounded-full mt-1.5 mb-1 overflow-hidden">
          <div className="h-full w-[2%] bg-slate-200 rounded-full" />
        </div>
        <span className="text-[10.5px] text-slate-300">– · Kalkulation</span>
      </div>
    )
  }
  const pct   = Math.round((ist / soll) * 100)
  const over  = pct > 100
  const color = over ? '#d97706' : '#0f766e'
  return (
    <div className="min-w-0">
      <span className={`text-[13px] font-bold tabular-nums ${over ? 'text-amber-600' : 'text-slate-800'}`}>
        {fmtH(ist)}
      </span>
      <div className="h-1.5 bg-slate-100 rounded-full mt-1.5 mb-1 overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(pct, 100)}%`, background: color }} />
      </div>
      <span className={`text-[10.5px] tabular-nums ${over ? 'text-amber-600 font-semibold' : 'text-slate-400'}`}>
        {pct} %
      </span>
    </div>
  )
}

function MargePct({ auftragswert, ist_kosten, soll_kosten }) {
  if (!auftragswert) return <span className="text-[13px] text-slate-300">–</span>
  const kosten = ist_kosten > 0 ? ist_kosten : soll_kosten
  const marge  = (auftragswert - kosten) / auftragswert * 100
  const cls    = marge < 25 ? 'text-amber-600' : marge >= 30 ? 'text-teal-700' : 'text-slate-700'
  return (
    <span className={`text-[13px] font-semibold tabular-nums ${cls}`}>
      {Math.round(marge)} %
    </span>
  )
}

function NeuesProjektModal({ onSave, onCancel }) {
  const [name,    setName]    = useState('')
  const [kunde,   setKunde]   = useState('')
  const [leitung, setLeitung] = useState('')
  const [auftrag, setAuftrag] = useState('')
  const [abr,     setAbr]     = useState('Festpreis')
  const [start,   setStart]   = useState('')
  const [end,     setEnd]     = useState('')
  const [saving,  setSaving]  = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!name.trim()) return
    setSaving(true)
    try {
      await onSave({
        name: name.trim(), kunde: kunde.trim(), leitung: leitung.trim(),
        auftragswert: auftrag ? parseFloat(auftrag) : null,
        abrechnung_typ: abr, laufzeit_start: start, laufzeit_end: end,
      })
    } finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 bg-slate-900/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl border border-slate-200 w-full max-w-lg p-6">
        <h3 className="text-[15px] font-semibold text-slate-900 mb-4">Projekt anlegen</h3>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1">Projektname *</label>
              <input value={name} onChange={e => setName(e.target.value)} required
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
            </div>
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1">Kunde</label>
              <input value={kunde} onChange={e => setKunde(e.target.value)}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
            </div>
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1">Projektleitung</label>
              <input value={leitung} onChange={e => setLeitung(e.target.value)} placeholder="Vor- und Nachname"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
            </div>
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1">Auftragswert (€)</label>
              <input type="number" value={auftrag} onChange={e => setAuftrag(e.target.value)} min="0" step="1000" placeholder="z. B. 120000"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
            </div>
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1">Abrechnung</label>
              <select value={abr} onChange={e => setAbr(e.target.value)}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] bg-white focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent">
                <option>Festpreis</option><option>T&amp;M</option><option>Rahmenvertrag</option>
              </select>
            </div>
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1">Laufzeit Start</label>
              <input type="month" value={start} onChange={e => setStart(e.target.value)}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
            </div>
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1">Laufzeit Ende</label>
              <input type="month" value={end} onChange={e => setEnd(e.target.value)}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
            </div>
          </div>
          <div className="flex gap-2 justify-end mt-2">
            <button type="button" onClick={onCancel}
              className="h-9 px-4 bg-white border border-slate-200 rounded-lg text-[13px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors">
              Abbrechen
            </button>
            <button type="submit" disabled={saving || !name.trim()}
              className="h-9 px-4 bg-accent hover:bg-accent-hover text-white rounded-lg text-[13px] font-semibold transition-colors disabled:opacity-50">
              {saving ? 'Anlegen…' : 'Anlegen'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function Dropdown({ prefix, value, onChange, options }) {
  return (
    <div className="relative">
      <select value={value} onChange={e => onChange(e.target.value)}
        className="h-9 pl-3 pr-8 bg-white border border-slate-200 rounded-lg text-[12.5px] font-medium text-slate-700 appearance-none focus:outline-none focus:ring-2 focus:ring-accent/20 cursor-pointer">
        {options.map(([v, l]) => (
          <option key={v} value={v}>{l === 'Alle' ? `${prefix}: Alle` : l}</option>
        ))}
      </select>
      <svg className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400" width="11" height="11" viewBox="0 0 24 24" fill="none">
        <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
    </div>
  )
}

function PageBtn({ label, onClick, disabled, active }) {
  return (
    <button onClick={onClick} disabled={disabled}
      className={`h-8 min-w-[32px] px-2.5 rounded-lg text-[12.5px] font-medium transition-colors disabled:opacity-40
        ${active
          ? 'bg-slate-900 text-white'
          : 'text-slate-600 hover:bg-slate-100 bg-white border border-slate-200'
        }`}>
      {label}
    </button>
  )
}

const PAGE_SIZE = 9

const COL = '2.2fr 1.4fr 1.5fr 130px 80px 2.2fr 80px 44px'

export default function Projekte() {
  const [projekte,      setProjekte]      = useState([])
  const [loading,       setLoading]       = useState(true)
  const [search,        setSearch]        = useState('')
  const [filterStatus,  setFilterStatus]  = useState('alle')
  const [filterKunde,   setFilterKunde]   = useState('alle')
  const [filterLeitung, setFilterLeitung] = useState('alle')
  const [filterJahr,    setFilterJahr]    = useState('alle')
  const [nurMeine,      setNurMeine]      = useState(false)
  const [page,          setPage]          = useState(1)
  const [showModal,     setShowModal]     = useState(false)
  const navigate = useNavigate()

  const load = () =>
    getProjekte(nurMeine)
      .then(ps => setProjekte(
        ps.filter(p => p.name !== '__historisch__' && !p.ist_referenz && ['beauftragt', 'abgeschlossen'].includes(p.status))
      ))
      .finally(() => setLoading(false))

  useEffect(() => { setLoading(true); load() }, [nurMeine])

  const kunden    = [...new Set(projekte.map(p => p.kunde).filter(Boolean))].sort()
  const leitungen = [...new Set(projekte.map(p => p.leitung).filter(Boolean))].sort()
  const jahre     = [...new Set(projekte.map(p => new Date(p.erstellt_am).getFullYear()))].sort((a, b) => b - a)
  const inArbeit  = projekte.filter(p => p.status === 'beauftragt').length

  const visible = projekte
    .filter(p => filterStatus  === 'alle' || p.status  === filterStatus)
    .filter(p => filterKunde   === 'alle' || p.kunde   === filterKunde)
    .filter(p => filterLeitung === 'alle' || p.leitung === filterLeitung)
    .filter(p => filterJahr    === 'alle' || String(new Date(p.erstellt_am).getFullYear()) === filterJahr)
    .filter(p => {
      if (!search) return true
      const q = search.toLowerCase()
      return p.name.toLowerCase().includes(q) ||
        p.kunde?.toLowerCase().includes(q) ||
        p.leitung?.toLowerCase().includes(q) ||
        PRJ_NR(p).toLowerCase().includes(q)
    })

  const totalPages = Math.max(1, Math.ceil(visible.length / PAGE_SIZE))
  const pageItems  = visible.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
  const goPage     = n => setPage(Math.max(1, Math.min(totalPages, n)))

  const handleCreate = async (body) => {
    const neu = await createProjekt({ ...body, status: 'beauftragt' })
    setShowModal(false)
    navigate(`/projekte/${neu.id}`)
  }

  const handleDelete = async (e, id) => {
    e.stopPropagation()
    if (!confirm('Projekt und alle Positionen löschen?')) return
    await deleteProjekt(id)
    load()
  }

  return (
    <div className="p-8 pb-16">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 mb-5">
        <div>
          <h1 className="text-[24px] font-bold tracking-tight text-slate-900 m-0">Projekte</h1>
          <p className="mt-1 text-[13.5px] text-slate-500">
            {projekte.length} Projekt{projekte.length !== 1 ? 'e' : ''} · {inArbeit} in Arbeit · Soll/Ist-Vergleich über alle Mandate
          </p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="h-10 inline-flex items-center gap-2 px-4 bg-accent hover:bg-accent-hover text-white text-[13.5px] font-semibold rounded-lg transition-colors shadow-accent"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"/>
          </svg>
          Projekt anlegen
        </button>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-2 mb-5 flex-wrap">
        {/* Search */}
        <div className="flex items-center gap-2 h-9 px-3 bg-white border border-slate-200 rounded-lg w-60">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" className="text-slate-400 flex-none">
            <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2"/>
            <path d="m20 20-3-3" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
          </svg>
          <input
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1) }}
            placeholder="Projekt oder Kunde …"
            className="flex-1 text-[13px] bg-transparent outline-none text-slate-900 placeholder:text-slate-400"
          />
        </div>

        <Dropdown prefix="Status" value={filterStatus} onChange={v => { setFilterStatus(v); setPage(1) }}
          options={[['alle','Alle'], ['beauftragt','In Arbeit'], ['abgeschlossen','Abgeschlossen']]} />

        <Dropdown prefix="Kunde" value={filterKunde} onChange={v => { setFilterKunde(v); setPage(1) }}
          options={[['alle','Alle'], ...kunden.map(k => [k, k])]} />

        <Dropdown prefix="Leitung" value={filterLeitung} onChange={v => { setFilterLeitung(v); setPage(1) }}
          options={[['alle','Alle'], ...leitungen.map(l => [l, l])]} />

        <Dropdown prefix="GJ" value={filterJahr} onChange={v => { setFilterJahr(v); setPage(1) }}
          options={[['alle','Alle'], ...jahre.map(y => [String(y), `GJ ${y}`])]} />

        {/* Nur eigene Projekte */}
        <button
          type="button"
          onClick={() => { setNurMeine(v => !v); setPage(1) }}
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

        <div className="ml-auto">
          <button className="h-9 px-3 bg-white border border-slate-200 rounded-lg text-[12.5px] font-medium text-slate-500 hover:bg-slate-50 transition-colors inline-flex items-center gap-1.5">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
              <path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            Export
          </button>
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <div className="text-slate-400 text-center py-20 text-sm">Lade…</div>
      ) : visible.length === 0 ? (
        <div className="bg-white border border-slate-200 rounded-xl p-16 text-center shadow-xs">
          <p className="text-[15px] font-semibold text-slate-900 mb-1">Keine Projekte</p>
          <p className="text-sm text-slate-500">
            {projekte.length === 0
              ? 'Projekte entstehen, wenn ein Angebot beauftragt wird, oder über "Projekt anlegen".'
              : 'Keine Treffer für die gewählten Filter.'}
          </p>
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
          {/* Column headers */}
          <div className="grid items-center px-5 py-2.5 bg-slate-50 border-b border-slate-200"
            style={{ gridTemplateColumns: COL }}>
            {['Projekt', 'Kunde', 'Leitung', 'Status', 'Soll', 'Istfortschritt', 'Marge', ''].map(h => (
              <span key={h} className="text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-400">{h}</span>
            ))}
          </div>

          {/* Rows */}
          {pageItems.map(p => (
            <div
              key={p.id}
              onClick={() => navigate(`/projekte/${p.id}`)}
              className="grid items-center px-5 py-3 border-t border-slate-100 hover:bg-slate-50/70 transition-colors cursor-pointer group"
              style={{ gridTemplateColumns: COL }}
            >
              {/* Projekt */}
              <div className="min-w-0 pr-4">
                <p className="text-[13.5px] font-semibold text-slate-900 truncate leading-snug">{p.name}</p>
                <p className="text-[11px] text-accent/70 font-semibold mt-0.5 tabular-nums">{PRJ_NR(p)}</p>
              </div>

              {/* Kunde */}
              <div className="min-w-0 pr-3">
                <p className="text-[13px] text-slate-700 truncate">{p.kunde || '–'}</p>
              </div>

              {/* Leitung */}
              <div className="flex items-center gap-1.5 pr-3 min-w-0">
                <Initials name={p.leitung} />
                {p.leitung && (
                  <span className="text-[12.5px] text-slate-700 truncate">{p.leitung}</span>
                )}
              </div>

              {/* Status */}
              <div>
                <StatusPill status={p.status} />
              </div>

              {/* Soll */}
              <div>
                {p.soll_stunden_gesamt > 0
                  ? <span className="text-[13px] font-medium text-slate-800 tabular-nums">{fmtH(p.soll_stunden_gesamt)}</span>
                  : <span className="text-[13px] text-slate-300">–</span>}
              </div>

              {/* Istfortschritt */}
              <div className="pr-4">
                <IstFortschritt soll={p.soll_stunden_gesamt} ist={p.ist_stunden_gesamt} />
              </div>

              {/* Marge */}
              <div>
                <MargePct auftragswert={p.auftragswert} ist_kosten={p.ist_kosten} soll_kosten={p.soll_kosten} />
              </div>

              {/* Chevron / delete */}
              <div className="flex items-center justify-end">
                {p.darf_bearbeiten !== false && (
                  <button
                    onClick={e => handleDelete(e, p.id)}
                    className="opacity-0 group-hover:opacity-100 text-[11px] text-red-400 hover:text-red-600 px-1 py-1 mr-1 transition-opacity"
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

          {/* Footer: range + pagination */}
          <div className="flex items-center justify-between px-5 py-3 border-t border-slate-200 bg-slate-50/50">
            <span className="text-[12px] text-slate-400 tabular-nums">
              {visible.length === 0
                ? '0 Projekte'
                : `${(page - 1) * PAGE_SIZE + 1}–${Math.min(page * PAGE_SIZE, visible.length)} von ${visible.length} Projekten`}
            </span>
            {totalPages > 1 && (
              <div className="flex items-center gap-1">
                <PageBtn label="Zurück" onClick={() => goPage(page - 1)} disabled={page === 1} />
                {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                  // Show pages around current
                  let n
                  if (totalPages <= 7) n = i + 1
                  else if (page <= 4) n = i + 1
                  else if (page >= totalPages - 3) n = totalPages - 6 + i
                  else n = page - 3 + i
                  return n
                }).filter((n, _, arr) => n >= 1 && n <= totalPages && arr.indexOf(n) === arr.lastIndexOf(n))
                  .map(n => (
                    <PageBtn key={n} label={String(n)} onClick={() => goPage(n)} active={n === page} />
                  ))}
                <PageBtn label="Weiter" onClick={() => goPage(page + 1)} disabled={page === totalPages} />
              </div>
            )}
          </div>
        </div>
      )}

      {showModal && (
        <NeuesProjektModal onSave={handleCreate} onCancel={() => setShowModal(false)} />
      )}
    </div>
  )
}
