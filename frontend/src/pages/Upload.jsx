import { useState, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function UploadIcon() {
  return (
    <svg width="40" height="40" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
      className="text-slate-400">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
  )
}

function CheckIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  )
}

function XIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  )
}

function ArrowLeftIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" />
    </svg>
  )
}

function DownloadIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  )
}

function Spinner() {
  return (
    <svg className="animate-spin" width="18" height="18" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2">
      <path d="M21 12a9 9 0 1 1-6.219-8.56" />
    </svg>
  )
}

function fmtBytes(b) {
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
  return `${(b / 1024 / 1024).toFixed(1)} MB`
}

const SPALTEN_LABELS = {
  beschreibung: 'Projektbeschreibung',
  dauer_tage:   'Laufzeit (Tage)',
  region:       'Region',
  technologie:  'Technologie',
  projekttyp:   'Projekttyp',
  teamgroesse:  'Teamgröße',
  jahr:         'Jahr',
  kosten:       'Budget/Kosten',
}

export default function Upload() {
  const navigate  = useNavigate()
  const fileInput = useRef(null)

  const [dragOver,    setDragOver]    = useState(false)
  const [file,        setFile]        = useState(null)
  const [status,      setStatus]      = useState('idle')    // idle | uploading | success | error | retraining | retrained
  const [result,      setResult]      = useState(null)
  const [errorMsg,    setErrorMsg]    = useState('')
  const [retainInfo,  setRetainInfo]  = useState(null)
  const [prevMdape,   setPrevMdape]   = useState(null)

  const handleFile = useCallback((f) => {
    if (!f) return
    const ext = f.name.split('.').pop().toLowerCase()
    if (!['csv', 'xlsx', 'xls'].includes(ext)) {
      setErrorMsg('Nur .csv und .xlsx Dateien erlaubt.')
      setStatus('error')
      return
    }
    if (f.size > 10 * 1024 * 1024) {
      setErrorMsg('Datei zu groß. Maximum: 10 MB.')
      setStatus('error')
      return
    }
    setFile(f)
    setStatus('idle')
    setResult(null)
    setErrorMsg('')
  }, [])

  const onDrop = useCallback((e) => {
    e.preventDefault()
    setDragOver(false)
    handleFile(e.dataTransfer.files[0])
  }, [handleFile])

  const onDragOver = (e) => { e.preventDefault(); setDragOver(true) }
  const onDragLeave = () => setDragOver(false)

  async function handleUpload() {
    if (!file) return
    setStatus('uploading')
    setResult(null)
    setErrorMsg('')

    const form = new FormData()
    form.append('file', file)

    try {
      const res = await fetch(`${API_BASE}/api/upload-training-data`, {
        method: 'POST',
        body: form,
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      setResult(data)
      setStatus('success')
    } catch (err) {
      setErrorMsg(err.message)
      setStatus('error')
    }
  }

  async function handleRetrain() {
    setStatus('retraining')
    // Aktuelles MdAPE als "vorher" speichern (falls vorhanden)
    setPrevMdape(retainInfo?.mdape ?? null)

    try {
      const startRes = await fetch(`${API_BASE}/api/retrain`, { method: 'POST' })
      if (!startRes.ok) {
        const d = await startRes.json()
        throw new Error(d.detail || `HTTP ${startRes.status}`)
      }
    } catch (err) {
      setErrorMsg(err.message)
      setStatus('success')  // zurück zu success state, button wieder sichtbar
      return
    }

    // Polling alle 2 Sekunden
    const poll = setInterval(async () => {
      try {
        const res  = await fetch(`${API_BASE}/api/retrain/status`)
        const data = await res.json()

        if (data.status === 'done') {
          clearInterval(poll)
          setRetainInfo(data)
          setStatus('retrained')
        } else if (data.status === 'error') {
          clearInterval(poll)
          setErrorMsg(`Training fehlgeschlagen: ${data.error}`)
          setStatus('success')
        }
      } catch {
        // kurz ignorieren, nächster Poll
      }
    }, 2000)
  }

  const canUpload   = file && status !== 'uploading'
  const canRetrain  = status === 'success' && result?.stats?.zeilen_akzeptiert > 0
  const isLoading   = status === 'uploading' || status === 'retraining'

  return (
    <div className="min-h-screen bg-light flex flex-col">
      {/* Nav */}
      <header className="px-6 py-4 flex items-center justify-between bg-white border-b border-slate-200 no-print">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
            <span className="text-white font-bold text-sm">IQ</span>
          </div>
          <span className="font-bold text-primary text-lg tracking-tight">EstimateIQ</span>
        </div>
        <button onClick={() => navigate('/')} className="btn-secondary text-sm py-2">
          <ArrowLeftIcon />
          Neue Schätzung
        </button>
      </header>

      <main className="max-w-2xl mx-auto px-4 py-10 w-full">
        <h1 className="text-[28px] font-bold text-primary mb-1 tracking-tight">
          Eigene Projektdaten hochladen
        </h1>
        <p className="text-slate-500 text-sm mb-8">
          Verbessere die Schätzgenauigkeit mit deinen historischen Projekten.
          Pflichtfelder: Projektbeschreibung und Laufzeit in Tagen.
        </p>

        {/* Drop Zone */}
        <div
          onDrop={onDrop}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onClick={() => !file && fileInput.current?.click()}
          className={`
            relative border-2 border-dashed rounded-xl p-10 flex flex-col items-center
            justify-center gap-4 transition-colors cursor-pointer mb-4
            ${dragOver
              ? 'border-accent bg-indigo-50'
              : file
              ? 'border-slate-200 bg-white cursor-default'
              : 'border-slate-200 hover:border-accent hover:bg-indigo-50/40'}
          `}
        >
          <input
            ref={fileInput}
            type="file"
            accept=".csv,.xlsx,.xls"
            className="hidden"
            onChange={e => handleFile(e.target.files[0])}
          />

          {file ? (
            <div className="flex flex-col items-center gap-2 text-center">
              <div className="w-12 h-12 bg-indigo-50 rounded-xl flex items-center justify-center">
                <span className="text-2xl">📄</span>
              </div>
              <p className="font-semibold text-primary text-sm">{file.name}</p>
              <p className="text-xs text-slate-400">{fmtBytes(file.size)}</p>
              <button
                type="button"
                onClick={e => { e.stopPropagation(); setFile(null); setStatus('idle'); setResult(null) }}
                className="text-xs text-slate-400 hover:text-red-500 transition-colors mt-1"
              >
                × Entfernen
              </button>
            </div>
          ) : (
            <>
              <UploadIcon />
              <div className="text-center">
                <p className="font-semibold text-slate-700 text-sm">
                  CSV oder Excel hier ablegen
                </p>
                <p className="text-xs text-slate-400 mt-1">
                  oder klicken zum Auswählen · .csv · .xlsx · max. 10 MB
                </p>
              </div>
            </>
          )}
        </div>

        {/* Pflichtfelder Hinweis + Vorlage */}
        <div className="flex items-center justify-between mb-6">
          <p className="text-xs text-slate-400">
            Pflichtfelder: <span className="font-medium text-slate-600">beschreibung</span>,{' '}
            <span className="font-medium text-slate-600">dauer_tage</span>
          </p>
          <a
            href={`${API_BASE}/api/download-template`}
            className="btn-secondary text-xs py-1.5 px-3"
          >
            <DownloadIcon />
            Vorlage herunterladen
          </a>
        </div>

        {/* Upload Button */}
        {file && status !== 'success' && status !== 'retrained' && (
          <button
            onClick={handleUpload}
            disabled={!canUpload || isLoading}
            className={`w-full py-3 rounded-xl font-semibold text-sm transition-colors flex items-center justify-center gap-2 mb-6 ${
              isLoading || !canUpload
                ? 'bg-slate-200 text-slate-400 cursor-not-allowed'
                : 'bg-accent hover:bg-accent-hover text-white'
            }`}
          >
            {status === 'uploading' ? <><Spinner /> Wird hochgeladen…</> : 'Datei hochladen'}
          </button>
        )}

        {/* Error State */}
        {status === 'error' && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-4 mb-6">
            <div className="flex gap-3 items-start">
              <span className="text-red-500 shrink-0 mt-0.5">
                <XIcon size={18} />
              </span>
              <div>
                <p className="font-semibold text-red-700 text-sm mb-1">Upload fehlgeschlagen</p>
                <p className="text-red-600 text-xs leading-relaxed">{errorMsg}</p>
                <button
                  onClick={() => { setStatus('idle'); setFile(null) }}
                  className="text-xs text-red-500 hover:text-red-700 mt-2 underline"
                >
                  Erneut versuchen
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Success / Results */}
        {(status === 'success' || status === 'retraining' || status === 'retrained') && result && (
          <div className="space-y-4">
            {/* Stats */}
            <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
              <h2 className="font-semibold text-primary text-sm mb-4">Upload-Ergebnis</h2>

              <div className="grid grid-cols-3 gap-3 mb-4">
                <div className="bg-slate-50 rounded-lg px-3 py-2.5 text-center">
                  <p className="text-xl font-bold text-primary">{result.stats.zeilen_gesamt}</p>
                  <p className="text-xs text-slate-400 mt-0.5">Zeilen gesamt</p>
                </div>
                <div className="bg-emerald-50 rounded-lg px-3 py-2.5 text-center">
                  <p className="text-xl font-bold text-emerald-700">{result.stats.zeilen_akzeptiert}</p>
                  <p className="text-xs text-emerald-600 mt-0.5">Akzeptiert</p>
                </div>
                <div className={`rounded-lg px-3 py-2.5 text-center ${
                  result.stats.zeilen_verworfen > 0 ? 'bg-red-50' : 'bg-slate-50'
                }`}>
                  <p className={`text-xl font-bold ${
                    result.stats.zeilen_verworfen > 0 ? 'text-red-600' : 'text-slate-400'
                  }`}>{result.stats.zeilen_verworfen}</p>
                  <p className="text-xs text-slate-400 mt-0.5">Verworfen</p>
                </div>
              </div>

              {/* Verwurfsdetails */}
              {Object.keys(result.stats.verworfene_gruende).length > 0 && (
                <div className="border-t border-slate-100 pt-3 mb-4">
                  <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                    Verwurfsdetails
                  </p>
                  {result.stats.verworfene_gruende.beschreibung_zu_kurz > 0 && (
                    <p className="text-xs text-slate-500 flex items-center gap-1.5">
                      <span className="text-red-400"><XIcon size={12} /></span>
                      {result.stats.verworfene_gruende.beschreibung_zu_kurz}× Beschreibung zu kurz (min. 20 Zeichen)
                    </p>
                  )}
                  {result.stats.verworfene_gruende.dauer_ausserhalb_bereich > 0 && (
                    <p className="text-xs text-slate-500 flex items-center gap-1.5 mt-1">
                      <span className="text-red-400"><XIcon size={12} /></span>
                      {result.stats.verworfene_gruende.dauer_ausserhalb_bereich}× Laufzeit außerhalb 7–730 Tage
                    </p>
                  )}
                </div>
              )}

              {/* Erkannte Spalten */}
              <div className="border-t border-slate-100 pt-3">
                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                  Erkannte Spalten
                </p>
                <div className="grid grid-cols-1 gap-1">
                  {Object.entries(SPALTEN_LABELS).map(([intern, label]) => {
                    const gefunden = result.stats.spalten_erkannt[intern]
                    return (
                      <div key={intern} className="flex items-center justify-between text-xs py-0.5">
                        <span className="font-medium text-slate-600">{label}</span>
                        {gefunden ? (
                          <span className="flex items-center gap-1 text-emerald-600">
                            <CheckIcon size={12} />
                            <span className="font-mono bg-emerald-50 px-1.5 py-0.5 rounded text-xs">
                              {gefunden}
                            </span>
                          </span>
                        ) : (
                          <span className="flex items-center gap-1 text-slate-400">
                            <XIcon size={12} />
                            <span className="text-slate-400">nicht gefunden</span>
                          </span>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>

            {/* Vorschau */}
            {result.vorschau?.length > 0 && (
              <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
                <h2 className="font-semibold text-primary text-sm mb-3">Vorschau (erste 3 Zeilen)</h2>
                <div className="space-y-2">
                  {result.vorschau.map((row, i) => (
                    <div key={i} className="bg-slate-50 rounded-lg px-3 py-2.5 text-xs">
                      <p className="text-slate-700 font-medium leading-snug">{row.beschreibung}</p>
                      <div className="flex gap-4 mt-1 text-slate-400">
                        <span>{row.dauer_tage} Tage</span>
                        {row.region && <span>{row.region}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Retrain Section */}
            <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
              <h2 className="font-semibold text-primary text-sm mb-1">Modell neu trainieren</h2>
              <p className="text-xs text-slate-400 mb-4">
                Trainiert das Laufzeit-Modell mit deinen neuen Daten. Dauert ca. 30–60 Sekunden.
              </p>

              {status === 'retraining' && (
                <div className="flex items-center gap-3 text-sm text-accent mb-3">
                  <Spinner />
                  <span>Modell wird trainiert…</span>
                </div>
              )}

              {status === 'retrained' && retainInfo && (
                <div className="bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-3 mb-4 text-sm">
                  <p className="font-semibold text-emerald-700">
                    Training abgeschlossen
                  </p>
                  <div className="flex gap-6 mt-1 text-xs text-emerald-600">
                    <span>
                      MdAPE: <strong>
                        {(retainInfo.mdape * 100).toFixed(1)} %
                        {prevMdape != null && prevMdape !== retainInfo.mdape && (
                          <span className="text-slate-500 font-normal ml-1">
                            (vorher {(prevMdape * 100).toFixed(1)} %)
                          </span>
                        )}
                      </strong>
                    </span>
                    <span>Datensätze: <strong>{retainInfo.n?.toLocaleString('de-DE')}</strong></span>
                  </div>
                </div>
              )}

              {errorMsg && (status === 'success' || status === 'retrained') && (
                <p className="text-xs text-red-500 mb-3">{errorMsg}</p>
              )}

              <button
                onClick={handleRetrain}
                disabled={!canRetrain || status === 'retraining'}
                className={`w-full py-2.5 rounded-lg font-semibold text-sm transition-colors flex items-center justify-center gap-2 ${
                  canRetrain && status !== 'retraining'
                    ? 'bg-primary hover:bg-slate-800 text-white'
                    : 'bg-slate-100 text-slate-400 cursor-not-allowed'
                }`}
              >
                {status === 'retraining'
                  ? <><Spinner /> Training läuft…</>
                  : status === 'retrained'
                  ? 'Erneut trainieren'
                  : 'Modell neu trainieren'
                }
              </button>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
