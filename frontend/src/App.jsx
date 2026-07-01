import { Routes, Route, Navigate } from 'react-router-dom'
import Projekte          from './pages/Projekte'
import ProjektDetail     from './pages/ProjektDetail'
import Nachkalkulation   from './pages/Nachkalkulation'
import Rollen            from './pages/Rollen'
import HistorischImport  from './pages/HistorischImport'

export default function App() {
  return (
    <Routes>
      <Route path="/"                           element={<Projekte />} />
      <Route path="/projekte"                   element={<Projekte />} />
      <Route path="/projekte/:id"               element={<ProjektDetail />} />
      <Route path="/projekte/:id/nachkalkulation" element={<Nachkalkulation />} />
      <Route path="/rollen"                     element={<Rollen />} />
      <Route path="/historisch"                 element={<HistorischImport />} />
      <Route path="*"                           element={<Navigate to="/" replace />} />
    </Routes>
  )
}
