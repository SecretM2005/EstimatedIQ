import { useState } from 'react'
import { Link } from 'react-router-dom'
import { importierePositionen } from '../api/angebot'
import NavBar from '../components/NavBar'

export default function HistorischImport() {
  const [file,     setFile]     = useState(null)
  const [result,   setResult]   = useState(null)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)
  const [dragOver, setDragOver] = useState(false)

  const handleFile = (f) => {
    if (!f) return
    const ext = f.name.split('.').pop().toLowerCase()
    if (!['csv', 'xlsx', 'xls'].includes(ext)) {
      setError('Nur CSV und Excel-Dateien (.csv, .xlsx, .xls) werden unterstützt.')
      return
    }
    setFile(f); setError(null); setResult(null)
  }

  const handleUpload = async () => {
    if (!file) return
    setLoading(true); setError(null)
    try {
      const res = await importierePositionen(file)
      setResult(res)
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    } finally { setLoading(false) }
  }

  return (
    <div className="min-h-screen bg-light">
      <NavBar />

      <main className="max-w-2xl mx-auto px-4 py-10">
        <div className="mb-8">
          <h1 className="text-3xl font-extrabold text-primary">Historische Positionen importieren</h1>
          <p className="text-sm text-slate-500 mt-2">
            Lade alte Angebote oder Projektzeiterfassungen als CSV oder Excel hoch.
            Diese werden als Vergleichsbasis für die Ähnlichkeitssuche genutzt.
          </p>
        </div>

        {/* Spalten-Hinweis */}
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-6 text-sm">
          <p className="font-medium text-blue-800 mb-1">Pflicht-Spalten</p>
          <ul className="list-disc list-inside space-y-0.5 text-blue-700">
            <li><code className="bg-blue-100 px-1 rounded">Beschreibung</code> (oder: description, titel, position, leistung)</li>
            <li><code className="bg-blue-100 px-1 rounded">Soll_Stunden</code> (oder: soll, stunden, estimated_hours, hours)</li>
          </ul>
          <p className="font-medium text-blue-800 mb-1 mt-3">Optionale Spalten</p>
          <ul className="list-disc list-inside space-y-0.5 text-blue-700">
            <li><code className="bg-blue-100 px-1 rounded">Rolle</code> (oder: role, funktion)</li>
            <li><code className="bg-blue-100 px-1 rounded">Ist_Stunden</code> (oder: ist, actual, actual_hours)</li>
          </ul>
        </div>

        {/* Drop Zone */}
        <div
          onDragOver={e => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={e => { e.preventDefault(); setDragOver(false); handleFile(e.dataTransfer.files[0]) }}
          onClick={() => document.getElementById('file-input').click()}
          className={`border-2 border-dashed rounded-xl p-10 text-center transition-colors cursor-pointer ${
            dragOver ? 'border-primary bg-blue-50' : 'border-slate-300 bg-white hover:border-primary'
          }`}
        >
          <input
            id="file-input" type="file" accept=".csv,.xlsx,.xls"
            className="hidden" onChange={e => handleFile(e.target.files[0])}
          />
          {file ? (
            <div>
              <p className="font-medium text-ink">{file.name}</p>
              <p className="text-xs text-slate-400 mt-1">{(file.size / 1024).toFixed(1)} KB · Klicken zum Ändern</p>
            </div>
          ) : (
            <div>
              <p className="font-medium text-slate-600">CSV oder Excel hierher ziehen</p>
              <p className="text-xs text-slate-400 mt-1">oder klicken zum Auswählen</p>
            </div>
          )}
        </div>

        {error && (
          <div className="mt-4 bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm text-red-700">{error}</div>
        )}

        <button
          onClick={handleUpload}
          disabled={!file || loading}
          className="btn-primary w-full mt-4 py-3 disabled:opacity-50"
        >
          {loading ? 'Importiere und berechne Embeddings…' : 'Importieren'}
        </button>

        {result && (
          <div className={`mt-6 rounded-xl border p-5 ${
            result.importiert > 0 ? 'bg-emerald-50 border-emerald-200' : 'bg-amber-50 border-amber-200'
          }`}>
            <p className={`font-semibold mb-2 ${result.importiert > 0 ? 'text-emerald-800' : 'text-amber-800'}`}>
              {result.importiert > 0 ? `${result.importiert} Positionen importiert` : 'Import fehlgeschlagen'}
            </p>
            <div className="text-sm text-slate-600 space-y-1">
              <p>Gesamt: {result.stats.gesamt} · Akzeptiert: {result.stats.akzeptiert} · Abgelehnt: {result.stats.abgelehnt}</p>
              {result.stats.spalten && (
                <p className="text-xs text-slate-400">
                  Erkannte Spalten:{' '}
                  {Object.entries(result.stats.spalten)
                    .filter(([, v]) => v)
                    .map(([k, v]) => `${k} → ${v}`)
                    .join(', ')}
                </p>
              )}
            </div>
            {result.fehler?.length > 0 && (
              <details className="mt-3">
                <summary className="text-xs text-slate-500 cursor-pointer">{result.fehler.length} Zeilen übersprungen</summary>
                <ul className="mt-2 text-xs text-slate-500 space-y-0.5 list-disc list-inside">
                  {result.fehler.slice(0, 10).map((f, i) => <li key={i}>{f}</li>)}
                  {result.fehler.length > 10 && <li>… und {result.fehler.length - 10} weitere</li>}
                </ul>
              </details>
            )}
            {result.importiert > 0 && (
              <Link to="/projekte" className="btn-primary inline-block mt-4 text-sm py-2 px-4">
                Zu den Projekten →
              </Link>
            )}
          </div>
        )}
      </main>
    </div>
  )
}
