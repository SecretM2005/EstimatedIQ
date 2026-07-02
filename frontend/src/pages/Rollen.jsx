import { useEffect, useState } from 'react'
import { getRollen, createRolle, updateRolle, deleteRolle } from '../api/angebot'

const fmtEUR = n =>
  new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(n)

export default function Rollen() {
  const [rollen,   setRollen]   = useState([])
  const [loading,  setLoading]  = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editId,   setEditId]   = useState(null)
  const [name,     setName]     = useState('')
  const [satz,     setSatz]     = useState('')
  const [saving,   setSaving]   = useState(false)

  const load = () => getRollen().then(setRollen).finally(() => setLoading(false))
  useEffect(() => { load() }, [])

  const openCreate = () => { setEditId(null); setName(''); setSatz(''); setShowForm(true) }
  const openEdit   = (r) => { setEditId(r.id); setName(r.name); setSatz(String(r.stundensatz_eur)); setShowForm(true) }
  const cancel     = () => { setShowForm(false); setEditId(null) }

  const handleSave = async (e) => {
    e.preventDefault()
    setSaving(true)
    try {
      const body = { name: name.trim(), stundensatz_eur: parseFloat(satz) }
      if (editId) await updateRolle(editId, body)
      else        await createRolle(body)
      cancel(); load()
    } finally { setSaving(false) }
  }

  const handleDelete = async (id) => {
    if (!confirm('Rolle löschen?')) return
    await deleteRolle(id); load()
  }

  return (
    <div className="p-8 pb-16 max-w-[900px]">
      {/* Page header */}
      <div className="flex items-end justify-between gap-4 mb-6">
        <div>
          <h1 className="text-[24px] font-bold tracking-tight text-slate-900 m-0">Rollen & Stundensätze</h1>
          <p className="mt-1.5 text-[13.5px] text-slate-500">
            {rollen.length} Rolle{rollen.length !== 1 ? 'n' : ''} · Stundensätze für Angebotspositionen
          </p>
        </div>
        <button
          onClick={openCreate}
          className="h-10 inline-flex items-center gap-2 px-4 bg-accent hover:bg-accent-hover text-white text-[13.5px] font-semibold rounded-lg transition-colors shadow-accent"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"/></svg>
          Neue Rolle
        </button>
      </div>

      {/* Form */}
      {showForm && (
        <form onSubmit={handleSave} className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs mb-5 flex flex-col gap-4">
          <h2 className="text-[14px] font-semibold text-slate-900">{editId ? 'Rolle bearbeiten' : 'Neue Rolle anlegen'}</h2>
          <div className="grid sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Rollenname *</label>
              <input
                value={name} onChange={e => setName(e.target.value)} required
                placeholder="z. B. Senior Developer"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"
              />
            </div>
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Stundensatz (€/h) *</label>
              <input
                type="number" min="1" step="1" value={satz} onChange={e => setSatz(e.target.value)} required
                placeholder="z. B. 120"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"
              />
            </div>
          </div>
          <div className="flex gap-2 justify-end">
            <button type="button" onClick={cancel} className="h-9 px-4 bg-white border border-slate-200 rounded-lg text-sm font-semibold text-slate-700 hover:bg-slate-50 transition-colors">Abbrechen</button>
            <button type="submit" disabled={saving} className="h-9 px-4 bg-accent hover:bg-accent-hover text-white rounded-lg text-sm font-semibold transition-colors disabled:opacity-50">
              {saving ? 'Speichern…' : 'Speichern'}
            </button>
          </div>
        </form>
      )}

      {/* Table */}
      {loading ? (
        <div className="text-slate-400 text-center py-20 text-sm">Lade…</div>
      ) : rollen.length === 0 ? (
        <div className="bg-white border border-slate-200 rounded-xl p-16 text-center shadow-xs">
          <p className="text-[15px] font-semibold text-slate-900 mb-1">Noch keine Rollen</p>
          <p className="text-sm text-slate-500">Lege Rollen wie "Senior Developer" oder "Projektleiter" an.</p>
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
          {/* Head */}
          <div className="grid items-center px-5 py-2.5 bg-slate-50 border-b border-slate-200"
            style={{ gridTemplateColumns: '1fr 160px 120px' }}>
            {['Rolle', 'Stundensatz', ''].map(h => (
              <span key={h} className="text-[10.5px] font-semibold uppercase tracking-[0.04em] text-slate-400">{h}</span>
            ))}
          </div>

          {rollen.map((r, i) => (
            <div
              key={r.id}
              className="grid items-center px-5 py-3.5 border-t border-slate-100 group"
              style={{ gridTemplateColumns: '1fr 160px 120px' }}
            >
              <div className="min-w-0 pr-4">
                <div className="text-[13px] font-semibold text-slate-900">{r.name}</div>
              </div>
              <div className="text-[13px] font-semibold text-slate-900 tabular-nums">
                {fmtEUR(r.stundensatz_eur)}<span className="text-slate-400 font-normal text-[12px]"> / h</span>
              </div>
              <div className="flex items-center justify-end gap-1">
                <button
                  onClick={() => openEdit(r)}
                  className="opacity-0 group-hover:opacity-100 text-[11px] text-slate-500 hover:text-accent px-2 py-1 transition-opacity"
                >Bearbeiten</button>
                <button
                  onClick={() => handleDelete(r.id)}
                  className="opacity-0 group-hover:opacity-100 text-[11px] text-red-400 hover:text-red-600 px-1.5 py-1 transition-opacity"
                >✕</button>
              </div>
            </div>
          ))}

          <div className="flex items-center px-5 py-3 border-t border-slate-200">
            <span className="text-[12px] text-slate-400 tabular-nums">{rollen.length} Rolle{rollen.length !== 1 ? 'n' : ''}</span>
          </div>
        </div>
      )}
    </div>
  )
}
