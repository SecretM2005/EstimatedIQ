import { useEffect, useState, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getProjekt, getPositionen, updateIstStunden } from '../api/angebot'
import NavBar from '../components/NavBar'

const fmtEUR = n =>
  new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(n)

const fmtH = n => `${Number(n).toFixed(1)} h`

function Abweichung({ soll, ist }) {
  if (ist == null) return <span className="text-slate-300">–</span>
  const diff = ist - soll
  const pct  = soll > 0 ? Math.round((diff / soll) * 100) : 0
  if (Math.abs(diff) < 0.1) return <span className="text-slate-400">±0</span>
  const cls  = diff > 0 ? 'text-red-600' : 'text-emerald-600'
  return (
    <span className={`font-medium ${cls}`}>
      {diff > 0 ? '+' : ''}{fmtH(diff)} ({diff > 0 ? '+' : ''}{pct} %)
    </span>
  )
}

export default function Nachkalkulation() {
  const { id }     = useParams()
  const projekt_id = parseInt(id)

  const [projekt,    setProjekt]    = useState(null)
  const [positionen, setPositionen] = useState([])
  const [loading,    setLoading]    = useState(true)
  const [editId,     setEditId]     = useState(null)
  const [istValue,   setIstValue]   = useState('')

  const load = useCallback(async () => {
    const [p, pos] = await Promise.all([getProjekt(projekt_id), getPositionen(projekt_id)])
    setProjekt(p)
    setPositionen(pos.filter(p => !p.ist_historisch))
    setLoading(false)
  }, [projekt_id])

  useEffect(() => { load() }, [load])

  const handleIstSave = async (posId) => {
    const val = parseFloat(istValue)
    if (isNaN(val) || val < 0) return
    await updateIstStunden(posId, val)
    setEditId(null); load()
  }

  if (loading) return (
    <div className="min-h-screen bg-light flex items-center justify-center text-slate-400">Lade…</div>
  )

  const gesamtSoll     = positionen.reduce((s, p) => s + p.soll_stunden, 0)
  const gesamtIst      = positionen.every(p => p.ist_stunden != null)
    ? positionen.reduce((s, p) => s + (p.ist_stunden ?? 0), 0)
    : null
  const gesamtSollEUR  = positionen.reduce((s, p) => s + p.soll_stunden * (p.stundensatz_snapshot || 0), 0)
  const gesamtIstEUR   = positionen.every(p => p.ist_stunden != null)
    ? positionen.reduce((s, p) => s + (p.ist_stunden ?? 0) * (p.stundensatz_snapshot || 0), 0)
    : null

  const istKomplett = positionen.length > 0 && positionen.every(p => p.ist_stunden != null)

  return (
    <div className="min-h-screen bg-light">
      <NavBar />

      <main className="max-w-5xl mx-auto px-4 py-10">
        <div className="flex items-start justify-between mb-8 gap-4">
          <div>
            <Link to={`/projekte/${projekt_id}`} className="text-xs text-slate-400 hover:text-primary mb-1 inline-block">
              ← {projekt?.name}
            </Link>
            <h1 className="text-3xl font-extrabold text-primary">Nachkalkulation</h1>
            <p className="text-sm text-slate-500 mt-0.5">{projekt?.kunde || '–'}</p>
          </div>

          {/* Zusammenfassung */}
          <div className="flex gap-4 shrink-0">
            <div className="bg-white border border-slate-200 rounded-xl px-5 py-3 text-right shadow-sm">
              <p className="text-xs text-slate-400 mb-0.5">Soll-Stunden</p>
              <p className="text-xl font-bold text-ink">{fmtH(gesamtSoll)}</p>
              <p className="text-xs text-slate-400">{fmtEUR(gesamtSollEUR)}</p>
            </div>
            <div className={`border rounded-xl px-5 py-3 text-right shadow-sm ${istKomplett ? 'bg-white border-slate-200' : 'bg-slate-50 border-slate-100'}`}>
              <p className="text-xs text-slate-400 mb-0.5">Ist-Stunden</p>
              <p className={`text-xl font-bold ${istKomplett ? 'text-ink' : 'text-slate-300'}`}>
                {gesamtIst != null ? fmtH(gesamtIst) : '–'}
              </p>
              <p className="text-xs text-slate-400">{gesamtIstEUR != null ? fmtEUR(gesamtIstEUR) : '–'}</p>
            </div>
            {istKomplett && gesamtIst != null && (
              <div className={`border rounded-xl px-5 py-3 text-right shadow-sm ${
                gesamtIst > gesamtSoll ? 'bg-red-50 border-red-200' : 'bg-emerald-50 border-emerald-200'
              }`}>
                <p className="text-xs text-slate-400 mb-0.5">Abweichung</p>
                <p className={`text-xl font-bold ${gesamtIst > gesamtSoll ? 'text-red-600' : 'text-emerald-700'}`}>
                  {gesamtIst > gesamtSoll ? '+' : ''}{fmtH(gesamtIst - gesamtSoll)}
                </p>
                <p className={`text-xs font-medium ${gesamtIst > gesamtSoll ? 'text-red-500' : 'text-emerald-600'}`}>
                  {gesamtSoll > 0 ? `${gesamtIst > gesamtSoll ? '+' : ''}${Math.round(((gesamtIst - gesamtSoll) / gesamtSoll) * 100)} %` : ''}
                </p>
              </div>
            )}
          </div>
        </div>

        {positionen.length === 0 ? (
          <div className="bg-white rounded-xl border border-slate-200 p-8 text-center text-slate-400">
            Keine Positionen in diesem Projekt.
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            {/* Tabellenkopf */}
            <div className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-x-4 px-5 py-3 bg-slate-50 border-b border-slate-200 text-xs font-semibold text-slate-500 uppercase tracking-wide">
              <span>Position</span>
              <span className="text-right w-24">Soll</span>
              <span className="text-right w-24">Ist</span>
              <span className="text-right w-32">Abweichung</span>
              <span className="w-28"></span>
            </div>

            {positionen.map((pos, i) => (
              <div
                key={pos.id}
                className={`grid grid-cols-[1fr_auto_auto_auto_auto] gap-x-4 items-center px-5 py-4 ${
                  i > 0 ? 'border-t border-slate-100' : ''
                } ${pos.ist_stunden != null && pos.ist_stunden > pos.soll_stunden ? 'bg-red-50/30' : ''}`}
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium text-ink truncate">{pos.beschreibung_text}</p>
                  <p className="text-xs text-slate-400 mt-0.5">
                    {pos.rolle_name || '–'}
                    {pos.stundensatz_snapshot ? ` · ${pos.stundensatz_snapshot} €/h` : ''}
                  </p>
                </div>

                <div className="text-right w-24">
                  <p className="text-sm font-medium text-ink">{fmtH(pos.soll_stunden)}</p>
                  {pos.stundensatz_snapshot > 0 && (
                    <p className="text-xs text-slate-400">{fmtEUR(pos.soll_stunden * pos.stundensatz_snapshot)}</p>
                  )}
                </div>

                <div className="text-right w-24">
                  {editId === pos.id ? (
                    <div className="flex items-center gap-1 justify-end">
                      <input
                        type="number" value={istValue} min="0" step="0.5"
                        onChange={e => setIstValue(e.target.value)}
                        className="w-16 border border-slate-200 rounded px-2 py-1 text-xs text-right"
                        autoFocus
                      />
                      <span className="text-xs text-slate-400">h</span>
                    </div>
                  ) : (
                    <>
                      <p className={`text-sm font-medium ${pos.ist_stunden != null ? 'text-ink' : 'text-slate-300'}`}>
                        {pos.ist_stunden != null ? fmtH(pos.ist_stunden) : '–'}
                      </p>
                      {pos.ist_stunden != null && pos.stundensatz_snapshot > 0 && (
                        <p className="text-xs text-slate-400">{fmtEUR(pos.ist_stunden * pos.stundensatz_snapshot)}</p>
                      )}
                    </>
                  )}
                </div>

                <div className="text-right w-32 text-sm">
                  <Abweichung soll={pos.soll_stunden} ist={pos.ist_stunden} />
                </div>

                <div className="w-28 flex justify-end gap-1">
                  {editId === pos.id ? (
                    <>
                      <button onClick={() => handleIstSave(pos.id)} className="text-xs text-emerald-600 font-medium px-2 py-1">OK</button>
                      <button onClick={() => setEditId(null)} className="text-xs text-slate-400 px-2 py-1">Abbruch</button>
                    </>
                  ) : (
                    <button
                      onClick={() => { setEditId(pos.id); setIstValue(pos.ist_stunden ?? '') }}
                      className="text-xs text-slate-500 hover:text-primary px-2 py-1"
                    >
                      {pos.ist_stunden != null ? 'Bearbeiten' : 'Ist eintragen'}
                    </button>
                  )}
                </div>
              </div>
            ))}

            {/* Summenzeile */}
            <div className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-x-4 items-center px-5 py-4 border-t-2 border-slate-200 bg-slate-50">
              <span className="text-sm font-bold text-ink">Gesamt</span>
              <div className="text-right w-24">
                <p className="text-sm font-bold text-ink">{fmtH(gesamtSoll)}</p>
                <p className="text-xs text-slate-500">{fmtEUR(gesamtSollEUR)}</p>
              </div>
              <div className="text-right w-24">
                <p className={`text-sm font-bold ${gesamtIst != null ? 'text-ink' : 'text-slate-300'}`}>
                  {gesamtIst != null ? fmtH(gesamtIst) : '–'}
                </p>
                <p className="text-xs text-slate-500">{gesamtIstEUR != null ? fmtEUR(gesamtIstEUR) : '–'}</p>
              </div>
              <div className="text-right w-32 text-sm">
                <Abweichung soll={gesamtSoll} ist={gesamtIst} />
              </div>
              <div className="w-28" />
            </div>
          </div>
        )}

        {!istKomplett && positionen.length > 0 && (
          <p className="text-xs text-slate-400 mt-4">
            {positionen.filter(p => p.ist_stunden == null).length} Position(en) ohne Ist-Stunden – trage sie ein um die Abweichung zu sehen.
          </p>
        )}
      </main>
    </div>
  )
}
