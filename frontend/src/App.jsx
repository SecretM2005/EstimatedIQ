import { Routes, Route, Navigate } from 'react-router-dom'
import Landing from './pages/Landing'
import Result from './pages/Result'
import Upload from './pages/Upload'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/result" element={<Result />} />
      <Route path="/upload" element={<Upload />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
