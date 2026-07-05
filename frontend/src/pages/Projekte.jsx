import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getProjekte, createProjekt, deleteProjekt } from '../api/angebot'

const fmtEUR = n =>
  new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(n)

const fmtH = n => new Intl.NumberFormat('de-DE', { maximumFractionDigits: 0 }).format(n)

const STATUS_LABEL = {
  beauftragt:    { label: 'In Arbeit',     bg: '#f0fdfa', color: '#0f766e', border: '#99f6e4' },
  abgeschlossen: { label: 'Abgeschlossen', bg: '#f8fafc', color: '#475569', border: '#e2e8f0' },
}

const PRJ_NR = p =>
  `PRJ-${new Date(p.erstellt_am).getFullYear()}-${String(p.id).padStart(4, '0')}`

function StatusPill({ status }) {
  const s = STATUS_LABEL[status] || STATUS_LABEL.beauftragt
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

function Initials({ name }) {
  if (!name) return null
  const parts = name.trim().split(/\s+/)
  const ini = parts.length >= 2
    ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
    : name.slice(0, 2).toUpperCase()
  return (
    <span className="w-6 h-6 rounded-full bg-slate-200 text-slate-600 text-[10px] font-bold flex items-center justify-center flex-none select-none">
      {ini}
    </span>
  )
}

function IstFortschritt({ soll, ist }) {
  if (!soll) return <span className="text-[12px] text-slate-300">–</span>
  const pct      = Math.round((ist / soll) * 100)
  const overSoll = ist > soll
  const barPct   = Math.min(pct, 100)
  const barColor = overSoll ? '#d97706' : '#0f766e'
  return (
    <div className="flex items-center gap-2">
      <span className={`text-[12.5px] font-semibold tabular-nums w-12 text-right shrink-0 ${overSoll ? 'text-amber-600' : 'text-slate-700'}`}>
        {fmtH(ist)}
      </span>
      <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${barPct}%`, background: barColor }} />
      </div>
      <span className={`text-[11px] tabular-nums w-9 shrink-0 ${overSoll ? 'text-amber-600 font-semibold' : 'text-slate-500'}`}>
        {pct}%
      </span>
    </div>
  )
}

function MargePct({ auftragswert, ist_kosten, soll_kosten }) {
  if (!auftragswert) return <span className="text-[12.5px] text-slate-300">–</span>
  const kosten = ist_kosten > 0 ? ist_kosten : soll_kosten
  const marge  = (auftragswert - kosten) / auftragswert * 100
  const low    = marge < 20
  return (
    <span className={`text-[13px] font-semibold tabular-nums ${low ? 'text-amber-600' : 'text-emerald-700'}`}>
      {marge.toFixed(0)} %
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
                <option>Festpreis</option>
                <option>T&M</option>
                <option>Rahmenvertrag</option>
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
            <button type="button" onClick={onCancel} className="h-9 px-4 bg-white border border-slate-200 rounded-lg text-[13px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors">Abbrechen</button>
            <button type="submit" disabled={saving || !name.trim()} className="h-9 px-4 bg-accent hover:bg-accent-hover text-white rounded-lg text-[13px] font-semibold transition-colors disabled:opacity-50">
              {saving ? 'Anlegen…' : 'Anlegen'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function FilterSelect({ label, value, onChange, options }) {
  return (
    <div className="relative">
      <select value={value} onChange={e => onChange(e.target.value)}
        className="h-9 pl-3 pr-7 bg-white border border-slate-200 rounded-lg text-[12.5px] font-medium text-slate-700 appearance-none focus:outline-none focus:ring-2 focus:ring-accent/20 cursor-pointer">
        {options.map(([v, l]) => <option key={v} value={v}>{l === 'Alle' ? `${label}: Alle` : l}</option>)}
      </select>
      <svg className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-slate-400" width="12" height="12" viewBox="0 0 24 24" fill="none">
        <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
    </div>
  )
}

function PageBtn({ label, onClick, disabled, active }) {
  const isNum = !isNaN(parseInt(label))
  return (
    <button onClick={onClick} disabled={disabled}
      className={`h-7 min-w-[28px] px-2 rounded-md text-[12px] font-medium transition-colors disabled:opacity-40
        ${active ? 'bg-accent text-white' : 'text-slate-600 hover:bg-slate-100 bg-white border border-slate-200'}
        ${!isNum ? 'px-3' : ''}`}>
      {label}
    </button>
  )
}

const PAGE_SIZE = 10

export default function Projekte() {
  const [projekte,       setProjekte]       = useState([])
  const [loading,        setLoading]        = useState(true)
  const [search,         setSearch]         = useState('')
  const [filterStatus,   setFilterStatus]   = useState('alle')
  const [filterKunde,    setFilterKunde]    = useState('alle')
  const [filterLeitung,  setFilterLeitung]  = useState('alle')
  const [page,           setPage]           = useState(1)
  const [showModal,      setShowModal]      = useState(false)
  const navigate = useNavigate()

  const load = () =>
    getProjekte()
      .then(ps => setProjekte(
        ps.filter(p => p.name !== '__historisch__' && !p.ist_referenz && ['beauftragt', 'abgeschlossen'].includes(p.status))
      ))
      .finally(() => setLoading(false))

  useEffect(() => { load() }, [])

  const kunden    = [...new Set(projekte.map(p => p.kunde).filter(Boolean))].sort()
  const leitungen = [...new Set(projekte.map(p => p.leitung).filter(Boolean))].sort()
  const inArbeit  = projekte.filter(p => p.status === 'beauftragt').length

  const visible = projekte
    .filter(p => filterStatus  === 'alle' || p.status  === filterStatus)
    .filter(p => filterKunde   === 'alle' || p.kunde   === filterKunde)
    .filter(p => filterLeitung === 'alle' || p.leitung === filterLeitung)
    .filter(p => !search ||
      p.name.toLowerCase().includes(search.toLowerCase()) ||
      p.kunde?.toLowerCase().includes(search.toLowerCase()) ||
      p.leitung?.toLowerCase().includes(search.toLowerCase())
    )

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
    <div className="p-8 pb-16 max-w-[1360px]">
      {/* Header */}
      <div className="flex items-end justify-between gap-4 mb-5">
        <div>
          <h1 className="text-[24px] font-bold tracking-tight text-slate-900 m-0">Projekte</h1>
          <p className="mt-1 text-[13.5px] text-slate-500">
            {projekte.length} Projekt{projekte.length !== 1 ? 'e' : ''} · {inArbeit} in Arbeit · Soll/Ist-Vergleich über alle Mandate
          </p>
        </div>
        <button onClick={() => setShowModal(true)}
          className="h-10 inline-flex items-center gap-2 px-4 bg-accent hover:bg-accent-hover text-white text-[13.5px] font-semibold rounded-lg transition-colors shadow-accent">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"/></svg>
          Projekt anlegen
        </button>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <div className="flex items-center gap-2 h-9 px-3 bg-white border border-slate-200 rounded-lg w-56">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" className="text-slate-400 flex-none">
            <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2"/>
            <path d="m20 20-3-3" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
          </svg>
          <input value={search} onChange={e => { setSearch(e.target.value); setPage(1) }}
            placeholder="Projekt oder Kunde …"
            className="flex-1 text-[13px] bg-transparent outline-none text-slate-900 placeholder:text-slate-400" />
        </div>

        <FilterSelect label="Status" value={filterStatus} onChange={v => { setFilterStatus(v); setPage(1) }}
          options={[['alle','Alle'], ['beauftragt','In Arbeit'], ['abgeschlossen','Abgeschlossen']]} />
        <FilterSelect label="Kunde" value={filterKunde} onChange={v => { setFilterKunde(v); setPage(1) }}
          options={[['alle','Alle'], ...kunden.map(k => [k, k])]} />
        <FilterSelect label="Leitung" value={filterLeitung} onChange={v => { setFilterLeitung(v); setPage(1) }}
          options={[['alle','Alle'], ...leitungen.map(l => [l, l])]} />

        <div className="ml-auto">
          <button className="h-9 px-3 bg-white border border-slate-200 rounded-lg text-[12.5px] font-medium text-slate-600 hover:bg-slate-50 transition-colors inline-flex items-center gap-1.5">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
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
          <p className="text-sm text-slate-500">Projekte entstehen, wenn ein Angebot als beauftragt markiert wird, oder über "Projekt anlegen".</p>
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
          <div className="grid items-center px-5 py-2.5 bg-slate-50 border-b border-slate-200"
            style={{ gridTemplateColumns: '2fr 1.2fr 1.3fr 110px 80px 1.8fr 80px 36px' }}>
            {['Projekt', 'Kunde', 'Leitung', 'Status', 'Soll h', 'Istfortschritt', 'Marge', ''].map(h => (
              <span key={h} className="text-[10.5px] font-semibold uppercase tracking-[0.05em] text-slate-400">{h}</span>
            ))}
          </div>

          {pageItems.map((p) => (
            <div key={p.id}
              className="grid items-center px-5 py-3.5 border-t border-slate-100 hover:bg-slate-50/80 transition-colors cursor-pointer group"
              style={{ gridTemplateColumns: '2fr 1.2fr 1.3fr 110px 80px 1.8fr 80px 36px' }}
              onClick={() => navigate(`/projekte/${p.id}`)}>

              <div className="min-w-0 pr-4">
                <div className="text-[13px] font-semibold text-slate-900 truncate">{p.name}</div>
                <div className="text-[11px] text-accent/70 font-medium mt-0.5 tabular-nums">{PRJ_NR(p)}</div>
              </div>

              <div className="text-[12.5px] text-slate-700 truncate pr-3">{p.kunde || '–'}</div>

              <div className="flex items-center gap-1.5 pr-3 min-w-0">
                {p.leitung ? (
                  <>
                    <Initials name={p.leitung} />
                    <span className="text-[12.5px] text-slate-700 truncate">{p.leitung}</span>
                  </>
                ) : <span className="text-[12px] text-slate-300">–</span>}
              </div>

              <div><StatusPill status={p.status} /></div>

              <div>
                {p.soll_stunden_gesamt > 0
                  ? <span className="text-[13px] font-medium text-slate-800 tabular-nums">{fmtH(p.soll_stunden_gesamt)}</span>
                  : <span className="text-[12px] text-slate-300">–</span>}
              </div>

              <div className="pr-3">
                <IstFortschritt soll={p.soll_stunden_gesamt} ist={p.ist_stunden_gesamt} />
              </div>

              <div>
                <MargePct auftragswert={p.auftragswert} ist_kosten={p.ist_kosten} soll_kosten={p.soll_kosten} />
              </div>

              <div className="flex items-center justify-end">
                <button onClick={e => handleDelete(e, p.id)}
                  className="opacity-0 group-hover:opacity-100 text-[11px] text-red-400 hover:text-red-600 px-1 py-1 transition-opacity">✕</button>
              </div>
            </div>
          ))}

          <div className="flex items-center justify-between px-5 py-3 border-t border-slate-200 bg-slate-50/50">
            <span className="text-[12px] text-slate-400 tabular-nums">
              {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, visible.length)} von {visible.length} Projekten
            </span>
            {totalPages > 1 && (
              <div className="flex items-center gap-1">
                <PageBtn label="Zurück" onClick={() => goPage(page - 1)} disabled={page === 1} />
                {Array.from({ length: totalPages }, (_, i) => i + 1).map(n => (
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
