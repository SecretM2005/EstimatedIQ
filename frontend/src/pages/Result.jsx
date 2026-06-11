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

// Fallback mock data for when backend is not running
const MOCK = {
  dauer_tage:        210,
  personalkosten:    189_000,
  kosten_min:        420_000,
  kosten_expected:   840_000,
  kosten_max:      2_100_000,
  overhead_faktor:     1.8,
  confidence_score:    0.62,
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

  const beschreibung = state?.beschreibung ?? ''
  const region       = state?.region       ?? 'DE'

  useEffect(() => {
    if (!beschreibung) {
      navigate('/', { replace: true })
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const result = await getEstimate(beschreibung, region)
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
        </div>

        {/* Cost range bar */}
        <div className="bg-white rounded-xl p-6 shadow-sm border border-blue-50 mb-6">
          <CostBar
            kosten_min={displayData.kosten_min}
            kosten_expected={displayData.kosten_expected}
            kosten_max={displayData.kosten_max}
          />
        </div>

        {/* Duration + overhead chips */}
        <div className="flex flex-wrap gap-3 mb-8">
          <div className="bg-white border border-gray-100 rounded-lg px-4 py-3 shadow-sm flex items-center gap-2">
            <span className="text-xl">⏱</span>
            <div>
              <p className="text-xs text-gray-400 font-medium">Laufzeit</p>
              <p className="font-bold text-ink">{fmtDauer(displayData.dauer_tage)}</p>
            </div>
          </div>
          <div className="bg-white border border-gray-100 rounded-lg px-4 py-3 shadow-sm flex items-center gap-2">
            <span className="text-xl">👥</span>
            <div>
              <p className="text-xs text-gray-400 font-medium">Personalkosten</p>
              <p className="font-bold text-ink">{fmtEUR(displayData.personalkosten)}</p>
            </div>
          </div>
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

        {/* Disclaimer */}
        <div className="bg-blue-50 border border-blue-100 rounded-lg p-4 mb-8 text-sm text-gray-600">
          <p>
            Schätzung basiert auf{' '}
            <strong className="text-primary">EU-Ausschreibungen aus dem TED-Portal</strong>.{' '}
            Konfidenz:{' '}
            <strong className={confidence.color}>{confidence.text}</strong>
            {displayData.confidence_score != null
              ? ` (${Math.round(displayData.confidence_score * 100)}%)`
              : ''}
          </p>
          <p className="mt-1 text-xs text-gray-400">
            Diese Schätzung dient als Orientierungswert. Individuelle Faktoren können stark abweichen.
          </p>
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
