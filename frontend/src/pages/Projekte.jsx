import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getProjekte, createProjekt, deleteProjekt } from '../api/angebot'
import NavBar from '../components/NavBar'

const STATUS = {
  entwurf:       { text: 'Entwurf',       cls: 'bg-slate-100 text-slate-600' },
  angeboten:     { text: 'Angeboten',     cls: 'bg-blue-100 text-blue-700' },
  beauftragt:    { text: 'Beauftragt',    cls: 'bg-emerald-100 text-emerald-700' },
  abgeschlossen: { text: 'Abgeschlossen', cls: 'bg-gray-100 text-gray-500' },
}

export default function Projekte() {
  const [projekte,  setProjekte]  = useState([])
  const [loading,   setLoading]   = useState(true)
  const [showForm,      setShowForm]      = useState(false)
  const [name,          setName]          = useState('')
  const [beschreibung,  setBeschreibung]  = useState('')
  const [kunde,         setKunde]         = useState('')
  const [saving,        setSaving]        = useState(false)

  const load = () => getProjekte().then(setProjekte).finally(() => setLoading(false))
  useEffect(() => { load() }, [])

  const handleCreate = async (e) => {
    e.preventDefault()
    if (!name.trim()) return
    setSaving(true)
    try {
      await createProjekt({ name: name.trim(), beschreibung: beschreibung.trim(), kunde: kunde.trim() })
      setName(''); setBeschreibung(''); setKunde(''); setShowForm(false)
      load()
    } finally { setSaving(false) }
  }

  const handleDelete = async (id) => {
    if (!confirm('Projekt und alle Positionen löschen?')) return
    await deleteProjekt(id)
    load()
  }

  return (
    <div className="min-h-screen bg-light">
      <NavBar />

      <main className="max-w-4xl mx-auto px-4 py-10">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-extrabold text-primary">Angebote & Projekte</h1>
            <p className="text-sm text-slate-500 mt-1">Verwalte Leistungspositionen und erstelle Angebote.</p>
          </div>
          <button onClick={() => setShowForm(v => !v)} className="btn-primary flex items-center gap-2">
            + Neues Projekt
          </button>
        </div>

        {showForm && (
          <form onSubmit={handleCreate} className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm mb-6 flex flex-col gap-4">
            <h2 className="font-semibold text-ink">Projekt anlegen</h2>
            <div className="grid sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-slate-500 mb-1">Projektname *</label>
                <input
                  value={name} onChange={e => setName(e.target.value)}
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                  required
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 mb-1">Kunde</label>
                <input
                  value={kunde} onChange={e => setKunde(e.target.value)}
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-500 mb-1">Projektbeschreibung</label>
              <textarea
                value={beschreibung} onChange={e => setBeschreibung(e.target.value)}
                rows={3}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary resize-none"
              />
              <p className="text-xs text-slate-400 mt-0.5">Wird für die Ähnlichkeitssuche nach passenden Referenzprojekten genutzt.</p>
            </div>
            <div className="flex gap-2 justify-end">
              <button type="button" onClick={() => setShowForm(false)} className="btn-secondary text-sm py-2">Abbrechen</button>
              <button type="submit" disabled={saving} className="btn-primary text-sm py-2">{saving ? 'Speichern…' : 'Anlegen'}</button>
            </div>
          </form>
        )}

        {loading ? (
          <div className="text-slate-400 text-center py-20">Lade…</div>
        ) : projekte.filter(p => p.name !== '__historisch__').length === 0 ? (
          <div className="text-center py-20 text-slate-400">
            <p className="text-lg font-medium mb-2">Noch keine Projekte</p>
            <p className="text-sm">Lege dein erstes Projekt an oder importiere historische Positionen.</p>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {projekte.filter(p => p.name !== '__historisch__').map(p => {
              const badge = STATUS[p.status] || STATUS.entwurf
              return (
                <div key={p.id} className="bg-white border border-slate-200 rounded-xl px-5 py-4 shadow-sm flex items-center justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <Link to={`/projekte/${p.id}`} className="font-semibold text-primary hover:underline truncate">
                        {p.name}
                      </Link>
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${badge.cls}`}>{badge.text}</span>
                    </div>
                    <p className="text-xs text-slate-400">{p.kunde || '–'} · {new Date(p.erstellt_am).toLocaleDateString('de-DE')}</p>
                    {p.beschreibung && (
                      <p className="text-xs text-slate-400 mt-0.5 line-clamp-1">{p.beschreibung}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Link to={`/projekte/${p.id}`} className="btn-secondary text-xs py-1.5 px-3">Öffnen</Link>
                    <button onClick={() => handleDelete(p.id)} className="text-xs text-red-500 hover:text-red-700 px-2 py-1.5">Löschen</button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </main>
    </div>
  )
}
