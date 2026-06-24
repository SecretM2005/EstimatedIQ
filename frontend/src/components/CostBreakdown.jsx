const fmtEUR = (n) =>
  new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(n)

const KATEGORIEN = [
  { key: 'lohn',    label: 'Lohnkosten', color: '#2563eb' },
  { key: 'overhead', label: 'Overhead',  color: '#6366f1' },
  { key: 'puffer',  label: 'Puffer',     color: '#94a3b8' },
]

export default function CostBreakdown({ personalkosten, kosten_expected }) {
  if (!personalkosten || !kosten_expected) return null

  const puffer_eur   = kosten_expected * 0.05
  const overhead_eur = Math.max(0, kosten_expected - personalkosten - puffer_eur)
  const gesamt       = personalkosten + overhead_eur + puffer_eur

  const items = [
    { key: 'lohn',     label: 'Lohnkosten', betrag: personalkosten, color: '#2563eb' },
    { key: 'overhead', label: 'Overhead',   betrag: overhead_eur,   color: '#6366f1' },
    { key: 'puffer',   label: 'Puffer',     betrag: puffer_eur,     color: '#94a3b8' },
  ]

  return (
    <section className="mb-8">
      <h2 className="text-[22px] font-semibold text-primary mb-4">Kostenaufschlüsselung</h2>
      <div className="bg-white rounded-xl p-6 shadow-sm border border-slate-200 flex flex-col gap-5">
        {items.map(({ key, label, betrag, color }) => {
          const pct = Math.round((betrag / gesamt) * 100)
          return (
            <div key={key}>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-sm font-medium text-ink">{label}</span>
                <span className="text-sm font-semibold text-ink tabular-nums">
                  {pct}&thinsp;%
                </span>
              </div>
              {/* Bar */}
              <div className="h-2.5 w-full bg-slate-100 rounded-full overflow-hidden mb-1">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{ width: `${pct}%`, backgroundColor: color }}
                />
              </div>
              <span className="text-xs text-slate-400 tabular-nums">{fmtEUR(betrag)}</span>
            </div>
          )
        })}
      </div>
    </section>
  )
}
