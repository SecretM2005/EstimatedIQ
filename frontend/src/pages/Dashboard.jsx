import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getDashboardStats } from '../api/angebot'

const fmtEUR = n =>
  new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(n)

const STATUS_META = {
  entwurf:      { label: 'Entwurf',      bg: '#fffbeb', color: '#b45309', border: '#fef3c7' },
  angeboten:    { label: 'Angeboten',    bg: '#eef2ff', color: '#4f46e5', border: '#e0e7ff' },
  beauftragt:   { label: 'Beauftragt',   bg: '#ecfdf5', color: '#047857', border: '#d1fae5' },
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

  return (
    <div className="p-8 pb-16 max-w-[1200px]">
      {/* Header */}
      <div className="mb-7">
        <h1 className="text-[24px] font-bold tracking-tight text-slate-900 m-0">Dashboard</h1>
        <p className="mt-1.5 text-[13.5px] text-slate-500">Übersicht über Angebote und Projekte</p>
      </div>

      {/* KPI cards */}
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-7">
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
          accent="bg-emerald-50"
          icon={
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="text-emerald-600">
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

      {/* Content panels */}
      <div className="grid lg:grid-cols-2 gap-5">
        {/* Angebote */}
        <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
          <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-100">
            <h2 className="text-[13.5px] font-semibold text-slate-900">Aktuelle Angebote</h2>
            <Link to="/angebote" className="text-[12px] text-accent hover:text-accent-hover font-medium transition-colors">
              Alle anzeigen →
            </Link>
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
              {angebote.map((p, i) => (
                <Link
                  key={p.id}
                  to={`/projekte/${p.id}`}
                  className="flex items-center gap-3 px-5 py-3 border-t border-slate-100 first:border-0 hover:bg-slate-50 transition-colors"
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-[13px] font-medium text-slate-900 truncate">{p.name}</p>
                    <p className="text-[11.5px] text-slate-400">{p.kunde}</p>
                  </div>
                  <div className="shrink-0 text-right">
                    {p.wert > 0 && (
                      <p className="text-[12.5px] font-semibold text-slate-900 tabular-nums mb-1">{fmtEUR(p.wert)}</p>
                    )}
                    <StatusPill status={p.status} />
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* Projekte */}
        <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
          <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-100">
            <h2 className="text-[13.5px] font-semibold text-slate-900">Laufende Projekte</h2>
            <Link to="/projekte" className="text-[12px] text-accent hover:text-accent-hover font-medium transition-colors">
              Alle anzeigen →
            </Link>
          </div>
          {projekte.length === 0 ? (
            <div className="px-5 py-8 text-center">
              <p className="text-[13px] text-slate-400">Noch keine beauftragten Projekte</p>
              <p className="text-[12px] text-slate-400 mt-1">Angebote werden hier nach Auftragserteilung sichtbar.</p>
            </div>
          ) : (
            <div>
              {projekte.map((p, i) => (
                <Link
                  key={p.id}
                  to={`/projekte/${p.id}`}
                  className="flex items-center gap-3 px-5 py-3 border-t border-slate-100 first:border-0 hover:bg-slate-50 transition-colors"
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-[13px] font-medium text-slate-900 truncate">{p.name}</p>
                    <p className="text-[11.5px] text-slate-400">{p.kunde}</p>
                  </div>
                  <div className="shrink-0 text-right">
                    {p.wert > 0 && (
                      <p className="text-[12.5px] font-semibold text-slate-900 tabular-nums mb-1">{fmtEUR(p.wert)}</p>
                    )}
                    <StatusPill status={p.status} />
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Pipeline status bar */}
      {(stats.n_offen + stats.n_beauftragt + stats.n_abgeschlossen + stats.n_abgelehnt) > 0 && (
        <div className="mt-5 bg-white border border-slate-200 rounded-xl shadow-xs p-5">
          <h2 className="text-[13.5px] font-semibold text-slate-900 mb-4">Pipeline-Übersicht</h2>
          <div className="grid grid-cols-5 gap-3">
            {[
              { key: 'entwurf',       label: 'Entwurf',       n: stats.counts.entwurf || 0,       color: '#f59e0b' },
              { key: 'angeboten',     label: 'Angeboten',     n: stats.counts.angeboten || 0,     color: '#6366f1' },
              { key: 'beauftragt',    label: 'Beauftragt',    n: stats.counts.beauftragt || 0,    color: '#10b981' },
              { key: 'abgeschlossen', label: 'Abgeschlossen', n: stats.counts.abgeschlossen || 0, color: '#94a3b8' },
              { key: 'abgelehnt',     label: 'Abgelehnt',     n: stats.counts.abgelehnt || 0,     color: '#ef4444' },
            ].map(s => (
              <div key={s.key} className="text-center">
                <div
                  className="w-10 h-10 rounded-full flex items-center justify-center mx-auto mb-2 text-white text-[14px] font-bold tabular-nums"
                  style={{ background: s.color }}
                >
                  {s.n}
                </div>
                <p className="text-[11px] text-slate-500 font-medium">{s.label}</p>
              </div>
            ))}
          </div>
          {stats.gewinnrate != null && (
            <div className="mt-4 pt-4 border-t border-slate-100">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[12px] text-slate-500">Gewinnrate</span>
                <span className="text-[12px] font-semibold text-slate-900">{Math.round(stats.gewinnrate * 100)} %</span>
              </div>
              <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full bg-emerald-500 transition-all"
                  style={{ width: `${Math.round(stats.gewinnrate * 100)}%` }}
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
