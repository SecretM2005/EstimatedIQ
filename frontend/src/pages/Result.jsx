import { useEffect, useState } from 'react'
import { useNavigate, useLocation, Link } from 'react-router-dom'
import { getEstimate } from '../api/estimate'
import CostBar from '../components/CostBar'
import RiskCard from '../components/RiskCard'
import LoadingScreen from '../components/LoadingScreen'

const fmtEUR = (n) =>
  new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(n)

function fmtDauer(tage) {
  if (!tage || tage <= 0) return '–'
  if (tage < 30)  return `${Math.round(tage)} Tage`
  if (tage < 90)  return `${Math.round(tage / 7)} Wochen`
  return `${Math.round(tage / 30)} Monate`
}

function confidenceLabel(score) {
  if (score == null) return { text: 'Unbekannt', color: 'text-slate-400' }
  if (score < 0.4)   return { text: 'Niedrig',   color: 'text-red-500'    }
  if (score < 0.7)   return { text: 'Mittel',    color: 'text-yellow-600' }
  return                    { text: 'Hoch',      color: 'text-emerald-600' }
}

const ASSESSMENT = {
  zu_klein: { label: 'Team zu klein',  cls: 'bg-red-50 text-red-600 border-red-200'           },
  passend:  { label: 'Team passend',   cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  zu_gross: { label: 'Team zu groß',   cls: 'bg-amber-50 text-amber-700 border-amber-200'       },
}

const MOCK = {
  dauer_tage:         210,
  personalkosten:     189_000,
  kosten_min:         420_000,
  kosten_expected:    840_000,
  kosten_max:       2_100_000,
  overhead_faktor:      1.8,
  confidence_score:     0.62,
  teamgroesse:          3,
  teamgroesse_modell:   3,
  team_assessment:      null,
  projekt_groesse:     'mittel',
  top_risks: [
    'SAP-Schnittstellenkomplexität kann Integrationsdauer um 30–50% verlängern.',
    'Nutzerverwaltung für 200 MA erfordert Sicherheits-Audit (DSGVO/NIS2).',
    'Abhängigkeit vom ERP-Lieferanten für API-Dokumentation und Testumgebung.',
  ],
  similar_projects: [
    { titel: 'Entwicklung Web-Portal mit SAP-Anbindung, Bayern 2023',    budget_eur: 760_000, dauer_tage: 180 },
    { titel: 'Nutzerverwaltungssystem mit SSO, Nordrhein-Westfalen 2022', budget_eur: 920_000, dauer_tage: 240 },
    { titel: 'ERP-Frontend-Modernisierung React, Hessen 2024',           budget_eur: 680_000, dauer_tage: 150 },
  ],
}

function PrintIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="6 9 6 2 18 2 18 9" />
      <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" />
      <rect x="6" y="14" width="12" height="8" />
    </svg>
  )
}

function ArrowLeftIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="19" y1="12" x2="5" y2="12" />
      <polyline points="12 19 5 12 12 5" />
    </svg>
  )
}

export default function Result() {
  const navigate  = useNavigate()
  const { state } = useLocation()

  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  const beschreibung   = state?.beschreibung   ?? ''
  const region         = state?.region         ?? 'DE'
  const projektGroesse = state?.projektGroesse ?? 'mittel'
  const teamgroesse    = state?.teamgroesse    ?? null

  useEffect(() => {
    if (!beschreibung) {
      navigate('/', { replace: true })
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const result = await getEstimate(beschreibung, region, teamgroesse, projektGroesse)
        if (!cancelled) setData(result)
      } catch (err) {
        if (!cancelled) setError(err.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [beschreibung, region, navigate])

  if (loading) return <LoadingScreen />

  const displayData = error ? MOCK : data
  const confidence  = confidenceLabel(displayData?.confidence_score)

  const assessment = displayData.team_assessment ? ASSESSMENT[displayData.team_assessment] : null

  return (
    <div className="min-h-screen bg-light">
      {/* Nav */}
      <header className="px-6 py-4 flex items-center justify-between bg-white border-b border-slate-200 no-print">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
            <span className="text-white font-bold text-sm">IQ</span>
          </div>
          <span className="font-bold text-primary text-lg tracking-tight">EstimateIQ</span>
        </div>
        <div className="flex items-center gap-2 no-print">
          <Link to="/upload" className="btn-secondary text-sm py-2">
            Daten hochladen
          </Link>
          <button
            onClick={() => navigate('/')}
            className="btn-secondary text-sm py-2"
          >
            <ArrowLeftIcon />
            Neue Schätzung
          </button>
        </div>
      </header>

      {/* API error banner */}
      {error && (
        <div className="bg-red-50 border-b border-red-200 px-6 py-3 text-red-700 text-sm flex items-start gap-2 no-print">
          <span className="shrink-0 mt-0.5">⚠</span>
          <span>
            <strong>Demo-Daten:</strong> {error} Die unten angezeigten Werte sind Beispieldaten.
          </span>
        </div>
      )}

      <main className="max-w-3xl mx-auto px-4 py-10">
        {/* Project snippet */}
        <p className="text-xs text-slate-400 uppercase tracking-wide font-medium mb-1">Projektbeschreibung</p>
        <p className="text-sm text-slate-500 mb-8 line-clamp-2 italic">
          „{beschreibung.slice(0, 160)}{beschreibung.length > 160 ? '…' : ''}"
        </p>

        {/* Hero: cost + assessment badge */}
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-4">
          <div>
            <p className="text-xs text-slate-400 uppercase tracking-widest font-semibold mb-1">
              Erwartete Projektkosten
            </p>
            <p className="text-5xl md:text-6xl font-extrabold text-primary tracking-tight">
              {fmtEUR(displayData.kosten_expected)}
            </p>
            <p className="text-xs text-slate-400 mt-1">netto · ohne MwSt.</p>

            {/* Cost breakdown */}
            {(() => {
              const team     = displayData.teamgroesse
              const dauer    = displayData.dauer_tage
              const personal = displayData.personalkosten
              const overhead = displayData.overhead_faktor
              if (!team || !dauer || !personal || !overhead) return null
              const stundensatz = Math.round(personal / (dauer * team * 8))
              const monate      = Math.max(1, Math.round(dauer / 30))
              const teamRund    = Math.max(1, Math.round(team * 2) / 2)
              const ohPct       = Math.round((overhead - 1) * 100)
              return (
                <p className="text-sm text-slate-400 mt-2">
                  ca.{' '}
                  <span className="text-slate-600 font-medium">
                    {teamRund === 1 ? '1 Entwickler' : `${teamRund} Entwickler`}
                  </span>
                  {' × '}
                  <span className="text-slate-600 font-medium">
                    {monate === 1 ? '1 Monat' : `${monate} Monate`}
                  </span>
                  {' × '}
                  <span className="text-slate-600 font-medium">{stundensatz} €/h</span>
                  {ohPct > 0 && (
                    <> + <span className="text-slate-600 font-medium">{ohPct} % Overhead</span></>
                  )}
                </p>
              )
            })()}
          </div>

          {/* Assessment badge */}
          {assessment && (
            <div className={`flex-shrink-0 self-start px-4 py-3 rounded-xl border text-sm font-semibold ${assessment.cls}`}>
              {assessment.label}
              {displayData.team_assessment !== 'passend' && (
                <p className="text-xs font-normal mt-0.5 opacity-75">
                  Empfehlung: {displayData.teamgroesse_modell} Pers.
                </p>
              )}
            </div>
          )}
        </div>

        {/* Cost range bar */}
        <div className="bg-white rounded-xl p-7 shadow-sm border border-slate-200 mb-6">
          <CostBar
            kosten_min={displayData.kosten_min}
            kosten_expected={displayData.kosten_expected}
            kosten_max={displayData.kosten_max}
          />
        </div>

        {/* Metric chips – 4-column grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
          <div className="bg-white border border-slate-200 rounded-xl px-4 py-3 shadow-sm">
            <p className="text-xs text-slate-400 font-medium mb-1">Laufzeit</p>
            <p className="font-bold text-ink">{fmtDauer(displayData.dauer_tage)}</p>
          </div>

          <div className="bg-white border border-slate-200 rounded-xl px-4 py-3 shadow-sm">
            <p className="text-xs text-slate-400 font-medium mb-1">Team</p>
            <p className="font-bold text-ink">
              {displayData.teamgroesse ?? '–'} Pers.
            </p>
          </div>

          <div className="bg-white border border-slate-200 rounded-xl px-4 py-3 shadow-sm">
            <p className="text-xs text-slate-400 font-medium mb-1">Personalkosten</p>
            <p className="font-bold text-ink">{fmtEUR(displayData.personalkosten)}</p>
          </div>

          {displayData.overhead_faktor != null && (
            <div className="bg-white border border-slate-200 rounded-xl px-4 py-3 shadow-sm">
              <p className="text-xs text-slate-400 font-medium mb-1">Overhead</p>
              <p className="font-bold text-ink">{Number(displayData.overhead_faktor).toFixed(2)}×</p>
            </div>
          )}
        </div>

        {/* Top risks */}
        {displayData.top_risks?.length > 0 && (
          <section className="mb-8">
            <h2 className="text-[22px] font-semibold text-primary mb-3">
              Top 3 Risiken
            </h2>
            <div className="flex flex-col gap-3">
              {displayData.top_risks.slice(0, 3).map((risk, i) => (
                <RiskCard key={i} risk={risk} index={i} />
              ))}
            </div>
          </section>
        )}

        {/* Similar projects – entfernt */}

        {/* Disclaimer – simple text */}
        <p className="text-xs text-slate-400 mb-8 leading-relaxed">
          Basis: öffentliche EU-Ausschreibungen (TED-Portal). Konfidenz dieser Schätzung:{' '}
          <span className={`font-medium ${confidence.color}`}>{confidence.text}</span>
          {displayData.confidence_score != null
            ? ` (${Math.round(displayData.confidence_score * 100)} %)`
            : ''}
          . Kleine Projekte unter ~50 000 € können systematisch überschätzt werden. Genauigkeit steigt mit eigenen Projektdaten.
        </p>

        {/* Actions */}
        <div className="flex flex-col sm:flex-row gap-3 no-print">
          <button
            onClick={() => window.print()}
            className="btn-secondary flex-1"
          >
            <PrintIcon />
            Als PDF exportieren
          </button>
          <button
            onClick={() => navigate('/')}
            className="btn-primary flex-1"
          >
            Neue Schätzung
          </button>
        </div>
      </main>
    </div>
  )
}
