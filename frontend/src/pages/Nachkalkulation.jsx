import { useEffect, useState, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getProjekt, getPositionen, updateIstStunden } from '../api/angebot'

const fmtEUR = n =>
  new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(n)

const fmtH = n => `${Number(n).toFixed(1)} h`

function Abweichung({ soll, ist }) {
  if (ist == null) return <span className="text-slate-300">–</span>
  const diff = ist - soll
  const pct  = soll > 0 ? Math.round((diff / soll) * 100) : 0
  if (Math.abs(diff) < 0.1) return <span className="text-slate-400">±0</span>
  const cls = diff > 0 ? 'text-red-600' : 'text-emerald-600'
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
    <div className="p-8 text-slate-400 text-sm">Lade…</div>
  )

  const gesamtSoll    = positionen.reduce((s, p) => s + p.soll_stunden, 0)
  const gesamtIst     = positionen.every(p => p.ist_stunden != null)
    ? positionen.reduce((s, p) => s + (p.ist_stunden ?? 0), 0)
    : null
  const gesamtSollEUR = positionen.reduce((s, p) => s + p.soll_stunden * (p.stundensatz_snapshot || 0), 0)
  const gesamtIstEUR  = positionen.every(p => p.ist_stunden != null)
    ? positionen.reduce((s, p) => s + (p.ist_stunden ?? 0) * (p.stundensatz_snapshot || 0), 0)
    : null

  const istKomplett = positionen.length > 0 && positionen.every(p => p.ist_stunden != null)

  return (
    <div className="p-8 pb-16 max-w-[1200px]">
      {/* Breadcrumb + header */}
      <div className="flex items-start justify-between gap-4 mb-6">
        <div>
          <Link
            to={`/projekte/${projekt_id}`}
            className="inline-flex items-center gap-1 text-[12px] text-slate-400 hover:text-slate-600 mb-2 transition-colors"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none"><path d="M15 18l-6-6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
            {projekt?.name}
          </Link>
          <h1 className="text-[24px] font-bold tracking-tight text-slate-900 m-0">Nachkalkulation</h1>
          <p className="mt-1 text-[13.5px] text-slate-500">{projekt?.kunde || '–'}</p>
        </div>

        {/* Summary cards */}
        <div className="flex gap-3 shrink-0">
          <div className="bg-white border border-slate-200 rounded-xl px-5 py-3 text-right shadow-xs">
            <p className="text-[11px] text-slate-400 mb-0.5 uppercase tracking-wide font-semibold">Soll</p>
            <p className="text-[20px] font-bold text-slate-900 tabular-nums">{fmtH(gesamtSoll)}</p>
            <p className="text-[11.5px] text-slate-400 tabular-nums">{fmtEUR(gesamtSollEUR)}</p>
          </div>
          <div className={`border rounded-xl px-5 py-3 text-right shadow-xs ${istKomplett ? 'bg-white border-slate-200' : 'bg-slate-50 border-slate-100'}`}>
            <p className="text-[11px] text-slate-400 mb-0.5 uppercase tracking-wide font-semibold">Ist</p>
            <p className={`text-[20px] font-bold tabular-nums ${istKomplett ? 'text-slate-900' : 'text-slate-300'}`}>
              {gesamtIst != null ? fmtH(gesamtIst) : '–'}
            </p>
            <p className="text-[11.5px] text-slate-400 tabular-nums">{gesamtIstEUR != null ? fmtEUR(gesamtIstEUR) : '–'}</p>
          </div>
          {istKomplett && gesamtIst != null && (
            <div className={`border rounded-xl px-5 py-3 text-right shadow-xs ${
              gesamtIst > gesamtSoll ? 'bg-red-50 border-red-200' : 'bg-emerald-50 border-emerald-200'
            }`}>
              <p className="text-[11px] text-slate-400 mb-0.5 uppercase tracking-wide font-semibold">Abweichung</p>
              <p className={`text-[20px] font-bold tabular-nums ${gesamtIst > gesamtSoll ? 'text-red-600' : 'text-emerald-700'}`}>
                {gesamtIst > gesamtSoll ? '+' : ''}{fmtH(gesamtIst - gesamtSoll)}
              </p>
              <p className={`text-[11.5px] font-medium ${gesamtIst > gesamtSoll ? 'text-red-500' : 'text-emerald-600'}`}>
                {gesamtSoll > 0 ? `${gesamtIst > gesamtSoll ? '+' : ''}${Math.round(((gesamtIst - gesamtSoll) / gesamtSoll) * 100)} %` : ''}
              </p>
            </div>
          )}
        </div>
      </div>

      {positionen.length === 0 ? (
        <div className="bg-white border border-slate-200 rounded-xl p-16 text-center shadow-xs">
          <p className="text-[15px] font-semibold text-slate-900 mb-1">Keine Positionen</p>
          <p className="text-sm text-slate-500">Dieses Projekt hat noch keine Positionen.</p>
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
          {/* Head */}
          <div
            className="grid items-center px-5 py-2.5 bg-slate-50 border-b border-slate-200"
            style={{ gridTemplateColumns: '1fr 110px 110px 160px 120px' }}
          >
            {['Position', 'Soll', 'Ist', 'Abweichung', ''].map(h => (
              <span key={h} className="text-[10.5px] font-semibold uppercase tracking-[0.04em] text-slate-400 text-right first:text-left last:text-right">{h}</span>
            ))}
          </div>

          {positionen.map((pos, i) => (
            <div
              key={pos.id}
              className={`grid items-center px-5 py-3.5 border-t border-slate-100 ${
                pos.ist_stunden != null && pos.ist_stunden > pos.soll_stunden ? 'bg-red-50/40' : ''
              }`}
              style={{ gridTemplateColumns: '1fr 110px 110px 160px 120px' }}
            >
              <div className="min-w-0 pr-4">
                <p className="text-[13px] font-medium text-slate-900 truncate">{pos.beschreibung_text}</p>
                <p className="text-[11.5px] text-slate-400 mt-0.5">
                  {pos.rolle_name || '–'}
                  {pos.stundensatz_snapshot ? ` · ${pos.stundensatz_snapshot} €/h` : ''}
                </p>
              </div>

              <div className="text-right">
                <p className="text-[13px] font-medium text-slate-900 tabular-nums">{fmtH(pos.soll_stunden)}</p>
                {pos.stundensatz_snapshot > 0 && (
                  <p className="text-[11.5px] text-slate-400 tabular-nums">{fmtEUR(pos.soll_stunden * pos.stundensatz_snapshot)}</p>
                )}
              </div>

              <div className="text-right">
                {editId === pos.id ? (
                  <div className="flex items-center gap-1 justify-end">
                    <input
                      type="number" value={istValue} min="0" step="0.5"
                      onChange={e => setIstValue(e.target.value)}
                      className="w-16 border border-slate-200 rounded px-2 py-1 text-xs text-right focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"
                      autoFocus
                    />
                    <span className="text-[11.5px] text-slate-400">h</span>
                  </div>
                ) : (
                  <>
                    <p className={`text-[13px] font-medium tabular-nums ${pos.ist_stunden != null ? 'text-slate-900' : 'text-slate-300'}`}>
                      {pos.ist_stunden != null ? fmtH(pos.ist_stunden) : '–'}
                    </p>
                    {pos.ist_stunden != null && pos.stundensatz_snapshot > 0 && (
                      <p className="text-[11.5px] text-slate-400 tabular-nums">{fmtEUR(pos.ist_stunden * pos.stundensatz_snapshot)}</p>
                    )}
                  </>
                )}
              </div>

              <div className="text-right text-[13px]">
                <Abweichung soll={pos.soll_stunden} ist={pos.ist_stunden} />
              </div>

              <div className="flex justify-end gap-1">
                {editId === pos.id ? (
                  <>
                    <button onClick={() => handleIstSave(pos.id)} className="text-[11.5px] text-emerald-600 font-semibold px-2 py-1 hover:text-emerald-700">OK</button>
                    <button onClick={() => setEditId(null)} className="text-[11.5px] text-slate-400 px-2 py-1">Abbruch</button>
                  </>
                ) : (
                  <button
                    onClick={() => { setEditId(pos.id); setIstValue(pos.ist_stunden ?? '') }}
                    className="text-[11.5px] text-slate-500 hover:text-accent px-2 py-1 transition-colors"
                  >
                    {pos.ist_stunden != null ? 'Bearbeiten' : 'Ist eintragen'}
                  </button>
                )}
              </div>
            </div>
          ))}

          {/* Total row */}
          <div
            className="grid items-center px-5 py-4 border-t-2 border-slate-200 bg-slate-50"
            style={{ gridTemplateColumns: '1fr 110px 110px 160px 120px' }}
          >
            <span className="text-[13px] font-bold text-slate-900">Gesamt</span>
            <div className="text-right">
              <p className="text-[13px] font-bold text-slate-900 tabular-nums">{fmtH(gesamtSoll)}</p>
              <p className="text-[11.5px] text-slate-500 tabular-nums">{fmtEUR(gesamtSollEUR)}</p>
            </div>
            <div className="text-right">
              <p className={`text-[13px] font-bold tabular-nums ${gesamtIst != null ? 'text-slate-900' : 'text-slate-300'}`}>
                {gesamtIst != null ? fmtH(gesamtIst) : '–'}
              </p>
              <p className="text-[11.5px] text-slate-500 tabular-nums">{gesamtIstEUR != null ? fmtEUR(gesamtIstEUR) : '–'}</p>
            </div>
            <div className="text-right text-[13px]">
              <Abweichung soll={gesamtSoll} ist={gesamtIst} />
            </div>
            <div />
          </div>
        </div>
      )}

      {!istKomplett && positionen.length > 0 && (
        <p className="text-[12px] text-slate-400 mt-4">
          {positionen.filter(p => p.ist_stunden == null).length} Position(en) ohne Ist-Stunden — trage sie ein um die Abweichung zu sehen.
        </p>
      )}
    </div>
  )
}
