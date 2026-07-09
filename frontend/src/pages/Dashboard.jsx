import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getDashboardStats, getProjekte } from '../api/angebot'

const fmtEUR = n =>
  new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(n)
const fmtK = n =>
  n === 0 ? '–' : n >= 1000 ? `€${Math.round(n / 1000)}k` : fmtEUR(n)
const fmtH = n =>
  new Intl.NumberFormat('de-DE', { maximumFractionDigits: 0 }).format(n)

const ANG_NR = p =>
  `ANG-${new Date(p.erstellt_am).getFullYear()}-${String(p.id).padStart(4, '0')}`

const STATUS_CFG = {
  entwurf:       { label: 'Entwurf',    bg: '#fffbeb', color: '#b45309', border: '#fef3c7', dot: '#f59e0b' },
  angeboten:     { label: 'Angeboten',  bg: '#eef2ff', color: '#4f46e5', border: '#e0e7ff', dot: '#6366f1' },
  beauftragt:    { label: 'In Arbeit',  bg: '#f0fdfa', color: '#0f766e', border: '#99f6e4', dot: '#0f766e' },
  abgeschlossen: { label: 'Abgeschl.',  bg: '#f8fafc', color: '#64748b', border: '#e2e8f0', dot: '#94a3b8' },
  abgelehnt:     { label: 'Abgelehnt', bg: '#fef2f2', color: '#b91c1c', border: '#fecaca', dot: '#ef4444' },
}

function StatusPill({ status }) {
  const s = STATUS_CFG[status] || STATUS_CFG.entwurf
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', height: 20, padding: '0 8px',
      fontSize: 11, fontWeight: 600, borderRadius: 999,
      background: s.bg, color: s.color, border: `1px solid ${s.border}`, whiteSpace: 'nowrap',
    }}>{s.label}</span>
  )
}

function Sparkline({ color = '#6366f1', points = '0 28 18 22 36 16 54 10 72 8 90 4' }) {
  return (
    <svg width="90" height="36" viewBox="0 0 90 36" fill="none" style={{ opacity: 0.55 }}>
      <polyline points={points} stroke={color} strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  )
}

function relDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const diffDays = Math.floor((Date.now() - d) / 86400000)
  const t = d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })
  if (diffDays === 0) return `Heute, ${t}`
  if (diffDays === 1) return `Gestern, ${t}`
  return `${d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' })}, ${t}`
}

function activityLabel(p) {
  const ang = ANG_NR(p)
  const k = p.kunde
  switch (p.status) {
    case 'entwurf':       return `Angebot ${ang} (${k}) wurde angelegt.`
    case 'angeboten':     return `Angebot ${ang} (${k}) wurde an den Kunden versendet.`
    case 'beauftragt':    return `Angebot ${ang} (${k}) wurde vom Kunden angenommen.`
    case 'abgelehnt':     return `Angebot ${ang} (${k}) wurde abgelehnt.`
    case 'abgeschlossen': return `Projekt ${ang} (${k}) wurde abgeschlossen.`
    default:              return `${ang} wurde aktualisiert.`
  }
}

export default function Dashboard() {
  const [stats, setStats]               = useState(null)
  const [alleProjekte, setAlleProjekte] = useState([])
  const [loading, setLoading]           = useState(true)

  useEffect(() => {
    Promise.all([getDashboardStats(), getProjekte()])
      .then(([s, ps]) => {
        setStats(s)
        setAlleProjekte(ps.filter(p => p.name !== '__historisch__' && !p.ist_referenz))
      })
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="p-8 text-slate-400 text-sm">Lade…</div>

  // Subsets
  const offeneAngebote   = alleProjekte.filter(p => ['entwurf', 'angeboten'].includes(p.status))
  const laufendeProjekte = alleProjekte.filter(p => p.status === 'beauftragt')
  const abgeschlossene   = alleProjekte.filter(p => p.status === 'abgeschlossen')
  const abgelehnte       = alleProjekte.filter(p => p.status === 'abgelehnt')

  // Pipeline EUR by stage
  const wertEntwurf   = alleProjekte.filter(p => p.status === 'entwurf').reduce((s, p) => s + p.soll_kosten, 0)
  const wertAngeboten = alleProjekte.filter(p => p.status === 'angeboten').reduce((s, p) => s + p.soll_kosten, 0)
  const wertOffen     = wertEntwurf + wertAngeboten
  const maxW          = Math.max(wertEntwurf, wertAngeboten, 1)

  // KPIs
  const n_gewonnen   = laufendeProjekte.length + abgeschlossene.length
  const n_verloren   = abgelehnte.length
  const gewinnrate   = stats.gewinnrate

  const soll_h = laufendeProjekte.reduce((s, p) => s + p.soll_stunden_gesamt, 0)
  const ist_h  = laufendeProjekte.reduce((s, p) => s + p.ist_stunden_gesamt,  0)
  const ist_vs_soll_pct = soll_h > 0 ? (ist_h / soll_h * 100) : null
  const n_ueber_soll    = laufendeProjekte.filter(p => p.soll_stunden_gesamt > 0 && p.ist_stunden_gesamt > p.soll_stunden_gesamt).length

  const margenPs  = laufendeProjekte.filter(p => p.auftragswert > 0 && p.soll_kosten > 0)
  const avg_marge = margenPs.length > 0
    ? margenPs.reduce((s, p) => s + (p.auftragswert - p.soll_kosten) / p.auftragswert * 100, 0) / margenPs.length
    : null

  const heute = new Date().toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' })

  return (
    <div className="p-8 pb-16">

      {/* ── Header ── */}
      <div className="flex items-start justify-between mb-7">
        <div>
          <h1 className="text-[24px] font-bold tracking-tight text-slate-900 m-0">Dashboard</h1>
          <p className="mt-1 text-[13px] text-slate-400">
            Stand {heute} · Kennzahlen für das laufende Geschäftsjahr
          </p>
        </div>
        <Link
          to="/angebote"
          className="h-10 inline-flex items-center gap-2 px-4 bg-accent hover:bg-accent-hover text-white text-[13.5px] font-semibold rounded-lg transition-colors shadow-accent"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"/>
          </svg>
          Neues Angebot
        </Link>
      </div>

      {/* ── KPI cards ── */}
      <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
        {/* Offene Angebote */}
        <div className="bg-white border border-slate-200 rounded-xl px-5 py-4 shadow-xs">
          <p className="text-[10.5px] font-semibold uppercase tracking-[0.06em] text-slate-400 mb-3">Offene Angebote</p>
          <div className="flex items-end justify-between gap-2">
            <div>
              <p className="text-[30px] font-bold text-slate-900 leading-none tabular-nums">{offeneAngebote.length}</p>
              <p className="text-[12px] text-slate-400 mt-1.5">{fmtEUR(wertOffen)} offen</p>
            </div>
            <Sparkline color="#6366f1" />
          </div>
        </div>

        {/* Trefferquote */}
        <div className="bg-white border border-slate-200 rounded-xl px-5 py-4 shadow-xs">
          <p className="text-[10.5px] font-semibold uppercase tracking-[0.06em] text-slate-400 mb-3">Trefferquote</p>
          <div className="flex items-end justify-between gap-2">
            <div>
              <p className="text-[30px] font-bold text-slate-900 leading-none tabular-nums">
                {gewinnrate != null ? `${Math.round(gewinnrate * 100)} %` : '–'}
              </p>
              <p className="text-[12px] text-slate-400 mt-1.5">{n_gewonnen} gew. · {n_verloren} verl.</p>
            </div>
            <Sparkline color="#10b981" points="0 28 18 24 36 20 54 14 72 10 90 6" />
          </div>
        </div>

        {/* Ø Marge Laufend */}
        <div className="bg-white border border-slate-200 rounded-xl px-5 py-4 shadow-xs">
          <p className="text-[10.5px] font-semibold uppercase tracking-[0.06em] text-slate-400 mb-3">Ø Marge Laufend</p>
          <div className="flex items-end justify-between gap-2">
            <div>
              <p className="text-[30px] font-bold text-slate-900 leading-none tabular-nums">
                {avg_marge != null ? `${avg_marge.toFixed(1)} %` : '–'}
              </p>
              <p className="text-[12px] text-slate-400 mt-1.5">
                {margenPs.length > 0 ? `${margenPs.length} Projekte mit Wert` : 'Kein Auftragswert'}
              </p>
            </div>
            <Sparkline color="#0f766e" points="0 30 18 26 36 22 54 18 72 14 90 10" />
          </div>
        </div>

        {/* Ist vs. Soll */}
        <div className="bg-white border border-slate-200 rounded-xl px-5 py-4 shadow-xs">
          <p className="text-[10.5px] font-semibold uppercase tracking-[0.06em] text-slate-400 mb-3">Ist vs. Soll (Std)</p>
          <div className="flex items-end justify-between gap-2">
            <div>
              <p className={`text-[30px] font-bold leading-none tabular-nums ${
                ist_vs_soll_pct != null && ist_vs_soll_pct > 100 ? 'text-amber-600' : 'text-slate-900'
              }`}>
                {ist_vs_soll_pct != null ? `${Math.round(ist_vs_soll_pct)} %` : '–'}
              </p>
              <p className="text-[12px] text-slate-400 mt-1.5">
                {n_ueber_soll > 0
                  ? `${n_ueber_soll} Projekt${n_ueber_soll !== 1 ? 'e' : ''} über Soll`
                  : laufendeProjekte.length > 0 ? 'Alle im Soll' : 'Keine laufenden Projekte'}
              </p>
            </div>
            <Sparkline
              color={ist_vs_soll_pct != null && ist_vs_soll_pct > 100 ? '#f59e0b' : '#6366f1'}
              points={ist_vs_soll_pct != null && ist_vs_soll_pct > 100
                ? '0 4 18 8 36 12 54 18 72 22 90 28'
                : '0 28 18 22 36 16 54 10 72 8 90 4'}
            />
          </div>
        </div>
      </div>

      {/* ── Main grid ── */}
      <div className="grid xl:grid-cols-[1fr_340px] gap-5">

        {/* LEFT: tables */}
        <div className="flex flex-col gap-5">

          {/* Offene Angebote */}
          <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-100">
              <div className="flex items-center gap-2.5">
                <h2 className="text-[13.5px] font-semibold text-slate-900">Offene Angebote</h2>
                {offeneAngebote.length > 0 && (
                  <span className="text-[11px] font-semibold bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full tabular-nums">
                    {offeneAngebote.length} aktiv
                  </span>
                )}
              </div>
              <Link to="/angebote" className="text-[12px] text-accent hover:text-accent-hover font-medium transition-colors">
                Alle ansehen →
              </Link>
            </div>

            {offeneAngebote.length === 0 ? (
              <div className="px-5 py-8 text-center">
                <p className="text-[13px] text-slate-400">Noch keine offenen Angebote</p>
                <Link to="/angebote"
                  className="inline-flex mt-3 h-8 px-3 bg-accent hover:bg-accent-hover text-white text-[12px] font-semibold rounded-lg items-center gap-1.5 transition-colors">
                  Erstes Angebot erstellen
                </Link>
              </div>
            ) : (
              <>
                {/* Column headers */}
                <div className="grid px-5 py-2 bg-slate-50 border-b border-slate-100"
                  style={{ gridTemplateColumns: '172px 1fr 130px 108px' }}>
                  {['Nummer / Kunde', 'Titel', 'Volumen', 'Status'].map(h => (
                    <span key={h} className="text-[10px] font-semibold uppercase tracking-[0.05em] text-slate-400">{h}</span>
                  ))}
                </div>
                {offeneAngebote.slice(0, 8).map(p => (
                  <Link key={p.id} to={`/angebote/${p.id}`}
                    className="grid px-5 py-2.5 border-t border-slate-100 hover:bg-slate-50 transition-colors items-center"
                    style={{ gridTemplateColumns: '172px 1fr 130px 108px' }}>
                    <div className="min-w-0 pr-3">
                      <p className="text-[11.5px] font-semibold text-slate-700 tabular-nums">{ANG_NR(p)}</p>
                      <p className="text-[11px] text-slate-400 truncate">{p.kunde}</p>
                    </div>
                    <div className="min-w-0 pr-3">
                      <p className="text-[13px] font-medium text-slate-900 truncate">{p.name}</p>
                    </div>
                    <div>
                      <p className="text-[13px] font-semibold text-slate-900 tabular-nums">
                        {p.soll_kosten > 0 ? fmtEUR(p.soll_kosten) : '–'}
                      </p>
                    </div>
                    <div>
                      <StatusPill status={p.status} />
                    </div>
                  </Link>
                ))}
                {offeneAngebote.length > 8 && (
                  <div className="px-5 py-2.5 border-t border-slate-100">
                    <Link to="/angebote" className="text-[12px] text-slate-400 hover:text-accent transition-colors">
                      + {offeneAngebote.length - 8} weitere anzeigen
                    </Link>
                  </div>
                )}
              </>
            )}
          </div>

          {/* Laufende Projekte — Soll / Ist */}
          <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-100">
              <h2 className="text-[13.5px] font-semibold text-slate-900">Laufende Projekte — Soll / Ist</h2>
              <Link to="/projekte" className="text-[12px] text-accent hover:text-accent-hover font-medium transition-colors">
                Zur Übersicht →
              </Link>
            </div>

            {laufendeProjekte.length === 0 ? (
              <div className="px-5 py-8 text-center">
                <p className="text-[13px] text-slate-400">Noch keine laufenden Projekte</p>
                <p className="text-[12px] text-slate-400 mt-1">Angebote erscheinen hier nach Auftragserteilung.</p>
              </div>
            ) : (
              <div>
                {laufendeProjekte.slice(0, 6).map(p => {
                  const pct = p.soll_stunden_gesamt > 0
                    ? (p.ist_stunden_gesamt / p.soll_stunden_gesamt * 100)
                    : 0
                  const over = pct > 100
                  const marge = p.auftragswert > 0 && p.soll_kosten > 0
                    ? (p.auftragswert - p.soll_kosten) / p.auftragswert * 100
                    : null
                  return (
                    <Link key={p.id} to={`/projekte/${p.id}`}
                      className="grid items-center px-5 py-3 border-t border-slate-100 hover:bg-slate-50 transition-colors gap-4"
                      style={{ gridTemplateColumns: '180px 1fr 56px 52px' }}>
                      {/* Name + Kunde */}
                      <div className="min-w-0">
                        <p className="text-[13px] font-semibold text-slate-900 truncate">{p.name}</p>
                        <p className="text-[11px] text-slate-400 truncate">{p.kunde}</p>
                      </div>
                      {/* Progress */}
                      <div className="min-w-0">
                        <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden mb-1.5">
                          <div
                            className="h-full rounded-full transition-all"
                            style={{ width: `${Math.min(pct, 100)}%`, background: over ? '#f59e0b' : '#0f766e' }}
                          />
                        </div>
                        <p className="text-[10.5px] text-slate-400 tabular-nums">
                          {fmtH(p.ist_stunden_gesamt)} / {fmtH(p.soll_stunden_gesamt)} Std
                        </p>
                      </div>
                      {/* % */}
                      <div className="text-right">
                        <p className={`text-[13px] font-bold tabular-nums ${over ? 'text-amber-600' : 'text-slate-900'}`}>
                          {Math.round(pct)} %
                        </p>
                      </div>
                      {/* Marge */}
                      <div className="text-right">
                        {marge != null ? (
                          <>
                            <p className={`text-[12px] font-semibold tabular-nums ${marge >= 0 ? 'text-teal-700' : 'text-red-600'}`}>
                              {Math.round(marge)} %
                            </p>
                            <p className="text-[9.5px] text-slate-400 uppercase tracking-wide">Marge</p>
                          </>
                        ) : (
                          <span className="text-[12px] text-slate-300">–</span>
                        )}
                      </div>
                    </Link>
                  )
                })}
              </div>
            )}
          </div>

        </div>

        {/* RIGHT: sidebar */}
        <div className="flex flex-col gap-5">

          {/* Angebots-Pipeline */}
          <div className="bg-white border border-slate-200 rounded-xl shadow-xs p-5">
            <h2 className="text-[13.5px] font-semibold text-slate-900">Angebots-Pipeline</h2>
            <p className="text-[12px] text-slate-400 mt-0.5 mb-5">
              Gesamt {fmtEUR(wertOffen)} in {offeneAngebote.length} Angeboten
            </p>

            {/* Status bars */}
            <div className="flex flex-col gap-3.5 mb-5">
              {[
                { label: 'Entwurf',   wert: wertEntwurf,   n: stats.counts.entwurf   || 0, color: '#94a3b8' },
                { label: 'Angeboten', wert: wertAngeboten,  n: stats.counts.angeboten  || 0, color: '#0f766e' },
              ].map(row => (
                <div key={row.label}>
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-sm shrink-0" style={{ background: row.color }} />
                      <span className="text-[12.5px] text-slate-600 font-medium">{row.label}</span>
                    </div>
                    <span className="text-[12.5px] font-semibold text-slate-700 tabular-nums">{fmtK(row.wert)}</span>
                  </div>
                  <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all"
                      style={{ width: `${Math.round((row.wert / maxW) * 100)}%`, background: row.color }}
                    />
                  </div>
                </div>
              ))}
            </div>

            {/* Stats */}
            <div className="grid grid-cols-3 divide-x divide-slate-100 pt-4 border-t border-slate-100">
              {[
                { label: 'Gewonnen', value: n_gewonnen },
                { label: 'Verloren',  value: n_verloren },
                { label: 'Quote',     value: gewinnrate != null ? `${Math.round(gewinnrate * 100)} %` : '–' },
              ].map(({ label, value }, i) => (
                <div key={label} className={`text-center ${i === 0 ? '' : 'pl-2'} ${i < 2 ? 'pr-2' : ''}`}>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.05em] text-slate-400 mb-1">{label}</p>
                  <p className="text-[20px] font-bold text-slate-900 tabular-nums leading-tight">{value}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Letzte Aktivität */}
          <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
            <div className="px-5 py-3.5 border-b border-slate-100">
              <h2 className="text-[13.5px] font-semibold text-slate-900">Letzte Aktivität</h2>
            </div>
            {stats.recent.length === 0 ? (
              <div className="px-5 py-8 text-center">
                <p className="text-[13px] text-slate-400">Noch keine Aktivitäten</p>
              </div>
            ) : (
              <div className="p-4 flex flex-col gap-3.5">
                {stats.recent.slice(0, 6).map(p => {
                  const cfg = STATUS_CFG[p.status] || STATUS_CFG.entwurf
                  return (
                    <div key={p.id} className="flex gap-3">
                      <div className="mt-[5px] w-2 h-2 rounded-full flex-none shrink-0" style={{ background: cfg.dot }} />
                      <div className="min-w-0">
                        <p className="text-[12.5px] text-slate-800 leading-snug font-medium">{activityLabel(p)}</p>
                        <p className="text-[11px] text-slate-400 mt-0.5">{relDate(p.erstellt_am)}</p>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

        </div>
      </div>
    </div>
  )
}
