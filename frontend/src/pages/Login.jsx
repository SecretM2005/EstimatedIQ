import { useState } from 'react'
import { supabase } from '../lib/supabase'

const Logo = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <path d="M5 4v16" stroke="#eef2ff" strokeWidth="2.4" strokeLinecap="round"/>
    <path d="M5 12l9-8M5 12l9 8" stroke="#6366f1" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
)

export default function Login() {
  const [email,    setEmail]    = useState('')
  const [passwort, setPasswort] = useState('')
  const [fehler,   setFehler]   = useState(null)
  const [laedt,    setLaedt]    = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setFehler(null)
    setLaedt(true)
    const { error } = await supabase.auth.signInWithPassword({ email, password: passwort })
    setLaedt(false)
    if (error) {
      setFehler(
        error.message === 'Invalid login credentials'
          ? 'E-Mail oder Passwort ist falsch.'
          : `Anmeldung fehlgeschlagen: ${error.message}`
      )
    }
    // Bei Erfolg übernimmt onAuthStateChange im AuthProvider.
  }

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
      <div className="w-full max-w-[400px]">
        {/* Logo */}
        <div className="flex items-center justify-center gap-2.5 mb-8">
          <div className="w-10 h-10 rounded-xl bg-slate-900 flex items-center justify-center">
            <Logo />
          </div>
          <span className="text-[20px] font-bold tracking-tight text-slate-900">EstimateIQ</span>
        </div>

        <form onSubmit={handleSubmit} className="bg-white border border-slate-200 rounded-2xl shadow-xs p-8 flex flex-col gap-5">
          <div>
            <h1 className="text-[18px] font-bold text-slate-900 m-0">Anmelden</h1>
            <p className="mt-1 text-[13px] text-slate-500">Zugang zur Angebots- und Projektkalkulation</p>
          </div>

          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">
              E-Mail
            </label>
            <input
              type="email" value={email} onChange={e => setEmail(e.target.value)}
              required autoComplete="email" placeholder="name@firma.de"
              className="w-full border border-slate-200 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"
            />
          </div>

          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">
              Passwort
            </label>
            <input
              type="password" value={passwort} onChange={e => setPasswort(e.target.value)}
              required autoComplete="current-password" placeholder="••••••••"
              className="w-full border border-slate-200 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"
            />
          </div>

          {fehler && (
            <div className="bg-red-50 border border-red-100 text-red-700 text-[13px] rounded-lg px-3.5 py-2.5">
              {fehler}
            </div>
          )}

          <button
            type="submit" disabled={laedt}
            className="h-11 bg-accent hover:bg-accent-hover text-white text-[14px] font-semibold rounded-lg transition-colors shadow-accent disabled:opacity-50"
          >
            {laedt ? 'Anmelden…' : 'Anmelden'}
          </button>
        </form>

        <p className="mt-5 text-center text-[12px] text-slate-400">
          Kein Zugang? Wende dich an deinen Administrator.
        </p>
      </div>
    </div>
  )
}
