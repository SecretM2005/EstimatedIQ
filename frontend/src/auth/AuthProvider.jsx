import { createContext, useContext, useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'
import { getMe } from '../api/angebot'

const AuthContext = createContext({ session: null, user: null, me: null, loading: false, signOut: () => {} })

export const useAuth = () => useContext(AuthContext)

export default function AuthProvider({ children }) {
  const [session, setSession] = useState(null)
  const [me,      setMe]      = useState(null)
  const [loading, setLoading] = useState(!!supabase)

  // Lädt das eigene Konto (rolle, user_id, email, tenant_name) – robust gegen Fehler
  const ladeMe = () => getMe().then(setMe).catch(() => setMe(null))

  useEffect(() => {
    // Ohne Supabase (lokale Entwicklung): direkt /me laden, kein Login-Gate
    if (!supabase) {
      ladeMe()
      return
    }
    supabase.auth.getSession().then(async ({ data }) => {
      setSession(data.session)
      if (data.session) await ladeMe()
      setLoading(false)
    })
    const { data: sub } = supabase.auth.onAuthStateChange(async (_event, s) => {
      setSession(s)
      if (s) await ladeMe()
      else setMe(null)
    })
    return () => sub.subscription.unsubscribe()
  }, [])

  const signOut = () => supabase?.auth.signOut()

  return (
    <AuthContext.Provider value={{ session, user: session?.user ?? null, me, loading, signOut }}>
      {children}
    </AuthContext.Provider>
  )
}
