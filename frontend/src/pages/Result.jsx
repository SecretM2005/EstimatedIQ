import { useEffect, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { getEstimate } from '../api/estimate'
import CostBar from '../components/CostBar'
import RiskCard from '../components/RiskCard'
import SimilarProject from '../components/SimilarProject'
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
  if (score == null) return { text: 'Unbekannt', color: 'text-gray-400' }
  if (score < 0.4)  return { text: 'Niedrige Konfidenz',  color: 'text-red-500'    }
  if (score < 0.7)  return { text: 'Mittlere Konfidenz',  color: 'text-yellow-600' }
  return               { text: 'Hohe Konfidenz',      color: 'text-green-600'  }
}

// Assessment-Konfiguration
const ASSESSMENT = {
  zu_klein: { label: 'Team zu klein',  cls: 'bg-red-50 text-red-600 border-red-200'       },
  passend:  { label: 'Team passend',   cls: 'bg-green-50 text-green-700 border-green-200'  },
  zu_gross: { label: 'Team zu groß',   cls: 'bg-yellow-50 text-yellow-700 border-yellow-200' },
}

// Fallback mock data for when backend is not running
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

  // On error: show message + fallback demo data
  const displayData = error ? MOCK : data
  const confidence  = confidenceLabel(displayData?.confidence_score)

  return (
    <div className="min-h-screen bg-light">
      {/* Nav */}
      <header className="px-6 py-4 flex items-center justify-between bg-white border-b border-gray-100 no-print">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
            <span className="text-white font-bold text-sm">IQ</span>
          </div>
          <span className="font-bold text-primary text-lg tracking-tight">EstimateIQ</span>
        </div>
        <button
          onClick={() => navigate('/')}
          className="btn-secondary text-sm py-2 no-print"
        >
          Neue Schätzung
        </button>
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
        <p className="text-xs text-gray-400 uppercase tracking-wide font-medium mb-1">Projektbeschreibung</p>
        <p className="text-sm text-gray-600 mb-8 line-clamp-2 italic">
          „{beschreibung.slice(0, 160)}{beschreibung.length > 160 ? '…' : ''}"
        </p>

        {/* Central cost figure */}
        <div className="text-center mb-2">
          <p className="text-xs text-gray-400 uppercase tracking-widest font-semibold mb-1">Erwartete Projektkosten</p>
          <p className="text-5xl md:text-6xl font-extrabold text-primary tracking-tight">
            {fmtEUR(displayData.kosten_expected)}
          </p>
          {/* Kosten-Breakdown: Wie kommt die Zahl zustande? */}
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
              <p className="text-sm text-gray-400 mt-2">
                ca.{' '}
                <span className="text-gray-600 font-medium">
                  {teamRund === 1 ? '1 Entwickler' : `${teamRund} Entwickler`}
                </span>
                {' × '}
                <span className="text-gray-600 font-medium">
                  {monate === 1 ? '1 Monat' : `${monate} Monate`}
                </span>
                {' × '}
                <span className="text-gray-600 font-medium">{stundensatz} €/h</span>
                {ohPct > 0 && (
                  <> + <span className="text-gray-600 font-medium">{ohPct} % Overhead</span></>
                )}
              </p>
            )
          })()}
        </div>

        {/* Cost range bar */}
        <div className="bg-white rounded-xl p-6 shadow-sm border border-blue-50 mb-6">
          <CostBar
            kosten_min={displayData.kosten_min}
            kosten_expected={displayData.kosten_expected}
            kosten_max={displayData.kosten_max}
          />
        </div>

        {/* Duration + Team + overhead chips */}
        <div className="flex flex-wrap gap-3 mb-8">

          {/* Laufzeit */}
          <div className="bg-white border border-gray-100 rounded-lg px-4 py-3 shadow-sm flex items-center gap-2">
            <span className="text-xl">⏱</span>
            <div>
              <p className="text-xs text-gray-400 font-medium">Laufzeit</p>
              <p className="font-bold text-ink">{fmtDauer(displayData.dauer_tage)}</p>
            </div>
          </div>

          {/* Team-Chip mit Assessment */}
          <div className="bg-white border border-gray-100 rounded-lg px-4 py-3 shadow-sm flex items-center gap-2">
            <span className="text-xl">👥</span>
            <div>
              <p className="text-xs text-gray-400 font-medium">Team</p>
              <p className="font-bold text-ink">
                {displayData.teamgroesse ?? '–'} Pers.
              </p>
              {displayData.team_assessment && (() => {
                const a = ASSESSMENT[displayData.team_assessment]
                return (
                  <div className="mt-1">
                    <span className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full border ${a.cls}`}>
                      {a.label}
                    </span>
                    {displayData.team_assessment !== 'passend' && (
                      <p className="text-xs text-gray-400 mt-0.5">
                        Empfehlung: {displayData.teamgroesse_modell} Pers.
                      </p>
                    )}
                  </div>
                )
              })()}
            </div>
          </div>

          {/* Personalkosten */}
          <div className="bg-white border border-gray-100 rounded-lg px-4 py-3 shadow-sm flex items-center gap-2">
            <span className="text-xl">💰</span>
            <div>
              <p className="text-xs text-gray-400 font-medium">Personalkosten</p>
              <p className="font-bold text-ink">{fmtEUR(displayData.personalkosten)}</p>
            </div>
          </div>

          {/* Overhead */}
          {displayData.overhead_faktor != null && (
            <div className="bg-white border border-gray-100 rounded-lg px-4 py-3 shadow-sm flex items-center gap-2">
              <span className="text-xl">📊</span>
              <div>
                <p className="text-xs text-gray-400 font-medium">Overhead-Faktor</p>
                <p className="font-bold text-ink">{Number(displayData.overhead_faktor).toFixed(2)}×</p>
              </div>
            </div>
          )}
        </div>

        {/* Top risks */}
        {displayData.top_risks?.length > 0 && (
          <section className="mb-8">
            <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
              Top-Risiken
            </h2>
            <div className="flex flex-col gap-3">
              {displayData.top_risks.slice(0, 3).map((risk, i) => (
                <RiskCard key={i} risk={risk} index={i} />
              ))}
            </div>
          </section>
        )}

        {/* Similar projects */}
        {displayData.similar_projects?.length > 0 && (
          <section className="mb-8">
            <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
              Ähnliche Referenzprojekte
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {displayData.similar_projects.slice(0, 3).map((p, i) => (
                <SimilarProject key={i} projekt={p} />
              ))}
            </div>
          </section>
        )}

        {/* Disclaimer – prominent & ehrlich */}
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 mb-8">
          <div className="flex gap-3">
            <span className="text-amber-500 text-lg shrink-0 mt-0.5">⚠</span>
            <div>
              <p className="text-sm font-semibold text-amber-800 mb-1">
                Wichtige Hinweise zur Schätzgenauigkeit
              </p>
              <ul className="text-sm text-amber-700 space-y-1 list-disc list-inside">
                <li>
                  Basis sind <strong>öffentliche EU-Ausschreibungen (TED-Portal)</strong> – typischerweise
                  große Behördenprojekte. Kleine Projekte unter ~50.000 € werden aktuell
                  <strong> systematisch überschätzt</strong>.
                </li>
                <li>
                  Konfidenz dieser Schätzung:{' '}
                  <strong className={confidence.color}>{confidence.text}</strong>
                  {displayData.confidence_score != null
                    ? ` (${Math.round(displayData.confidence_score * 100)} %)`
                    : ''}
                  {' '}– Kostenspanne Min/Max zeigt die Unsicherheit.
                </li>
                <li>
                  Genauigkeit verbessert sich mit euren eigenen abgeschlossenen Projektdaten.
                </li>
              </ul>
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="flex flex-col sm:flex-row gap-3 no-print">
          <button
            onClick={() => window.print()}
            className="btn-secondary flex-1 flex items-center justify-center gap-2"
          >
            <span>🖨</span> Als PDF exportieren
          </button>
          <button
            onClick={() => navigate('/')}
            className="btn-primary flex-1"
          >
            Neue Schätzung →
          </button>
        </div>
      </main>
    </div>
  )
}
