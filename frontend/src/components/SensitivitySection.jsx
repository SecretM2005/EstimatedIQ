const fmtEUR = (n) =>
  new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(n)

function SkeletonRow() {
  return (
    <div className="flex items-start justify-between gap-4 py-4 border-b border-slate-100 last:border-0 animate-pulse">
      <div className="flex-1">
        <div className="h-4 bg-slate-200 rounded w-2/3 mb-2" />
        <div className="h-3 bg-slate-100 rounded w-1/3" />
      </div>
      <div className="h-5 bg-slate-200 rounded w-24 shrink-0" />
    </div>
  )
}

function ArrowUpIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="19" x2="12" y2="5" />
      <polyline points="5 12 12 5 19 12" />
    </svg>
  )
}

function ArrowDownIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="5" x2="12" y2="19" />
      <polyline points="19 12 12 19 5 12" />
    </svg>
  )
}

export default function SensitivitySection({ data, loading }) {
  return (
    <section className="mb-8">
      <h2 className="text-[22px] font-semibold text-primary mb-4">Was verändert den Preis?</h2>
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 divide-y divide-slate-100 overflow-hidden">
        {loading || !data
          ? [0, 1, 2, 3].map((i) => (
              <div key={i} className="px-6">
                <SkeletonRow />
              </div>
            ))
          : data.sensitivitaeten.map((item, i) => {
              const teurer    = item.richtung === 'teurer'
              const gleich    = item.richtung === 'gleich'
              const color     = teurer ? '#ef4444' : gleich ? '#94a3b8' : '#16a34a'
              const bgColor   = teurer ? 'bg-red-50' : gleich ? 'bg-slate-50' : 'bg-green-50'
              const textColor = teurer ? 'text-red-600' : gleich ? 'text-slate-500' : 'text-green-700'
              const label     = teurer ? 'teurer' : gleich ? 'gleich' : 'günstiger'

              return (
                <div key={i} className="flex items-center justify-between gap-4 px-6 py-4">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-ink truncate">{item.label}</p>
                    <p className="text-xs text-slate-400 tabular-nums mt-0.5">
                      <span style={{ color }}>
                        {item.delta_eur >= 0 ? '+' : ''}
                        {fmtEUR(item.delta_eur)}
                      </span>
                      {' '}
                      <span className="text-slate-400">
                        ({item.delta_prozent >= 0 ? '+' : ''}{item.delta_prozent}&thinsp;%)
                      </span>
                    </p>
                  </div>
                  <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold shrink-0 ${bgColor} ${textColor}`}
                    style={{ color }}>
                    {teurer ? <ArrowUpIcon /> : gleich ? null : <ArrowDownIcon />}
                    {label}
                  </div>
                </div>
              )
            })}
      </div>
    </section>
  )
}
