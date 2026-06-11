const fmtEUR = (n) =>
  new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(n)

function fmtDauer(tage) {
  if (!tage) return '–'
  if (tage < 30)  return `${tage} Tage`
  if (tage < 90)  return `${Math.round(tage / 7)} Wochen`
  return `${Math.round(tage / 30)} Monate`
}

export default function SimilarProject({ projekt }) {
  const { titel, budget_eur, dauer_tage } = projekt
  return (
    <div className="card flex flex-col gap-2">
      <p className="text-sm font-medium text-ink leading-snug line-clamp-3">{titel}</p>
      <div className="mt-auto pt-2 flex gap-4 text-xs text-gray-500">
        <span className="font-semibold text-primary">{fmtEUR(budget_eur)}</span>
        <span>{fmtDauer(dauer_tage)}</span>
      </div>
    </div>
  )
}
