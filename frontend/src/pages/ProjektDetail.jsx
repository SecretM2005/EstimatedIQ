import { useEffect, useState, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  getProjekt, getPositionen, createPosition, deletePosition,
  updateIstStunden, sucheAehnliche, createAngebot, getPdfUrl, getRollen,
  sucheReferenzprojekte, vorlagUebernehmen, updateProjekt,
} from '../api/angebot'

const fmtEUR = n =>
  new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(n)

function SimilarityBar({ value }) {
  const pct = Math.round(value * 100)
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full bg-accent"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-[11px] text-slate-500 tabular-nums w-8 text-right">{pct}%</span>
    </div>
  )
}

export default function ProjektDetail() {
  const { id }     = useParams()
  const projekt_id = parseInt(id)

  const [projekt,    setProjekt]    = useState(null)
  const [positionen, setPositionen] = useState([])
  const [rollen,     setRollen]     = useState([])
  const [loading,    setLoading]    = useState(true)

  const [beschreibung, setBeschreibung] = useState('')
  const [stunden,      setStunden]      = useState('')
  const [rolleId,      setRolleId]      = useState('')
  const [satz,         setSatz]         = useState('')
  const [saving,       setSaving]       = useState(false)

  const [suchErgebnis, setSuchErgebnis] = useState(null)
  const [sucheLoading, setSucheLoading] = useState(false)

  const [editIstId, setEditIstId] = useState(null)
  const [istValue,  setIstValue]  = useState('')

  const [pdfLoading, setPdfLoading] = useState(false)

  const [refErgebnisse,    setRefErgebnisse]    = useState(null)
  const [refUebernommenId, setRefUebernommenId] = useState(null)

  const [editBeschreibung,   setEditBeschreibung]   = useState(false)
  const [beschreibungText,   setBeschreibungText]   = useState('')
  const [savingBeschreibung, setSavingBeschreibung] = useState(false)

  const load = useCallback(async () => {
    const [p, pos, r] = await Promise.all([
      getProjekt(projekt_id),
      getPositionen(projekt_id),
      getRollen(),
    ])
    setProjekt(p); setPositionen(pos); setRollen(r)
    setBeschreibungText(p.beschreibung || '')
    setLoading(false)
    const suchbeschreibung = p.beschreibung?.trim() || p.name
    try {
      const refs = await sucheReferenzprojekte({
        beschreibung:       suchbeschreibung,
        name:               p.name,
        k:                  1,
        exclude_projekt_id: projekt_id,
      })
      setRefErgebnisse(refs)
    } catch { setRefErgebnisse([]) }
  }, [projekt_id])

  useEffect(() => { load() }, [load])

  const handleRolleChange = (e) => {
    const rid = e.target.value
    setRolleId(rid)
    if (rid) {
      const rolle = rollen.find(r => r.id === parseInt(rid))
      if (rolle) setSatz(String(rolle.stundensatz_eur))
    }
  }

  const aktivPositionen = positionen.filter(p => !p.ist_historisch)

  const gesamtSoll = aktivPositionen.reduce(
    (s, p) => s + (p.soll_stunden * (p.stundensatz_snapshot || 0)), 0
  )

  const handleAddPosition = async (e) => {
    e.preventDefault()
    if (!beschreibung.trim() || !stunden) return
    setSaving(true)
    try {
      await createPosition(projekt_id, {
        beschreibung_text: beschreibung.trim(),
        soll_stunden:      parseFloat(stunden),
        rolle_id:          rolleId ? parseInt(rolleId) : null,
        stundensatz_eur:   satz ? parseFloat(satz) : null,
      })
      setBeschreibung(''); setStunden(''); setRolleId(''); setSatz('')
      setSuchErgebnis(null)
      load()
    } finally { setSaving(false) }
  }

  const handleSuche = async () => {
    if (!beschreibung.trim()) return
    setSucheLoading(true)
    try {
      const res = await sucheAehnliche({
        beschreibung_text:  beschreibung.trim(),
        k:                  5,
        exclude_projekt_id: projekt_id,
      })
      setSuchErgebnis(res)
      if (res.schaetzvorschlag && !stunden) {
        setStunden(String(res.schaetzvorschlag))
      }
    } catch {
      setSuchErgebnis(null)
    } finally {
      setSucheLoading(false)
    }
  }

  const handleBeschreibungSave = async () => {
    setSavingBeschreibung(true)
    try {
      await updateProjekt(projekt_id, { beschreibung: beschreibungText.trim() })
      setEditBeschreibung(false)
      load()
    } finally { setSavingBeschreibung(false) }
  }

  const handleVorlageUebernehmen = async (refId) => {
    setRefUebernommenId(refId)
    try {
      await vorlagUebernehmen(projekt_id, refId)
      setRefErgebnisse(null)
      load()
    } finally { setRefUebernommenId(null) }
  }

  const handleIstSave = async (posId) => {
    const val = parseFloat(istValue)
    if (isNaN(val) || val <= 0) return
    await updateIstStunden(posId, val)
    setEditIstId(null); load()
  }

  const handlePdf = async () => {
    setPdfLoading(true)
    try {
      const a = await createAngebot(projekt_id, { titel: `Angebot ${projekt?.name}` })
      window.open(getPdfUrl(a.id), '_blank')
    } finally { setPdfLoading(false) }
  }

  if (loading) return (
    <div className="p-8 text-slate-400 text-sm">Lade…</div>
  )

  const bestRef = refErgebnisse?.length > 0 ? refErgebnisse[0] : null

  return (
    <div className="flex items-start">
      {/* Main content */}
      <div className="flex-1 min-w-0 p-8 pb-16">
        {/* Breadcrumb */}
        <Link
          to="/projekte"
          className="inline-flex items-center gap-1 text-[12px] text-slate-400 hover:text-slate-600 mb-4 transition-colors"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none"><path d="M15 18l-6-6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
          Projekte
        </Link>

        {/* Header */}
        <div className="flex items-start justify-between gap-6 mb-6">
          <div className="flex-1 min-w-0">
            <h1 className="text-[24px] font-bold tracking-tight text-slate-900 m-0 truncate">{projekt?.name}</h1>
            {projekt?.kunde && (
              <p className="text-[13px] text-slate-500 mt-0.5">{projekt.kunde}</p>
            )}

            {/* Editable description */}
            <div className="mt-3">
              {editBeschreibung ? (
                <div className="flex flex-col gap-2">
                  <textarea
                    value={beschreibungText}
                    onChange={e => setBeschreibungText(e.target.value)}
                    rows={3}
                    placeholder="Projektbeschreibung – wird für die Ähnlichkeitssuche genutzt"
                    className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent resize-none"
                    autoFocus
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={handleBeschreibungSave}
                      disabled={savingBeschreibung}
                      className="h-8 px-3 bg-accent hover:bg-accent-hover text-white rounded-lg text-[12px] font-semibold transition-colors disabled:opacity-50"
                    >
                      {savingBeschreibung ? 'Speichern…' : 'Speichern'}
                    </button>
                    <button
                      onClick={() => { setEditBeschreibung(false); setBeschreibungText(projekt?.beschreibung || '') }}
                      className="h-8 px-3 bg-white border border-slate-200 rounded-lg text-[12px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors"
                    >
                      Abbrechen
                    </button>
                  </div>
                </div>
              ) : (
                <div onClick={() => setEditBeschreibung(true)} className="group cursor-pointer">
                  {projekt?.beschreibung ? (
                    <p className="text-[13px] text-slate-600 leading-relaxed group-hover:text-slate-800 transition-colors">
                      {projekt.beschreibung}
                      <span className="ml-1.5 text-[12px] text-slate-300 group-hover:text-slate-400 transition-colors">✎</span>
                    </p>
                  ) : (
                    <p className="text-[13px] text-slate-300 italic group-hover:text-slate-400 transition-colors">
                      Projektbeschreibung hinzufügen… <span className="not-italic">✎</span>
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Actions + total */}
          <div className="shrink-0 flex flex-col items-end gap-3">
            <div className="text-right">
              <p className="text-[11px] text-slate-400 uppercase tracking-wide font-semibold mb-0.5">Angebotssumme</p>
              <p className="text-[28px] font-bold text-slate-900 tabular-nums leading-none">{fmtEUR(gesamtSoll)}</p>
            </div>
            <div className="flex gap-2">
              <Link
                to={`/projekte/${projekt_id}/nachkalkulation`}
                className="h-9 px-3 bg-white border border-slate-200 rounded-lg text-[13px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors inline-flex items-center"
              >
                Nachkalkulation
              </Link>
              <button
                onClick={handlePdf}
                disabled={pdfLoading || aktivPositionen.length === 0}
                className="h-9 px-4 bg-accent hover:bg-accent-hover text-white rounded-lg text-[13px] font-semibold transition-colors shadow-accent disabled:opacity-40 inline-flex items-center gap-1.5"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
                {pdfLoading ? 'PDF erstellen…' : 'PDF'}
              </button>
            </div>
          </div>
        </div>

        {/* Add position form */}
        <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs mb-5">
          <h2 className="text-[13.5px] font-semibold text-slate-900 mb-4">Position hinzufügen</h2>
          <form onSubmit={handleAddPosition} className="flex flex-col gap-4">
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Beschreibung *</label>
              <textarea
                value={beschreibung}
                onChange={e => { setBeschreibung(e.target.value); setSuchErgebnis(null) }}
                rows={2}
                placeholder="Was wird in dieser Position geleistet?"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent resize-none"
              />
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div>
                <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Soll-Stunden *</label>
                <input
                  type="number" min="0.5" step="0.5" value={stunden}
                  onChange={e => setStunden(e.target.value)}
                  placeholder="8"
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"
                />
              </div>
              <div>
                <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Rolle</label>
                <select
                  value={rolleId} onChange={handleRolleChange}
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent bg-white"
                >
                  <option value="">– keine –</option>
                  {rollen.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Stundensatz €/h</label>
                <input
                  type="number" min="1" step="1" value={satz}
                  onChange={e => setSatz(e.target.value)}
                  placeholder="120"
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"
                />
              </div>
              <div className="flex flex-col justify-end gap-2">
                <button
                  type="button" onClick={handleSuche}
                  disabled={sucheLoading || !beschreibung.trim()}
                  className="h-9 px-3 bg-white border border-slate-200 rounded-lg text-[12.5px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors disabled:opacity-40"
                >
                  {sucheLoading ? 'Suche…' : 'Ähnliche suchen'}
                </button>
                <button
                  type="submit"
                  disabled={saving || !beschreibung.trim() || !stunden}
                  className="h-9 px-3 bg-accent hover:bg-accent-hover text-white rounded-lg text-[12.5px] font-semibold transition-colors disabled:opacity-40"
                >
                  {saving ? 'Hinzufügen…' : '+ Hinzufügen'}
                </button>
              </div>
            </div>
          </form>

          {/* Position similarity results */}
          {suchErgebnis && (
            <div className="mt-5 pt-4 border-t border-slate-100">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <p className="text-[13px] font-semibold text-slate-900">Ähnliche historische Positionen</p>
                  <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${
                    suchErgebnis.konfidenz === 'hoch'   ? 'bg-emerald-50 text-emerald-700' :
                    suchErgebnis.konfidenz === 'mittel' ? 'bg-amber-50 text-amber-700'   :
                    'bg-slate-100 text-slate-500'
                  }`}>Konfidenz: {suchErgebnis.konfidenz}</span>
                </div>
                <p className="text-[12px] text-slate-400">
                  Vorschlag: <strong className="text-slate-700">{suchErgebnis.schaetzvorschlag} h</strong>
                  {' '}({suchErgebnis.n_verglichen} verglichen)
                </p>
              </div>
              {suchErgebnis.treffer.length === 0 ? (
                <p className="text-[13px] text-slate-400">Keine ähnlichen Positionen gefunden – bitte erst historische Daten importieren.</p>
              ) : (
                <div className="flex flex-col gap-2">
                  {suchErgebnis.treffer.map((t, i) => (
                    <div key={i} className="flex items-start justify-between gap-3 bg-slate-50 rounded-lg px-4 py-3">
                      <div className="flex-1 min-w-0">
                        <p className="text-[12.5px] text-slate-800 line-clamp-2">{t.beschreibung_text}</p>
                        {t.rolle_name && <p className="text-[11.5px] text-slate-400 mt-0.5">{t.rolle_name}</p>}
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="text-[13px] font-semibold text-slate-900 tabular-nums">
                          {t.ist_stunden != null ? t.ist_stunden : t.soll_stunden} h
                          {t.ist_stunden != null && <span className="text-[11px] text-emerald-600 ml-1">(Ist)</span>}
                        </p>
                        <p className="text-[11px] text-slate-400">{Math.round(t.aehnlichkeit * 100)}% ähnlich</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Positions list */}
        <div>
          <h2 className="text-[14px] font-semibold text-slate-900 mb-3">
            Positionen <span className="text-slate-400 font-normal">({aktivPositionen.length})</span>
          </h2>
          {aktivPositionen.length === 0 ? (
            <div className="bg-white border border-slate-200 rounded-xl p-12 text-center shadow-xs">
              <p className="text-[14px] font-semibold text-slate-900 mb-1">Noch keine Positionen</p>
              <p className="text-[13px] text-slate-500">Füge oben eine Position hinzu.</p>
            </div>
          ) : (
            <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
              {/* Head */}
              <div
                className="grid items-center px-5 py-2.5 bg-slate-50 border-b border-slate-200"
                style={{ gridTemplateColumns: '1fr 100px 110px 100px 90px' }}
              >
                {['Beschreibung', 'Stunden', 'Stundensatz', 'Summe', ''].map(h => (
                  <span key={h} className="text-[10.5px] font-semibold uppercase tracking-[0.04em] text-slate-400 text-right first:text-left">{h}</span>
                ))}
              </div>

              {aktivPositionen.map((pos, i) => {
                const summe = pos.soll_stunden * (pos.stundensatz_snapshot || 0)
                return (
                  <div
                    key={pos.id}
                    className="grid items-center px-5 py-3.5 border-t border-slate-100 group"
                    style={{ gridTemplateColumns: '1fr 100px 110px 100px 90px' }}
                  >
                    <div className="min-w-0 pr-4">
                      <p className="text-[13px] font-medium text-slate-900 truncate">{pos.beschreibung_text}</p>
                      <p className="text-[11.5px] text-slate-400 mt-0.5">{pos.rolle_name || '–'}</p>
                    </div>

                    <div className="text-right">
                      {editIstId === pos.id ? (
                        <div className="flex items-center gap-1 justify-end">
                          <input
                            type="number" value={istValue}
                            onChange={e => setIstValue(e.target.value)}
                            className="w-16 border border-slate-200 rounded px-2 py-1 text-[12px] text-right focus:outline-none focus:ring-1 focus:ring-accent/30"
                            autoFocus
                          />
                          <button onClick={() => handleIstSave(pos.id)} className="text-[11.5px] text-emerald-600 font-semibold">OK</button>
                          <button onClick={() => setEditIstId(null)} className="text-[11.5px] text-slate-400">✕</button>
                        </div>
                      ) : (
                        <div>
                          <p className="text-[13px] font-medium text-slate-900 tabular-nums">{pos.soll_stunden} h</p>
                          {pos.ist_stunden != null && (
                            <p className="text-[11px] text-emerald-600 tabular-nums">{pos.ist_stunden} h Ist</p>
                          )}
                        </div>
                      )}
                    </div>

                    <div className="text-right">
                      <p className="text-[13px] text-slate-600 tabular-nums">
                        {pos.stundensatz_snapshot ? `${pos.stundensatz_snapshot} €/h` : '–'}
                      </p>
                    </div>

                    <div className="text-right">
                      {summe > 0 && (
                        <p className="text-[13px] font-semibold text-slate-900 tabular-nums">{fmtEUR(summe)}</p>
                      )}
                    </div>

                    <div className="flex items-center justify-end gap-1">
                      {editIstId !== pos.id && (
                        <button
                          onClick={() => { setEditIstId(pos.id); setIstValue(pos.ist_stunden ?? '') }}
                          className="opacity-0 group-hover:opacity-100 text-[11px] text-slate-500 hover:text-accent px-1.5 py-1 transition-opacity"
                        >
                          {pos.ist_stunden != null ? 'Ist ✎' : '+ Ist'}
                        </button>
                      )}
                      <button
                        onClick={async () => { await deletePosition(pos.id); load() }}
                        className="opacity-0 group-hover:opacity-100 text-[11px] text-red-400 hover:text-red-600 px-1 py-1 transition-opacity"
                      >✕</button>
                    </div>
                  </div>
                )
              })}

              {/* Total */}
              <div
                className="grid items-center px-5 py-3.5 border-t-2 border-slate-200 bg-slate-50"
                style={{ gridTemplateColumns: '1fr 100px 110px 100px 90px' }}
              >
                <span className="text-[13px] font-semibold text-slate-700">Gesamt (netto)</span>
                <div />
                <div />
                <div className="text-right">
                  <p className="text-[15px] font-bold text-slate-900 tabular-nums">{fmtEUR(gesamtSoll)}</p>
                </div>
                <div />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Right panel — reference project, sticky */}
      <div className="w-[352px] flex-none border-l border-slate-200 bg-white sticky top-0 max-h-screen overflow-y-auto">
        <div className="p-5">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-6 h-6 rounded-md bg-indigo-50 flex items-center justify-center flex-none">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" className="text-accent">
                <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2"/>
                <path d="m20 20-3-3" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
              </svg>
            </div>
            <h2 className="text-[13px] font-semibold text-slate-900">Ähnlichstes Referenzprojekt</h2>
          </div>

          {refErgebnisse === null ? (
            <div className="flex items-center gap-2 text-[12.5px] text-slate-400">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" className="animate-spin flex-none"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4" strokeDashoffset="10"/></svg>
              Suche läuft…
            </div>
          ) : !bestRef ? (
            <div className="bg-slate-50 rounded-xl p-5 text-center">
              <p className="text-[13px] font-medium text-slate-600 mb-1">Kein passendes Referenzprojekt</p>
              <p className="text-[12px] text-slate-400">Importiere historische Projekte unter "Daten importieren".</p>
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              {/* Match card */}
              <div className="bg-indigo-50 border border-indigo-100 rounded-xl p-4">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <p className="text-[13.5px] font-semibold text-slate-900 leading-snug">{bestRef.projekt_name}</p>
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-accent text-white font-semibold shrink-0 tabular-nums">
                    {Math.round(bestRef.aehnlichkeit * 100)}%
                  </span>
                </div>
                <SimilarityBar value={bestRef.aehnlichkeit} />
                <p className="text-[12px] text-slate-500 mt-2">{bestRef.n_positionen} Position{bestRef.n_positionen !== 1 ? 'en' : ''}</p>
              </div>

              {/* Positions preview */}
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.04em] text-slate-400 mb-2">Positionen</p>
                <div className="flex flex-col gap-1">
                  {bestRef.positionen.slice(0, 6).map((p, i) => (
                    <div key={i} className="flex items-start justify-between gap-2 py-1.5 border-b border-slate-100 last:border-0">
                      <p className="text-[12px] text-slate-700 flex-1 min-w-0 leading-snug line-clamp-2">{p.beschreibung_text}</p>
                      <div className="shrink-0 text-right">
                        <span className="text-[12px] font-medium text-slate-900 tabular-nums">{p.soll_stunden} h</span>
                        {p.stundensatz_snapshot && (
                          <p className="text-[10.5px] text-slate-400 tabular-nums">{p.stundensatz_snapshot} €/h</p>
                        )}
                      </div>
                    </div>
                  ))}
                  {bestRef.n_positionen > 6 && (
                    <p className="text-[11.5px] text-slate-400 pt-1">… und {bestRef.n_positionen - 6} weitere</p>
                  )}
                </div>
              </div>

              {/* Action */}
              <button
                onClick={() => handleVorlageUebernehmen(bestRef.projekt_id)}
                disabled={refUebernommenId === bestRef.projekt_id}
                className="w-full h-9 bg-accent hover:bg-accent-hover text-white rounded-lg text-[13px] font-semibold transition-colors shadow-accent disabled:opacity-50"
              >
                {refUebernommenId === bestRef.projekt_id ? 'Übernehme…' : 'Als Vorlage übernehmen'}
              </button>
              <p className="text-[11.5px] text-slate-400 text-center -mt-2">
                Alle Positionen werden in dieses Projekt kopiert
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
