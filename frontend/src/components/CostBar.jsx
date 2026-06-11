const fmt = (n) =>
  new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(n)

/**
 * Visual min → expected → max cost range bar.
 */
export default function CostBar({ kosten_min, kosten_expected, kosten_max }) {
  // Normalise positions as percentages of the full range
  const range   = kosten_max - kosten_min
  const expPct  = range > 0 ? ((kosten_expected - kosten_min) / range) * 100 : 50

  return (
    <div className="w-full">
      {/* Track */}
      <div className="relative h-3 bg-blue-100 rounded-full">
        {/* Filled segment from min to max */}
        <div className="absolute inset-0 bg-gradient-to-r from-blue-200 via-accent to-blue-300 rounded-full opacity-40" />

        {/* Expected marker */}
        <div
          className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-5 h-5 rounded-full bg-accent border-2 border-white shadow"
          style={{ left: `${expPct}%` }}
          title={`Erwartet: ${fmt(kosten_expected)}`}
        />
      </div>

      {/* Labels */}
      <div className="flex justify-between mt-3 text-sm">
        <div className="text-left">
          <div className="text-gray-400 text-xs font-medium uppercase tracking-wide">Minimum</div>
          <div className="font-semibold text-ink">{fmt(kosten_min)}</div>
        </div>

        <div className="text-center">
          <div className="text-accent text-xs font-medium uppercase tracking-wide">Erwartet</div>
          <div className="font-bold text-accent">{fmt(kosten_expected)}</div>
        </div>

        <div className="text-right">
          <div className="text-gray-400 text-xs font-medium uppercase tracking-wide">Maximum</div>
          <div className="font-semibold text-ink">{fmt(kosten_max)}</div>
        </div>
      </div>
    </div>
  )
}
