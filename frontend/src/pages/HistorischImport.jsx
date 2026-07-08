import { useState } from 'react'
import { Link } from 'react-router-dom'
import { importierePositionen } from '../api/angebot'

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
    <div className="p-8 pb-16">
      {/* Page header */}
      <div className="mb-6">
        <h1 className="text-[24px] font-bold tracking-tight text-slate-900 m-0">Daten importieren</h1>
        <p className="mt-1.5 text-[13.5px] text-slate-500">
          Lade historische Projektdaten als CSV oder Excel hoch — sie dienen als Referenzbasis für die Ähnlichkeitssuche.
        </p>
      </div>

      {/* Two-column layout */}
      <div className="grid xl:grid-cols-[1fr_360px] gap-5 items-start">
        {/* Left: Drop zone + upload */}
        <div className="flex flex-col gap-4">
          {/* Drop zone */}
          <div
            onDragOver={e => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={e => { e.preventDefault(); setDragOver(false); handleFile(e.dataTransfer.files[0]) }}
            onClick={() => document.getElementById('file-input').click()}
            className={`border-2 border-dashed rounded-xl p-16 text-center transition-colors cursor-pointer ${
              dragOver
                ? 'border-accent bg-indigo-50'
                : file
                ? 'border-accent/40 bg-indigo-50/40'
                : 'border-slate-200 bg-white hover:border-accent/50 hover:bg-slate-50'
            }`}
          >
            <input
              id="file-input" type="file" accept=".csv,.xlsx,.xls"
              className="hidden" onChange={e => handleFile(e.target.files[0])}
            />
            <div className="flex flex-col items-center gap-3">
              <svg width="36" height="36" viewBox="0 0 24 24" fill="none" className={file ? 'text-accent' : 'text-slate-300'}>
                <path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
              {file ? (
                <>
                  <div>
                    <p className="text-[14px] font-semibold text-slate-900">{file.name}</p>
                    <p className="text-[12px] text-slate-400 mt-0.5">{(file.size / 1024).toFixed(1)} KB · Klicken zum Ändern</p>
                  </div>
                </>
              ) : (
                <>
                  <div>
                    <p className="text-[14px] font-semibold text-slate-700">CSV oder Excel hierher ziehen</p>
                    <p className="text-[12.5px] text-slate-400 mt-0.5">oder klicken zum Auswählen</p>
                    <p className="text-[11.5px] text-slate-300 mt-1">.csv · .xlsx · .xls</p>
                  </div>
                </>
              )}
            </div>
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-[13px] text-red-700">{error}</div>
          )}

          <button
            onClick={handleUpload}
            disabled={!file || loading}
            className="h-11 w-full inline-flex items-center justify-center gap-2 px-4 bg-accent hover:bg-accent-hover text-white text-[13.5px] font-semibold rounded-lg transition-colors shadow-accent disabled:opacity-40"
          >
            {loading ? (
              <>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" className="animate-spin"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4" strokeDashoffset="10"/></svg>
                Importiere und berechne Embeddings…
              </>
            ) : (
              <>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/></svg>
                Importieren
              </>
            )}
          </button>

          {result && (
            <div className={`rounded-xl border p-5 ${
              result.importiert > 0 ? 'bg-emerald-50 border-emerald-200' : 'bg-amber-50 border-amber-200'
            }`}>
              <p className={`text-[14px] font-semibold mb-2 ${result.importiert > 0 ? 'text-emerald-800' : 'text-amber-800'}`}>
                {result.importiert > 0 ? `${result.importiert} Position${result.importiert !== 1 ? 'en' : ''} importiert` : 'Import fehlgeschlagen'}
              </p>
              <div className="text-[13px] text-slate-600 space-y-1">
                <p>Gesamt: {result.stats.gesamt} · Akzeptiert: {result.stats.akzeptiert} · Abgelehnt: {result.stats.abgelehnt}</p>
                {result.stats.spalten && (
                  <p className="text-[11.5px] text-slate-400">
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
                  <summary className="text-[12px] text-slate-500 cursor-pointer">{result.fehler.length} Zeilen übersprungen</summary>
                  <ul className="mt-2 text-[12px] text-slate-500 space-y-0.5 list-disc list-inside">
                    {result.fehler.slice(0, 10).map((f, i) => <li key={i}>{f}</li>)}
                    {result.fehler.length > 10 && <li>… und {result.fehler.length - 10} weitere</li>}
                  </ul>
                </details>
              )}
              {result.importiert > 0 && (
                <Link
                  to="/projekte"
                  className="inline-flex items-center gap-1.5 mt-4 h-9 px-4 bg-accent hover:bg-accent-hover text-white rounded-lg text-[13px] font-semibold transition-colors"
                >
                  Zu den Projekten
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
                </Link>
              )}
            </div>
          )}
        </div>

        {/* Right: Column guide + tips */}
        <div className="flex flex-col gap-4">
          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs">
            <h2 className="text-[13px] font-semibold text-slate-900 mb-4">Erwartete Spalten</h2>
            <div className="flex flex-col gap-5">
              <div>
                <p className="text-[10.5px] font-semibold uppercase tracking-wide text-slate-400 mb-2.5">Pflichtfelder</p>
                <div className="flex flex-col gap-2">
                  {[
                    ['Beschreibung', 'description, titel, position, leistung'],
                    ['Soll_Stunden', 'soll, stunden, estimated_hours, hours'],
                  ].map(([col, alts]) => (
                    <div key={col}>
                      <code className="text-[11.5px] bg-indigo-50 text-accent px-1.5 py-0.5 rounded font-mono">{col}</code>
                      <p className="text-[11px] text-slate-400 mt-0.5 pl-0.5">{alts}</p>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-[10.5px] font-semibold uppercase tracking-wide text-slate-400 mb-2.5">Optionale Felder</p>
                <div className="flex flex-col gap-2">
                  {[
                    ['Projekt', 'projektname, project — gruppiert Positionen'],
                    ['Stundensatz', 'satz, rate, hourly_rate'],
                    ['Rolle', 'role, funktion'],
                    ['Ist_Stunden', 'ist, actual, actual_hours'],
                  ].map(([col, desc]) => (
                    <div key={col}>
                      <code className="text-[11.5px] bg-slate-100 text-slate-700 px-1.5 py-0.5 rounded font-mono">{col}</code>
                      <p className="text-[11px] text-slate-400 mt-0.5 pl-0.5">{desc}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs">
            <h2 className="text-[13px] font-semibold text-slate-900 mb-3">Beispiel CSV</h2>
            <div className="bg-slate-50 rounded-lg p-3 overflow-x-auto">
              <pre className="text-[10.5px] text-slate-600 font-mono leading-relaxed whitespace-pre">{`Projekt,Beschreibung,Rolle,Soll_Stunden,Stundensatz
CRM-2024,Frontend Entwicklung,Senior Dev,40,120
CRM-2024,Backend API,Backend Dev,24,110
CRM-2024,Testing & QA,Tester,16,80
Portal,UX Konzept,Designer,12,95`}</pre>
            </div>
            <p className="text-[11px] text-slate-400 mt-2">
              Kopfzeile wird automatisch erkannt · UTF-8 oder ISO-8859-1
            </p>
          </div>

          <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
            <p className="text-[12px] font-semibold text-amber-800 mb-1">Hinweis</p>
            <p className="text-[11.5px] text-amber-700 leading-relaxed">
              Importierte Positionen werden als historische Referenzdaten gespeichert und für die KI-gestützte Ähnlichkeitssuche bei neuen Angeboten verwendet.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
