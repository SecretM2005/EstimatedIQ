import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
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
    <div className="min-h-screen bg-light">
      <header className="px-6 py-4 flex items-center justify-between bg-white border-b border-slate-200">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
            <span className="text-white font-bold text-sm">IQ</span>
          </div>
          <span className="font-bold text-primary text-lg">EstimateIQ</span>
        </div>
        <nav className="flex items-center gap-2">
          <Link to="/projekte" className="btn-secondary text-sm py-2">Projekte</Link>
          <Link to="/"         className="btn-secondary text-sm py-2">Kostenschätzung</Link>
        </nav>
      </header>

      <main className="max-w-2xl mx-auto px-4 py-10">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-extrabold text-primary">Rollen & Stundensätze</h1>
            <p className="text-sm text-slate-500 mt-1">Verwalte Rollen und ihre Stundensätze für Angebotspositionen.</p>
          </div>
          <button onClick={openCreate} className="btn-primary text-sm py-2 px-4">+ Neue Rolle</button>
        </div>

        {showForm && (
          <form onSubmit={handleSave} className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm mb-6 flex flex-col gap-4">
            <h2 className="font-semibold text-ink">{editId ? 'Rolle bearbeiten' : 'Neue Rolle'}</h2>
            <div className="grid sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-slate-500 mb-1">Rollenname *</label>
                <input
                  value={name} onChange={e => setName(e.target.value)}
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                  placeholder="z.B. Senior Developer" required
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 mb-1">Stundensatz (€/h) *</label>
                <input
                  type="number" min="1" step="1" value={satz} onChange={e => setSatz(e.target.value)}
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                  placeholder="z.B. 120" required
                />
              </div>
            </div>
            <div className="flex gap-2 justify-end">
              <button type="button" onClick={cancel} className="btn-secondary text-sm py-2">Abbrechen</button>
              <button type="submit" disabled={saving} className="btn-primary text-sm py-2">{saving ? 'Speichern…' : 'Speichern'}</button>
            </div>
          </form>
        )}

        {loading ? (
          <div className="text-slate-400 text-center py-20">Lade…</div>
        ) : rollen.length === 0 ? (
          <div className="text-center py-20 text-slate-400">
            <p className="font-medium">Noch keine Rollen</p>
            <p className="text-sm mt-1">Lege Rollen wie "Senior Developer" oder "Projektleiter" an.</p>
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            {rollen.map((r, i) => (
              <div key={r.id} className={`flex items-center justify-between px-5 py-4 ${i > 0 ? 'border-t border-slate-100' : ''}`}>
                <div>
                  <p className="font-medium text-ink">{r.name}</p>
                  <p className="text-xs text-slate-400">{fmtEUR(r.stundensatz_eur)} / Stunde</p>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => openEdit(r)} className="text-xs text-primary hover:underline px-2 py-1">Bearbeiten</button>
                  <button onClick={() => handleDelete(r.id)} className="text-xs text-red-500 hover:text-red-700 px-2 py-1">Löschen</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
