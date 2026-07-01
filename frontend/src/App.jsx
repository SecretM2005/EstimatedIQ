import { Routes, Route, Navigate } from 'react-router-dom'
import Landing        from './pages/Landing'
import Result         from './pages/Result'
import Upload         from './pages/Upload'
import Projekte       from './pages/Projekte'
import ProjektDetail  from './pages/ProjektDetail'
import Rollen         from './pages/Rollen'
import HistorischImport from './pages/HistorischImport'

export default function App() {
  return (
    <Routes>
      {/* Neue Hauptseite */}
      <Route path="/"               element={<Projekte />} />
      <Route path="/projekte"       element={<Projekte />} />
      <Route path="/projekte/:id"   element={<ProjektDetail />} />
      <Route path="/rollen"         element={<Rollen />} />
      <Route path="/historisch"     element={<HistorischImport />} />

      {/* Alte ML-Kostenschätzung unter /schaetzung */}
      <Route path="/schaetzung"     element={<Landing />} />
      <Route path="/result"         element={<Result />} />
      <Route path="/upload"         element={<Upload />} />

      <Route path="*"               element={<Navigate to="/" replace />} />
    </Routes>
  )
}
