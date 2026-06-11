const RISK_ICONS = ['⚠️', '🔴', '🟡']

export default function RiskCard({ risk, index }) {
  return (
    <div className="card flex gap-3 items-start">
      <span className="text-lg mt-0.5 shrink-0">{RISK_ICONS[index] ?? '⚠️'}</span>
      <p className="text-sm text-ink leading-relaxed">{risk}</p>
    </div>
  )
}
