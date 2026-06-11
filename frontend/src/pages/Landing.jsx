import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

const REGIONS = [
  { value: 'DE-BY', label: 'Bayern (DE-BY)' },
  { value: 'DE-BW', label: 'Baden-Württemberg (DE-BW)' },
  { value: 'DE-NW', label: 'Nordrhein-Westfalen (DE-NW)' },
  { value: 'DE-BE', label: 'Berlin (DE-BE)' },
  { value: 'DE-HH', label: 'Hamburg (DE-HH)' },
  { value: 'DE-HE', label: 'Hessen (DE-HE)' },
  { value: 'DE',    label: 'Deutschland (gesamt)' },
  { value: 'AT',    label: 'Österreich' },
  { value: 'CH',    label: 'Schweiz' },
]

const PLACEHOLDER = `z. B. "React-Webanwendung mit SAP-Schnittstelle und Nutzerverwaltung für 200 Mitarbeiter. Anbindung an bestehendes ERP-System, Single Sign-On via Azure AD, mobil-optimiertes Design. Projektstart Q3, Deadline Ende Jahr."`

export default function Landing() {
  const navigate  = useNavigate()
  const [beschreibung, setBeschreibung] = useState('')
  const [region, setRegion]             = useState('DE-BY')
  const [error, setError]               = useState('')

  function handleSubmit(e) {
    e.preventDefault()
    if (beschreibung.trim().length < 20) {
      setError('Bitte beschreibe dein Projekt mit mindestens 20 Zeichen.')
      return
    }
    setError('')
    navigate('/result', { state: { beschreibung: beschreibung.trim(), region } })
  }

  return (
    <div className="min-h-screen bg-light flex flex-col">
      {/* Nav */}
      <header className="px-6 py-5 flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
          <span className="text-white font-bold text-sm">IQ</span>
        </div>
        <span className="font-bold text-primary text-lg tracking-tight">EstimateIQ</span>
      </header>

      {/* Hero */}
      <main className="flex-1 flex flex-col items-center justify-center px-4 py-12">
        <div className="w-full max-w-2xl">
          {/* Badge */}
          <div className="flex justify-center mb-6">
            <span className="inline-flex items-center gap-1.5 bg-blue-100 text-accent text-xs font-semibold px-3 py-1 rounded-full">
              <span className="w-1.5 h-1.5 rounded-full bg-accent inline-block" />
              ML-gestützt · 6.899 EU-Ausschreibungen
            </span>
          </div>

          <h1 className="text-4xl md:text-5xl font-extrabold text-primary text-center leading-tight mb-3">
            Projektkostenrahmen in Sekunden
          </h1>
          <p className="text-gray-500 text-center text-lg mb-10">
            Für IT-Dienstleister und Agenturen in DACH
          </p>

          {/* Form */}
          <form onSubmit={handleSubmit} noValidate>
            <div className="bg-white rounded-xl shadow-sm border border-blue-100 overflow-hidden mb-4">
              <textarea
                value={beschreibung}
                onChange={e => { setBeschreibung(e.target.value); if (error) setError('') }}
                placeholder={PLACEHOLDER}
                rows={6}
                className="w-full px-5 pt-5 pb-3 text-ink placeholder-gray-400 text-base resize-none focus:outline-none leading-relaxed"
                aria-label="Projektbeschreibung"
              />
              <div className="flex items-center gap-3 px-5 py-3 border-t border-gray-100 bg-gray-50">
                <label className="text-sm font-medium text-gray-600 shrink-0">Region:</label>
                <select
                  value={region}
                  onChange={e => setRegion(e.target.value)}
                  className="flex-1 bg-transparent text-ink text-sm focus:outline-none cursor-pointer"
                  aria-label="Region auswählen"
                >
                  {REGIONS.map(r => (
                    <option key={r.value} value={r.value}>{r.label}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* Inline validation error */}
            {error && (
              <p className="text-red-500 text-sm mb-4 flex items-center gap-1.5">
                <span>⚠</span> {error}
              </p>
            )}

            <button
              type="submit"
              className="btn-primary w-full text-base py-4 rounded-xl"
            >
              Projekt kalkulieren →
            </button>
          </form>

          {/* Trust badges */}
          <div className="flex justify-center gap-6 mt-8 text-xs text-gray-400 flex-wrap">
            <span>✓ Keine Registrierung</span>
            <span>✓ TED-Daten 2022–2024</span>
            <span>✓ DACH-Stundensätze</span>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="text-center py-4 text-xs text-gray-400">
        EstimateIQ · Nur für interne Kalkulationszwecke
      </footer>
    </div>
  )
}
