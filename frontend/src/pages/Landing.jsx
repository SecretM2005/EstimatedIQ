import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

const REGIONS = [
  { value: 'DE-HH', label: 'DE-Nord',     hint: 'Hamburg, Berlin'    },
  { value: 'DE-BY', label: 'DE-Süd',      hint: 'München, Stuttgart' },
  { value: 'DE-NW', label: 'DE-West',     hint: 'Köln, Frankfurt'    },
  { value: 'DE',    label: 'DE-Ost',      hint: 'Dresden, Leipzig'   },
  { value: 'AT',    label: 'Österreich',  hint: 'Wien, Graz'         },
  { value: 'CH',    label: 'Schweiz',     hint: 'Zürich, Basel'      },
]

const TECHNOLOGIEN = [
  { value: 'react',     label: 'React/Vue/Angular'    },
  { value: 'java',      label: 'Java/.NET'            },
  { value: 'python',    label: 'Python/ML'            },
  { value: 'sap',       label: 'SAP'                  },
  { value: 'php',       label: 'PHP/WordPress'        },
  { value: 'mobile',    label: 'Mobile (iOS/Android)' },
  { value: 'cloud',     label: 'Cloud/DevOps'         },
  { value: 'sonstiges', label: 'Sonstiges'            },
]

const PROJEKTTYPEN = [
  { value: 'neuentwicklung',    label: 'Neuentwicklung'    },
  { value: 'weiterentwicklung', label: 'Weiterentwicklung' },
  { value: 'migration',         label: 'Migration'         },
]

const TEAMGROESSEN = [
  { value: 1,  label: '1'    },
  { value: 2,  label: '2'    },
  { value: 4,  label: '3–5'  },
  { value: 7,  label: '5–10' },
  { value: 15, label: '10+'  },
]

const MIN_ZEICHEN = 50
const MAX_ZEICHEN = 500

function teamzuGroesse(t) {
  if (t <= 1) return 'klein'
  if (t <= 4) return 'mittel'
  return 'gross'
}

function ChevronIcon({ open }) {
  return (
    <svg
      width="16" height="16" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      style={{ transform: open ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }}
    >
      <polyline points="9 18 15 12 9 6" />
    </svg>
  )
}

function ArrowRightIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
    >
      <line x1="5" y1="12" x2="19" y2="12" />
      <polyline points="12 5 19 12 12 19" />
    </svg>
  )
}

export default function Landing() {
  const navigate = useNavigate()

  const [beschreibung, setBeschreibung] = useState('')
  const [region,       setRegion]       = useState('DE-BY')
  const [technologien, setTechnologien] = useState([])
  const [projekttyp,   setProjekttyp]   = useState('neuentwicklung')
  const [teamIdx,      setTeamIdx]      = useState(1)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [error,        setError]        = useState('')

  const zeichen   = beschreibung.length
  const canSubmit = zeichen >= MIN_ZEICHEN

  function toggleTech(value) {
    setTechnologien(prev => {
      if (prev.includes(value)) return prev.filter(v => v !== value)
      if (prev.length >= 3) return prev
      return [...prev, value]
    })
  }

  function handleSubmit(e) {
    e.preventDefault()
    if (!canSubmit) {
      setError(`Bitte beschreibe dein Projekt mit mindestens ${MIN_ZEICHEN} Zeichen.`)
      return
    }
    setError('')

    const teamgroesse    = TEAMGROESSEN[teamIdx].value
    const projektGroesse = teamzuGroesse(teamgroesse)

    let volltext = beschreibung.trim()
    if (technologien.length > 0) {
      const techLabels = technologien.map(v => TECHNOLOGIEN.find(t => t.value === v)?.label ?? v)
      volltext += `\nTechnologien: ${techLabels.join(', ')}`
    }
    const ptLabel = PROJEKTTYPEN.find(p => p.value === projekttyp)?.label ?? projekttyp
    volltext += `\nProjekttyp: ${ptLabel}`

    navigate('/result', {
      state: { beschreibung: volltext, region, projektGroesse, teamgroesse },
    })
  }

  return (
    <div className="min-h-screen bg-light flex flex-col">
      {/* Nav */}
      <header className="px-6 py-5 flex items-center gap-3 border-b border-slate-100">
        <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
          <span className="text-white font-bold text-sm">IQ</span>
        </div>
        <span className="font-bold text-primary text-lg tracking-tight">EstimateIQ</span>
      </header>

      <main className="flex-1 flex flex-col items-center justify-center px-4 py-12">
        <div className="w-full max-w-2xl">
          {/* Badge */}
          <div className="flex justify-center mb-6">
            <span className="inline-flex items-center gap-1.5 bg-indigo-50 text-accent text-xs font-semibold px-3 py-1 rounded-full border border-indigo-100">
              <span className="w-1.5 h-1.5 rounded-full bg-accent inline-block" />
              ML-gestützt · DACH-Projekte
            </span>
          </div>

          <h1 className="text-4xl md:text-[40px] font-bold text-primary text-center leading-tight tracking-tight mb-3">
            Neue Kostenschätzung
          </h1>
          <p className="text-slate-500 text-center text-base mb-10 max-w-lg mx-auto">
            Beschreibe das Projekt – das Modell schätzt Kosten und Dauer anhand vergleichbarer DACH-Projekte.
          </p>

          <form onSubmit={handleSubmit} noValidate className="space-y-3">

            {/* 1. Projektbeschreibung */}
            <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
              <textarea
                value={beschreibung}
                onChange={e => {
                  setBeschreibung(e.target.value.slice(0, MAX_ZEICHEN))
                  if (error) setError('')
                }}
                placeholder="z.B. React-Webanwendung mit SAP-Schnittstelle und Nutzerverwaltung für 200 Mitarbeiter – inkl. Mobile App"
                rows={5}
                className="w-full px-5 pt-5 pb-2 text-ink placeholder-slate-400 text-base resize-none focus:outline-none leading-relaxed"
                aria-label="Projektbeschreibung"
              />
              <div className="px-5 pb-3 flex justify-between items-center border-t border-slate-100">
                <span className={`text-xs font-medium ${zeichen < MIN_ZEICHEN ? 'text-slate-400' : 'text-emerald-600'}`}>
                  {zeichen < MIN_ZEICHEN
                    ? `Noch ${MIN_ZEICHEN - zeichen} Zeichen bis Mindestlänge`
                    : '✓ Ausreichend beschrieben'}
                </span>
                <span className={`text-xs ${zeichen >= MAX_ZEICHEN ? 'text-orange-500 font-medium' : 'text-slate-400'}`}>
                  {zeichen}/{MAX_ZEICHEN}
                </span>
              </div>
            </div>

            {/* 2. Region */}
            <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-4">
              <p className="section-label">Region</p>
              <div className="grid grid-cols-3 gap-2">
                {REGIONS.map(r => (
                  <button
                    key={r.value}
                    type="button"
                    onClick={() => setRegion(r.value)}
                    className={`text-left px-3 py-2.5 rounded-lg border text-sm transition-colors ${
                      region === r.value
                        ? 'border-accent bg-indigo-50 text-accent font-semibold'
                        : 'border-slate-200 text-slate-600 hover:border-slate-300 hover:bg-slate-50'
                    }`}
                  >
                    <p className="font-medium leading-tight">{r.label}</p>
                    <p className="text-xs text-slate-400 leading-tight mt-0.5">{r.hint}</p>
                  </button>
                ))}
              </div>
            </div>

            {/* 3. Technologie */}
            <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-4">
              <div className="flex justify-between items-center mb-3">
                <p className="section-label mb-0">Technologie</p>
                <span className="text-xs text-slate-400">max. 3 · {technologien.length}/3</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {TECHNOLOGIEN.map(t => {
                  const selected = technologien.includes(t.value)
                  const disabled = !selected && technologien.length >= 3
                  return (
                    <button
                      key={t.value}
                      type="button"
                      onClick={() => toggleTech(t.value)}
                      disabled={disabled}
                      className={`chip ${
                        selected ? 'chip-active' : disabled ? 'chip-disabled' : 'chip-inactive'
                      }`}
                    >
                      {t.label}
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Erweiterte Optionen */}
            <div>
              <button
                type="button"
                onClick={() => setShowAdvanced(v => !v)}
                className="flex items-center gap-2 text-sm text-slate-500 hover:text-primary transition-colors py-1.5"
              >
                <ChevronIcon open={showAdvanced} />
                Erweiterte Optionen
              </button>

              {showAdvanced && (
                <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {/* 4. Projekttyp */}
                  <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-4">
                    <p className="section-label">Projekttyp</p>
                    <div className="flex flex-col gap-2">
                      {PROJEKTTYPEN.map(p => {
                        const active = projekttyp === p.value
                        return (
                          <button
                            key={p.value}
                            type="button"
                            onClick={() => setProjekttyp(p.value)}
                            className={`text-left px-3 py-2 rounded-lg border text-sm transition-colors ${
                              active
                                ? 'border-accent bg-indigo-50 text-accent font-semibold'
                                : 'border-slate-200 text-slate-600 hover:border-slate-300'
                            }`}
                          >
                            {p.label}
                          </button>
                        )
                      })}
                    </div>
                  </div>

                  {/* 5. Teamgröße */}
                  <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-4">
                    <div className="flex justify-between items-center mb-4">
                      <p className="section-label mb-0">Verfügbares Team</p>
                      <span className="text-sm font-bold text-primary">
                        {TEAMGROESSEN[teamIdx].label}
                        {' '}
                        <span className="font-normal text-slate-500">
                          {TEAMGROESSEN[teamIdx].value === 1 ? 'Person' : 'Pers.'}
                        </span>
                      </span>
                    </div>
                    <input
                      type="range"
                      min={0}
                      max={TEAMGROESSEN.length - 1}
                      step={1}
                      value={teamIdx}
                      onChange={e => setTeamIdx(Number(e.target.value))}
                      className="w-full accent-indigo-500"
                      aria-label="Teamgröße"
                    />
                    <div className="flex justify-between mt-2">
                      {TEAMGROESSEN.map((t, i) => (
                        <span
                          key={i}
                          className={`text-xs ${i === teamIdx ? 'text-accent font-semibold' : 'text-slate-400'}`}
                        >
                          {t.label}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Validation error */}
            {error && (
              <p className="text-red-500 text-sm flex items-center gap-1.5">
                <span>⚠</span> {error}
              </p>
            )}

            {/* Submit row */}
            <div className="flex flex-col sm:flex-row items-center gap-4 pt-2">
              <p className="text-xs text-slate-400 flex-1 text-center sm:text-left">
                Keine Registrierung · TED-Daten 2022–2024 · DACH-Stundensätze
              </p>
              <button
                type="submit"
                disabled={!canSubmit}
                className={`sm:w-auto w-full text-base py-3 px-8 rounded-xl font-semibold transition-colors flex items-center justify-center gap-2 ${
                  canSubmit
                    ? 'bg-accent hover:bg-accent-hover text-white focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2'
                    : 'bg-slate-200 text-slate-400 cursor-not-allowed'
                }`}
              >
                Projekt kalkulieren
                {canSubmit && <ArrowRightIcon />}
              </button>
            </div>
          </form>
        </div>
      </main>

      <footer className="text-center py-4 text-xs text-slate-400 border-t border-slate-100">
        EstimateIQ · Nur für interne Kalkulationszwecke
      </footer>
    </div>
  )
}
