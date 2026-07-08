import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getDashboardStats } from '../api/angebot'

const fmtEUR = n =>
  new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(n)

const STATUS_META = {
  entwurf:      { label: 'Entwurf',      bg: '#fffbeb', color: '#b45309', border: '#fef3c7' },
  angeboten:    { label: 'Angeboten',    bg: '#eef2ff', color: '#4f46e5', border: '#e0e7ff' },
  beauftragt:   { label: 'In Arbeit',    bg: '#f0fdfa', color: '#0f766e', border: '#99f6e4' },
  abgeschlossen:{ label: 'Abgeschlossen',bg: '#f8fafc', color: '#64748b', border: '#e2e8f0' },
  abgelehnt:    { label: 'Abgelehnt',    bg: '#fef2f2', color: '#b91c1c', border: '#fecaca' },
}

function StatusPill({ status }) {
  const s = STATUS_META[status] || STATUS_META.entwurf
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', height: 20, padding: '0 8px',
      fontSize: 11, fontWeight: 600, borderRadius: 999,
      background: s.bg, color: s.color, border: `1px solid ${s.border}`, whiteSpace: 'nowrap',
    }}>{s.label}</span>
  )
}

function KpiCard({ label, value, sub, icon, accent }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl px-5 py-4 shadow-xs flex items-start gap-4">
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-none mt-0.5 ${accent || 'bg-slate-100'}`}>
        {icon}
      </div>
      <div className="min-w-0">
        <p className="text-[11px] font-semibold uppercase tracking-[0.05em] text-slate-400 mb-1">{label}</p>
        <p className="text-[24px] font-bold text-slate-900 leading-none tabular-nums">{value}</p>
        {sub && <p className="text-[12px] text-slate-400 mt-1">{sub}</p>}
      </div>
    </div>
  )
}

function relDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const diffMs = now - d
  const diffDays = Math.floor(diffMs / 86400000)
  if (diffDays === 0) return 'Heute'
  if (diffDays === 1) return 'Gestern'
  if (diffDays < 7) return `vor ${diffDays} Tagen`
  if (diffDays < 30) return `vor ${Math.floor(diffDays / 7)} Wo.`
  return d.toLocaleDateString('de-DE', { day: '2-digit', month: 'short' })
}

export default function Dashboard() {
  const [stats,   setStats]   = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getDashboardStats()
      .then(setStats)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="p-8 text-slate-400 text-sm">Lade…</div>

  const gewinnrate = stats.gewinnrate != null
    ? `${Math.round(stats.gewinnrate * 100)} %`
    : '–'

  const angebote  = stats.recent.filter(p => ['entwurf','angeboten','abgelehnt'].includes(p.status))
  const projekte  = stats.recent.filter(p => ['beauftragt','abgeschlossen'].includes(p.status))

  // Pipeline stages for funnel
  const nEntwurf      = stats.counts.entwurf      || 0
  const nAngeboten    = stats.counts.angeboten     || 0
  const nBeauftragt   = stats.counts.beauftragt    || 0
  const nAbgeschlossen= stats.counts.abgeschlossen || 0
  const nAbgelehnt    = stats.counts.abgelehnt     || 0
  const hasPipeline   = (nEntwurf + nAngeboten + nBeauftragt + nAbgeschlossen + nAbgelehnt) > 0

  const conv = (a, b) => (a > 0 ? Math.round((b / a) * 100) : null)

  const FUNNEL = [
    { key: 'entwurf',       label: 'Entwurf',       n: nEntwurf,       color: '#f59e0b', light: '#fffbeb', link: '/angebote' },
    { key: 'angeboten',     label: 'Angeboten',     n: nAngeboten,     color: '#6366f1', light: '#eef2ff', link: '/angebote', conv: conv(nEntwurf, nAngeboten) },
    { key: 'beauftragt',    label: 'Beauftragt',    n: nBeauftragt,    color: '#0f766e', light: '#f0fdfa', link: '/projekte', conv: conv(nAngeboten, nBeauftragt) },
    { key: 'abgeschlossen', label: 'Abgeschlossen', n: nAbgeschlossen, color: '#64748b', light: '#f8fafc', link: '/projekte', conv: conv(nBeauftragt, nAbgeschlossen) },
  ]

  // Recent activity: all recent items sorted newest-first
  const aktivitaeten = [...stats.recent].sort((a, b) =>
    new Date(b.erstellt_am || 0) - new Date(a.erstellt_am || 0)
  ).slice(0, 8)

  return (
    <div className="p-8 pb-16">
      {/* Header */}
      <div className="mb-7">
        <h1 className="text-[24px] font-bold tracking-tight text-slate-900 m-0">Dashboard</h1>
        <p className="mt-1.5 text-[13.5px] text-slate-500">Übersicht über Angebote und Projekte</p>
      </div>

      {/* KPI cards */}
      <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
        <KpiCard
          label="Offene Angebote"
          value={stats.n_offen}
          sub={fmtEUR(stats.wert_offen) + ' Pipeline'}
          accent="bg-amber-50"
          icon={
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="text-amber-600">
              <path d="M9 12h6m-3-3v6M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round"/>
            </svg>
          }
        />
        <KpiCard
          label="Gewinnrate"
          value={gewinnrate}
          sub={stats.gewinnrate != null
            ? `${stats.n_beauftragt + stats.n_abgeschlossen} gewonnen · ${stats.n_abgelehnt} abgelehnt`
            : 'Noch keine Entscheidungen'}
          accent={stats.gewinnrate != null && stats.gewinnrate >= 0.5 ? 'bg-emerald-50' : 'bg-slate-100'}
          icon={
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className={stats.gewinnrate != null && stats.gewinnrate >= 0.5 ? 'text-emerald-600' : 'text-slate-400'}>
              <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round"/>
            </svg>
          }
        />
        <KpiCard
          label="Aktive Projekte"
          value={stats.n_beauftragt}
          sub={`${stats.n_abgeschlossen} abgeschlossen`}
          accent="bg-teal-50"
          icon={
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="text-teal-700">
              <path d="M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          }
        />
        <KpiCard
          label="Auftragsvolumen"
          value={fmtEUR(stats.wert_beauftragt)}
          sub="laufende + abgeschlossene Projekte"
          accent="bg-indigo-50"
          icon={
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="text-accent">
              <path d="M12 2v20M17 5H9.5a3.5 3.5 0 1 0 0 7h5a3.5 3.5 0 1 1 0 7H6" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/>
            </svg>
          }
        />
      </div>

      {/* Main grid: left lists, right sidebar */}
      <div className="grid xl:grid-cols-[1fr_320px] gap-5 mb-5">
        {/* Left: Angebote + Projekte */}
        <div className="flex flex-col gap-5">
          <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-100">
              <h2 className="text-[13.5px] font-semibold text-slate-900">Aktuelle Angebote</h2>
              <Link to="/angebote" className="text-[12px] text-accent hover:text-accent-hover font-medium transition-colors">Alle anzeigen →</Link>
            </div>
            {angebote.length === 0 ? (
              <div className="px-5 py-8 text-center">
                <p className="text-[13px] text-slate-400">Noch keine Angebote</p>
                <Link to="/angebote" className="inline-flex mt-3 h-8 px-3 bg-accent hover:bg-accent-hover text-white text-[12px] font-semibold rounded-lg items-center gap-1.5 transition-colors">
                  Erstes Angebot erstellen
                </Link>
              </div>
            ) : (
              <div>
                {angebote.map(p => (
                  <Link key={p.id} to={`/angebote/${p.id}`}
                    className="flex items-center gap-3 px-5 py-3 border-t border-slate-100 first:border-0 hover:bg-slate-50 transition-colors">
                    <div className="flex-1 min-w-0">
                      <p className="text-[13px] font-medium text-slate-900 truncate">{p.name}</p>
                      <p className="text-[11.5px] text-slate-400">{p.kunde}</p>
                    </div>
                    <div className="shrink-0 text-right">
                      {p.wert > 0 && <p className="text-[12.5px] font-semibold text-slate-900 tabular-nums mb-1">{fmtEUR(p.wert)}</p>}
                      <StatusPill status={p.status} />
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </div>

          <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-100">
              <h2 className="text-[13.5px] font-semibold text-slate-900">Laufende Projekte</h2>
              <Link to="/projekte" className="text-[12px] text-accent hover:text-accent-hover font-medium transition-colors">Alle anzeigen →</Link>
            </div>
            {projekte.length === 0 ? (
              <div className="px-5 py-8 text-center">
                <p className="text-[13px] text-slate-400">Noch keine beauftragten Projekte</p>
                <p className="text-[12px] text-slate-400 mt-1">Angebote werden hier nach Auftragserteilung sichtbar.</p>
              </div>
            ) : (
              <div>
                {projekte.map(p => (
                  <Link key={p.id} to={`/projekte/${p.id}`}
                    className="flex items-center gap-3 px-5 py-3 border-t border-slate-100 first:border-0 hover:bg-slate-50 transition-colors">
                    <div className="flex-1 min-w-0">
                      <p className="text-[13px] font-medium text-slate-900 truncate">{p.name}</p>
                      <p className="text-[11.5px] text-slate-400">{p.kunde}</p>
                    </div>
                    <div className="shrink-0 text-right">
                      {p.wert > 0 && <p className="text-[12.5px] font-semibold text-slate-900 tabular-nums mb-1">{fmtEUR(p.wert)}</p>}
                      <StatusPill status={p.status} />
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right sidebar: Letzte Aktivitäten + Schnellzugriff */}
        <div className="flex flex-col gap-5">
          {/* Letzte Aktivitäten */}
          <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
            <div className="px-5 py-3.5 border-b border-slate-100">
              <h2 className="text-[13.5px] font-semibold text-slate-900">Letzte Aktivitäten</h2>
            </div>
            {aktivitaeten.length === 0 ? (
              <div className="px-5 py-8 text-center">
                <p className="text-[13px] text-slate-400">Noch keine Aktivitäten</p>
              </div>
            ) : (
              <div className="divide-y divide-slate-100">
                {aktivitaeten.map(p => {
                  const isAngebot = ['entwurf','angeboten','abgelehnt'].includes(p.status)
                  const s = STATUS_META[p.status] || STATUS_META.entwurf
                  return (
                    <Link
                      key={p.id}
                      to={isAngebot ? `/angebote/${p.id}` : `/projekte/${p.id}`}
                      className="flex items-start gap-3 px-5 py-3 hover:bg-slate-50 transition-colors"
                    >
                      {/* Status dot */}
                      <div className="mt-1.5 w-2 h-2 rounded-full flex-none" style={{ background: s.color }} />
                      <div className="flex-1 min-w-0">
                        <p className="text-[12.5px] font-medium text-slate-900 truncate leading-snug">{p.name}</p>
                        <p className="text-[11px] text-slate-400 mt-0.5">{p.kunde}</p>
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="text-[11px] text-slate-400">{relDate(p.erstellt_am)}</p>
                        <div className="mt-0.5 flex justify-end">
                          <StatusPill status={p.status} />
                        </div>
                      </div>
                    </Link>
                  )
                })}
              </div>
            )}
          </div>

          {/* Schnellzugriff */}
          <div className="bg-white border border-slate-200 rounded-xl shadow-xs p-5">
            <h2 className="text-[13.5px] font-semibold text-slate-900 mb-3">Schnellzugriff</h2>
            <div className="flex flex-col gap-1">
              {[
                {
                  to: '/angebote', label: 'Neues Angebot erstellen',
                  icon: <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"/>,
                },
                {
                  to: '/projekte', label: 'Projektstatus verwalten',
                  icon: <path d="M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>,
                },
                {
                  to: '/rollen', label: 'Rollen & Stundensätze',
                  icon: <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>,
                },
                {
                  to: '/import', label: 'Daten importieren',
                  icon: <path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>,
                },
              ].map(({ to, label, icon }) => (
                <Link key={to} to={to}
                  className="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-slate-50 transition-colors group">
                  <div className="w-7 h-7 rounded-md bg-slate-100 group-hover:bg-accent/10 flex items-center justify-center flex-none transition-colors">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" className="text-slate-500 group-hover:text-accent transition-colors">
                      {icon}
                    </svg>
                  </div>
                  <span className="text-[13px] text-slate-700 group-hover:text-slate-900 font-medium transition-colors">{label}</span>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" className="ml-auto text-slate-300 group-hover:text-slate-400 transition-colors">
                    <path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </Link>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Angebotspipeline – full width */}
      {hasPipeline && (
        <div className="bg-white border border-slate-200 rounded-xl shadow-xs p-6">
          <div className="flex items-center justify-between mb-5">
            <div>
              <h2 className="text-[13.5px] font-semibold text-slate-900">Angebotspipeline</h2>
              <p className="text-[12px] text-slate-400 mt-0.5">Von der Anfrage bis zum Abschluss</p>
            </div>
            {stats.gewinnrate != null && (
              <div className="text-right">
                <p className="text-[11px] text-slate-400 uppercase tracking-wide font-semibold">Gewinnrate</p>
                <p className="text-[22px] font-bold text-slate-900 tabular-nums leading-tight">{Math.round(stats.gewinnrate * 100)} %</p>
              </div>
            )}
          </div>

          {/* Funnel stages */}
          <div className="flex items-stretch gap-0">
            {FUNNEL.map((stage, i) => {
              const maxN = Math.max(...FUNNEL.map(s => s.n), 1)
              const barH = stage.n > 0 ? Math.max(Math.round((stage.n / maxN) * 56) + 16, 28) : 16
              return (
                <div key={stage.key} className="flex items-center flex-1 min-w-0">
                  {/* Conversion arrow between stages */}
                  {i > 0 && (
                    <div className="flex flex-col items-center px-1 shrink-0">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="text-slate-300">
                        <path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                      {stage.conv != null && (
                        <span className="text-[9.5px] font-semibold text-slate-400 tabular-nums mt-0.5">{stage.conv}%</span>
                      )}
                    </div>
                  )}

                  {/* Stage card */}
                  <Link to={stage.link} className="flex-1 min-w-0 group">
                    <div
                      className="rounded-xl border px-4 py-3 transition-all group-hover:shadow-sm"
                      style={{ borderColor: stage.color + '40', background: stage.light }}
                    >
                      <div className="flex items-end gap-2 mb-2">
                        <span
                          className="text-[32px] font-bold tabular-nums leading-none"
                          style={{ color: stage.color }}
                        >{stage.n}</span>
                      </div>
                      {/* Mini bar */}
                      <div className="h-1.5 bg-white/60 rounded-full overflow-hidden mb-2">
                        <div
                          className="h-full rounded-full transition-all"
                          style={{ width: `${stage.n > 0 ? Math.round((stage.n / Math.max(...FUNNEL.map(s => s.n), 1)) * 100) : 0}%`, background: stage.color }}
                        />
                      </div>
                      <p className="text-[11.5px] font-semibold truncate" style={{ color: stage.color }}>{stage.label}</p>
                    </div>
                  </Link>
                </div>
              )
            })}

            {/* Abgelehnt separator + card */}
            {nAbgelehnt > 0 && (
              <>
                <div className="flex items-center px-2 shrink-0">
                  <div className="w-px h-8 bg-slate-200 mx-1" />
                </div>
                <div className="shrink-0 w-36">
                  <div className="rounded-xl border border-red-100 bg-red-50 px-4 py-3">
                    <div className="flex items-end gap-1 mb-2">
                      <span className="text-[32px] font-bold tabular-nums leading-none text-red-500">{nAbgelehnt}</span>
                    </div>
                    <div className="h-1.5 bg-white/60 rounded-full overflow-hidden mb-2">
                      <div className="h-full rounded-full bg-red-400" style={{ width: '100%' }} />
                    </div>
                    <p className="text-[11.5px] font-semibold text-red-500">Abgelehnt</p>
                  </div>
                </div>
              </>
            )}
          </div>

          {/* Gewinnrate bar */}
          {stats.gewinnrate != null && (
            <div className="mt-5 pt-4 border-t border-slate-100">
              <div className="flex items-center gap-3">
                <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full bg-teal-500 transition-all"
                    style={{ width: `${Math.round(stats.gewinnrate * 100)}%` }}
                  />
                </div>
                <span className="text-[12px] text-slate-500 tabular-nums shrink-0">
                  {stats.n_beauftragt + stats.n_abgeschlossen} gewonnen · {stats.n_abgelehnt} abgelehnt
                </span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
