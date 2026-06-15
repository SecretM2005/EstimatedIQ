import { useEffect, useState } from 'react'

const MESSAGES = [
  'Analysiere Projektbeschreibung…',
  'Vergleiche mit ähnlichen Projekten…',
  'Berechne Kostenrahmen…',
]

export default function LoadingScreen() {
  const [step, setStep] = useState(0)

  useEffect(() => {
    const id = setInterval(() => {
      setStep(s => (s + 1) % MESSAGES.length)
    }, 1800)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="min-h-screen bg-light flex flex-col items-center justify-center px-4">
      {/* Logo mark */}
      <div className="w-14 h-14 rounded-xl bg-primary flex items-center justify-center mb-8 shadow-sm">
        <span className="text-white font-bold text-xl tracking-tight">IQ</span>
      </div>

      {/* Progress bar */}
      <div className="w-full max-w-sm h-1.5 bg-slate-200 rounded-full overflow-hidden mb-6">
        <div className="h-full w-1/3 bg-accent rounded-full animate-progress" />
      </div>

      {/* Cycling message */}
      <p
        key={step}
        className="text-primary font-medium text-base text-center"
        style={{ animation: 'fadeIn 0.4s ease' }}
      >
        {MESSAGES[step]}
      </p>

      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(6px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  )
}
