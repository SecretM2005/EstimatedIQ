import { Routes, Route, Navigate } from 'react-router-dom'
import { supabase }     from './lib/supabase'
import { useAuth }      from './auth/AuthProvider'
import Sidebar          from './components/Sidebar'
import Login            from './pages/Login'
import Dashboard        from './pages/Dashboard'
import Angebote         from './pages/Angebote'
import Projekte         from './pages/Projekte'
import ProjektDetail    from './pages/ProjektDetail'
import Nachkalkulation  from './pages/Nachkalkulation'
import Rollen           from './pages/Rollen'
import Benutzer         from './pages/Benutzer'
import HistorischImport from './pages/HistorischImport'

export default function App() {
  const { session, loading, me } = useAuth()

  // Login nur, wenn Supabase konfiguriert ist (sonst lokale Entwicklung ohne Auth)
  if (supabase) {
    if (loading) {
      return (
        <div className="h-full flex items-center justify-center bg-slate-50">
          <span className="text-sm text-slate-400">Lade…</span>
        </div>
      )
    }
    if (!session) return <Login />
  }

  return (
    <div className="flex h-full overflow-hidden bg-slate-50">
      <Sidebar />
      <div className="flex-1 min-w-0 overflow-y-auto">
        <Routes>
          <Route path="/"                              element={<Dashboard />} />
          <Route path="/angebote"                      element={<Angebote />} />
          <Route path="/angebote/:id"                  element={<ProjektDetail />} />
          <Route path="/projekte"                      element={<Projekte />} />
          <Route path="/projekte/:id"                  element={<ProjektDetail />} />
          <Route path="/projekte/:id/nachkalkulation"  element={<Nachkalkulation />} />
          <Route path="/rollen"                        element={<Rollen />} />
          <Route path="/benutzer"                      element={me?.rolle === 'admin' ? <Benutzer /> : <Navigate to="/" replace />} />
          <Route path="/historisch"                    element={<HistorischImport />} />
          <Route path="*"                              element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </div>
  )
}
