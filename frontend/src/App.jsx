import { Routes, Route, Navigate } from 'react-router-dom'
import Sidebar          from './components/Sidebar'
import Projekte          from './pages/Projekte'
import ProjektDetail     from './pages/ProjektDetail'
import Nachkalkulation   from './pages/Nachkalkulation'
import Rollen            from './pages/Rollen'
import HistorischImport  from './pages/HistorischImport'

export default function App() {
  return (
    <div className="flex h-full overflow-hidden bg-slate-50">
      <Sidebar />
      <div className="flex-1 min-w-0 overflow-y-auto">
        <Routes>
          <Route path="/"                              element={<Navigate to="/projekte" replace />} />
          <Route path="/projekte"                      element={<Projekte />} />
          <Route path="/projekte/:id"                  element={<ProjektDetail />} />
          <Route path="/projekte/:id/nachkalkulation"  element={<Nachkalkulation />} />
          <Route path="/rollen"                        element={<Rollen />} />
          <Route path="/historisch"                    element={<HistorischImport />} />
          <Route path="*"                              element={<Navigate to="/projekte" replace />} />
        </Routes>
      </div>
    </div>
  )
}
