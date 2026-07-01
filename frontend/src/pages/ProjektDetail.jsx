import { useEffect, useState, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  getProjekt, getPositionen, createPosition, deletePosition,
  updateIstStunden, sucheAehnliche, createAngebot, getPdfUrl, getRollen,
} from '../api/angebot'
import NavBar from '../components/NavBar'

const fmtEUR = n =>
  new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(n)

function KonfidenzBadge({ score }) {
  const pct = Math.round(score * 100)
  const cls = score >= 0.75 ? 'bg-emerald-50 text-emerald-700'
            : score >= 0.50 ? 'bg-yellow-50 text-yellow-700'
            : 'bg-slate-100 text-slate-500'
  return <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cls}`}>{pct}% ähnlich</span>
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
  const [satz,         setSatz]         = useState('')   // projektspezifischer Stundensatz
  const [saving,       setSaving]       = useState(false)

  const [suchErgebnis, setSuchErgebnis] = useState(null)
  const [sucheLoading, setSucheLoading] = useState(false)

  const [editIstId, setEditIstId] = useState(null)
  const [istValue,  setIstValue]  = useState('')

  const [pdfLoading, setPdfLoading] = useState(false)

  const load = useCallback(async () => {
    const [p, pos, r] = await Promise.all([
      getProjekt(projekt_id),
      getPositionen(projekt_id),
      getRollen(),
    ])
    setProjekt(p); setPositionen(pos); setRollen(r)
    setLoading(false)
  }, [projekt_id])

  useEffect(() => { load() }, [load])

  // Rollenwechsel → Stundensatz vorbelegen
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
    <div className="min-h-screen bg-light flex items-center justify-center text-slate-400">Lade…</div>
  )

  return (
    <div className="min-h-screen bg-light">
      <NavBar />

      <main className="max-w-4xl mx-auto px-4 py-10">
        {/* Projekt-Header */}
        <div className="flex items-start justify-between mb-8 gap-4">
          <div>
            <Link to="/projekte" className="text-xs text-slate-400 hover:text-primary mb-1 inline-block">← Projekte</Link>
            <h1 className="text-3xl font-extrabold text-primary">{projekt?.name}</h1>
            <p className="text-sm text-slate-500 mt-0.5">{projekt?.kunde || '–'}</p>
          </div>
          <div className="text-right shrink-0 flex flex-col gap-2">
            <div>
              <p className="text-xs text-slate-400 mb-0.5">Angebotssumme (netto)</p>
              <p className="text-3xl font-extrabold text-primary">{fmtEUR(gesamtSoll)}</p>
            </div>
            <button
              onClick={handlePdf}
              disabled={pdfLoading || aktivPositionen.length === 0}
              className="btn-primary text-sm py-2 px-4 disabled:opacity-50"
            >
              {pdfLoading ? 'Erstelle PDF…' : 'Angebot als PDF'}
            </button>
            <Link
              to={`/projekte/${projekt_id}/nachkalkulation`}
              className="btn-secondary text-sm py-2 px-4 text-center"
            >
              Nachkalkulation
            </Link>
          </div>
        </div>

        {/* Neue Position */}
        <section className="bg-white rounded-xl border border-slate-200 shadow-sm p-6 mb-6">
          <h2 className="font-semibold text-ink mb-4">Position hinzufügen</h2>
          <form onSubmit={handleAddPosition} className="flex flex-col gap-4">
            <div>
              <label className="block text-xs font-medium text-slate-500 mb-1">Beschreibung *</label>
              <textarea
                value={beschreibung}
                onChange={e => { setBeschreibung(e.target.value); setSuchErgebnis(null) }}
                rows={3}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary resize-none"
              />
            </div>

            <div className="grid sm:grid-cols-4 gap-4">
              <div>
                <label className="block text-xs font-medium text-slate-500 mb-1">Soll-Stunden *</label>
                <input
                  type="number" min="0.5" step="0.5" value={stunden}
                  onChange={e => setStunden(e.target.value)}
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 mb-1">Rolle</label>
                <select
                  value={rolleId} onChange={handleRolleChange}
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary bg-white"
                >
                  <option value="">– keine –</option>
                  {rollen.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 mb-1">Stundensatz €/h</label>
                <input
                  type="number" min="1" step="1" value={satz}
                  onChange={e => setSatz(e.target.value)}
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </div>
              <div className="flex flex-col justify-end gap-2">
                <button
                  type="button" onClick={handleSuche}
                  disabled={sucheLoading || !beschreibung.trim()}
                  className="btn-secondary text-sm py-2 disabled:opacity-50"
                >
                  {sucheLoading ? 'Suche…' : 'Ähnliche suchen'}
                </button>
                <button
                  type="submit"
                  disabled={saving || !beschreibung.trim() || !stunden}
                  className="btn-primary text-sm py-2 disabled:opacity-50"
                >
                  {saving ? 'Hinzufügen…' : '+ Hinzufügen'}
                </button>
              </div>
            </div>
          </form>

          {/* Ähnlichkeits-Ergebnisse */}
          {suchErgebnis && (
            <div className="mt-5 border-t border-slate-100 pt-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium text-ink">Ähnliche historische Positionen</p>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                    suchErgebnis.konfidenz === 'hoch'   ? 'bg-emerald-50 text-emerald-700' :
                    suchErgebnis.konfidenz === 'mittel' ? 'bg-yellow-50 text-yellow-700'   :
                    'bg-slate-100 text-slate-500'
                  }`}>Konfidenz: {suchErgebnis.konfidenz}</span>
                </div>
                <p className="text-xs text-slate-400">
                  Vorschlag: <strong className="text-ink">{suchErgebnis.schaetzvorschlag} h</strong>
                  {' '}({suchErgebnis.n_verglichen} verglichen)
                </p>
              </div>
              {suchErgebnis.treffer.length === 0 ? (
                <p className="text-sm text-slate-400">Keine ähnlichen Positionen gefunden – bitte erst historische Daten importieren.</p>
              ) : (
                <div className="flex flex-col gap-2">
                  {suchErgebnis.treffer.map((t, i) => (
                    <div key={i} className="flex items-start justify-between gap-3 bg-slate-50 rounded-lg px-4 py-3">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-ink line-clamp-2">{t.beschreibung_text}</p>
                        {t.rolle_name && <p className="text-xs text-slate-400 mt-0.5">{t.rolle_name}</p>}
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="text-sm font-semibold text-ink">
                          {t.ist_stunden != null ? t.ist_stunden : t.soll_stunden} h
                          {t.ist_stunden != null && <span className="text-xs text-emerald-600 ml-1">(Ist)</span>}
                        </p>
                        <KonfidenzBadge score={t.aehnlichkeit} />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </section>

        {/* Positionsliste */}
        <section>
          <h2 className="text-[22px] font-semibold text-primary mb-3">
            Positionen ({aktivPositionen.length})
          </h2>
          {aktivPositionen.length === 0 ? (
            <div className="bg-white rounded-xl border border-slate-200 p-8 text-center text-slate-400">
              Noch keine Positionen.
            </div>
          ) : (
            <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
              {aktivPositionen.map((pos, i) => {
                const summe = pos.soll_stunden * (pos.stundensatz_snapshot || 0)
                return (
                  <div key={pos.id} className={`px-5 py-4 ${i > 0 ? 'border-t border-slate-100' : ''}`}>
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-ink">{pos.beschreibung_text}</p>
                        <p className="text-xs text-slate-400 mt-0.5">
                          {pos.rolle_name || '–'}{' · '}
                          {pos.soll_stunden} h Soll
                          {pos.stundensatz_snapshot ? ` · ${pos.stundensatz_snapshot} €/h` : ''}
                          {pos.ist_stunden != null && (
                            <span className="ml-2 text-emerald-600 font-medium">{pos.ist_stunden} h Ist</span>
                          )}
                        </p>
                      </div>
                      <div className="shrink-0 text-right">
                        {summe > 0 && <p className="font-semibold text-ink text-sm">{fmtEUR(summe)}</p>}
                        <div className="flex items-center gap-2 mt-1 justify-end">
                          {editIstId === pos.id ? (
                            <>
                              <input
                                type="number" value={istValue}
                                onChange={e => setIstValue(e.target.value)}
                                className="w-20 border border-slate-200 rounded px-2 py-1 text-xs"
                                autoFocus
                              />
                              <button onClick={() => handleIstSave(pos.id)} className="text-xs text-emerald-600 font-medium">OK</button>
                              <button onClick={() => setEditIstId(null)} className="text-xs text-slate-400">✕</button>
                            </>
                          ) : (
                            <button
                              onClick={() => { setEditIstId(pos.id); setIstValue(pos.ist_stunden ?? '') }}
                              className="text-xs text-slate-500 hover:text-primary"
                            >
                              {pos.ist_stunden != null ? 'Ist bearbeiten' : 'Ist eintragen'}
                            </button>
                          )}
                          <button
                            onClick={async () => { await deletePosition(pos.id); load() }}
                            className="text-xs text-red-400 hover:text-red-600"
                          >✕</button>
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })}
              <div className="border-t border-slate-200 px-5 py-4 bg-slate-50 flex justify-between items-center">
                <span className="text-sm font-semibold text-slate-600">Gesamt (netto)</span>
                <span className="text-lg font-extrabold text-primary">{fmtEUR(gesamtSoll)}</span>
              </div>
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
