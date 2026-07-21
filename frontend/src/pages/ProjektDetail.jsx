import { useEffect, useState, useCallback } from 'react'
import { useParams, Link, useLocation } from 'react-router-dom'
import {
  getProjekt, getPositionen, createPosition, deletePosition,
  updateIstStunden, sucheAehnliche, createAngebot, openAngebotPdf, getRollen,
  sucheReferenzprojekte, vorlagUebernehmen, updateProjekt, updateProjektStatus,
} from '../api/angebot'

const fmtEUR = n =>
  new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(n)

const STATUS_META = {
  entwurf:       { label: 'Entwurf',      bg: '#fffbeb', color: '#b45309', border: '#fef3c7' },
  angeboten:     { label: 'Angeboten',    bg: '#eef2ff', color: '#4f46e5', border: '#e0e7ff' },
  beauftragt:    { label: 'In Arbeit',    bg: '#f0fdfa', color: '#0f766e', border: '#99f6e4' },
  abgeschlossen: { label: 'Abgeschlossen',bg: '#f8fafc', color: '#475569', border: '#e2e8f0' },
  abgelehnt:     { label: 'Abgelehnt',    bg: '#fef2f2', color: '#b91c1c', border: '#fecaca' },
}

function StatusBadge({ status }) {
  const s = STATUS_META[status] || STATUS_META.entwurf
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', height: 24, padding: '0 10px',
      fontSize: 12, fontWeight: 600, borderRadius: 999,
      background: s.bg, color: s.color, border: `1px solid ${s.border}`,
    }}>{s.label}</span>
  )
}

function AblehnungModal({ onConfirm, onCancel }) {
  const [grund, setGrund] = useState('')
  return (
    <div className="fixed inset-0 bg-slate-900/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl border border-slate-200 w-full max-w-md p-6">
        <h3 className="text-[15px] font-semibold text-slate-900 mb-1">Angebot ablehnen</h3>
        <p className="text-[13px] text-slate-500 mb-4">Der Ablehnungsgrund wird für die spätere ML-Verbesserung gespeichert.</p>
        <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Ablehnungsgrund (optional)</label>
        <textarea value={grund} onChange={e => setGrund(e.target.value)} rows={3}
          placeholder="z. B. Preis zu hoch, Vergabe an Mitbewerber …"
          className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-red-400/30 focus:border-red-400 resize-none" autoFocus />
        <div className="flex gap-2 mt-4 justify-end">
          <button onClick={onCancel} className="h-9 px-4 bg-white border border-slate-200 rounded-lg text-[13px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors">Abbrechen</button>
          <button onClick={() => onConfirm(grund)} className="h-9 px-4 bg-red-600 hover:bg-red-700 text-white rounded-lg text-[13px] font-semibold transition-colors">Als abgelehnt markieren</button>
        </div>
      </div>
    </div>
  )
}

function SimilarityBar({ value }) {
  const pct = Math.round(value * 100)
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
        <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[11px] text-slate-500 tabular-nums w-8 text-right">{pct}%</span>
    </div>
  )
}

// ─── Projekt-mode sub-components ─────────────────────────────────────────────

function PhaseRow({ phase, soll, ist }) {
  const pct      = soll > 0 ? (ist / soll) * 100 : 0
  const over     = ist > soll
  const diff     = Math.round(ist - soll)
  const barColor = over ? '#d97706' : '#0f766e'
  return (
    <div className="flex items-center gap-3 py-2">
      <span className="text-[12.5px] text-slate-700 w-40 shrink-0 truncate">{phase}</span>
      <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${Math.min(pct, 100)}%`, background: barColor }} />
      </div>
      <span className="text-[12px] text-slate-500 w-28 text-right tabular-nums shrink-0">
        {Math.round(soll)} / {Math.round(ist)} h
        <span className={`ml-1.5 font-semibold ${over ? 'text-amber-600' : 'text-emerald-600'}`}>
          {over ? '+' : ''}{diff}
        </span>
      </span>
    </div>
  )
}

function EckdatenRow({ label, value }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5 border-b border-slate-100 last:border-0">
      <span className="text-[12px] text-slate-400 shrink-0">{label}</span>
      <span className="text-[12.5px] text-slate-900 font-medium text-right truncate">{value || '–'}</span>
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function ProjektDetail() {
  const { id }     = useParams()
  const projekt_id = parseInt(id)
  const location   = useLocation()
  const isAngebot  = location.pathname.startsWith('/angebote/')

  const [projekt,    setProjekt]    = useState(null)
  const [positionen, setPositionen] = useState([])
  const [rollen,     setRollen]     = useState([])
  const [loading,    setLoading]    = useState(true)

  // Position form state
  const [beschreibung, setBeschreibung] = useState('')
  const [stunden,      setStunden]      = useState('')
  const [rolleId,      setRolleId]      = useState('')
  const [satz,         setSatz]         = useState('')
  const [phase,        setPhase]        = useState('')
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

  const [statusSaving, setStatusSaving] = useState(false)
  const [ablehnModal,  setAblehnModal]  = useState(false)

  // Projekt-mode tabs
  const [tab, setTab] = useState('uebersicht')

  // Inline edit for Eckdaten
  const [editEckdaten, setEditEckdaten] = useState(false)
  const [eckForm, setEckForm] = useState({})
  const [savingEck, setSavingEck] = useState(false)

  const load = useCallback(async () => {
    const [p, pos, r] = await Promise.all([
      getProjekt(projekt_id),
      getPositionen(projekt_id),
      getRollen(),
    ])
    setProjekt(p); setPositionen(pos); setRollen(r)
    setBeschreibungText(p.beschreibung || '')
    setEckForm({
      leitung: p.leitung || '', auftragswert: p.auftragswert || '',
      abrechnung_typ: p.abrechnung_typ || '', laufzeit_start: p.laufzeit_start || '',
      laufzeit_end: p.laufzeit_end || '', kunde: p.kunde || '',
    })
    setLoading(false)
    if (isAngebot) {
      const suchbeschreibung = p.beschreibung?.trim() || p.name
      try {
        const refs = await sucheReferenzprojekte({
          beschreibung: suchbeschreibung, name: p.name, k: 1, exclude_projekt_id: projekt_id,
        })
        setRefErgebnisse(refs)
      } catch { setRefErgebnisse([]) }
    }
  }, [projekt_id, isAngebot])

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

  const gesamtSoll = aktivPositionen.reduce((s, p) => s + (p.soll_stunden * (p.stundensatz_snapshot || 0)), 0)
  const gesamtIst  = aktivPositionen.reduce((s, p) => s + ((p.ist_stunden || 0) * (p.stundensatz_snapshot || 0)), 0)

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
        phase:             phase.trim(),
      })
      setBeschreibung(''); setStunden(''); setRolleId(''); setSatz(''); setPhase('')
      setSuchErgebnis(null)
      load()
    } finally { setSaving(false) }
  }

  const handleSuche = async () => {
    if (!beschreibung.trim()) return
    setSucheLoading(true)
    try {
      const res = await sucheAehnliche({ beschreibung_text: beschreibung.trim(), k: 5, exclude_projekt_id: projekt_id })
      setSuchErgebnis(res)
      if (res.schaetzvorschlag && !stunden) setStunden(String(res.schaetzvorschlag))
    } catch { setSuchErgebnis(null) }
    finally { setSucheLoading(false) }
  }

  const handleBeschreibungSave = async () => {
    setSavingBeschreibung(true)
    try {
      await updateProjekt(projekt_id, { beschreibung: beschreibungText.trim() })
      setEditBeschreibung(false); load()
    } finally { setSavingBeschreibung(false) }
  }

  const handleEckdatenSave = async () => {
    setSavingEck(true)
    try {
      await updateProjekt(projekt_id, {
        leitung:       eckForm.leitung || null,
        auftragswert:  eckForm.auftragswert ? parseFloat(eckForm.auftragswert) : null,
        abrechnung_typ: eckForm.abrechnung_typ || null,
        laufzeit_start: eckForm.laufzeit_start || null,
        laufzeit_end:   eckForm.laufzeit_end || null,
        kunde:          eckForm.kunde || '',
      })
      setEditEckdaten(false); load()
    } finally { setSavingEck(false) }
  }

  const handleVorlageUebernehmen = async (refId) => {
    setRefUebernommenId(refId)
    try { await vorlagUebernehmen(projekt_id, refId); setRefErgebnisse(null); load() }
    finally { setRefUebernommenId(null) }
  }

  const handleIstSave = async (posId) => {
    const val = parseFloat(istValue)
    if (isNaN(val) || val <= 0) return
    await updateIstStunden(posId, val)
    setEditIstId(null); load()
  }

  const handleStatusChange = async (status, ablehnungsgrund = null) => {
    setStatusSaving(true)
    try { await updateProjektStatus(projekt_id, { status, ablehnungsgrund }); load() }
    finally { setStatusSaving(false) }
  }

  const handlePdf = async () => {
    setPdfLoading(true)
    try {
      const a = await createAngebot(projekt_id, { titel: `Angebot ${projekt?.name}` })
      await openAngebotPdf(a.id)
    } finally { setPdfLoading(false) }
  }

  if (loading) return <div className="p-8 text-slate-400 text-sm">Lade…</div>

  const bestRef = refErgebnisse?.length > 0 ? refErgebnisse[0] : null

  // ─── Phase-Aggregation für Übersicht ───────────────────────────────────────
  const phaseMap = {}
  aktivPositionen.forEach(pos => {
    const key = pos.phase?.trim() || 'Allgemein'
    if (!phaseMap[key]) phaseMap[key] = { soll: 0, ist: 0 }
    phaseMap[key].soll += pos.soll_stunden
    phaseMap[key].ist  += pos.ist_stunden || 0
  })
  const phases = Object.entries(phaseMap)

  // ─── Rollen-Aggregation ────────────────────────────────────────────────────
  const rolleMap = {}
  aktivPositionen.forEach(pos => {
    const key = pos.rolle_name || 'Ohne Rolle'
    const satz = pos.stundensatz_snapshot || 0
    if (!rolleMap[key]) rolleMap[key] = { soll: 0, ist: 0, satz, kosten: 0 }
    rolleMap[key].soll  += pos.soll_stunden
    rolleMap[key].ist   += pos.ist_stunden || 0
    rolleMap[key].kosten += (pos.ist_stunden || 0) * satz
    if (!rolleMap[key].satz && satz) rolleMap[key].satz = satz
  })
  const rollenStats = Object.entries(rolleMap)

  const auftragswert = projekt?.auftragswert
  const restbudget   = auftragswert ? auftragswert - gesamtIst : null
  const margeAktuell = auftragswert && gesamtIst > 0
    ? (auftragswert - gesamtIst) / auftragswert * 100
    : auftragswert ? (auftragswert - gesamtSoll) / auftragswert * 100 : null

  const gesamtSollH   = aktivPositionen.reduce((s, p) => s + p.soll_stunden, 0)
  const gesamtIstH    = aktivPositionen.reduce((s, p) => s + (p.ist_stunden || 0), 0)
  const istUeberSoll  = gesamtIstH > gesamtSollH

  const PRJ_NR = `PRJ-${new Date(projekt.erstellt_am).getFullYear()}-${String(projekt.id).padStart(4, '0')}`

  // ─── ANGEBOT MODE ────────────────────────────────────────────────────────────
  if (isAngebot) {
    return (
      <div className="flex items-start">
        <div className="flex-1 min-w-0 p-8 pb-16">
          <Link to="/angebote" className="inline-flex items-center gap-1 text-[12px] text-slate-400 hover:text-slate-600 mb-4 transition-colors">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none"><path d="M15 18l-6-6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
            Angebote
          </Link>

          <div className="flex items-start justify-between gap-6 mb-6">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-3 mb-1 flex-wrap">
                <h1 className="text-[24px] font-bold tracking-tight text-slate-900 m-0 truncate">{projekt?.name}</h1>
                <StatusBadge status={projekt?.status} />
              </div>
              {projekt?.kunde && <p className="text-[13px] text-slate-500">{projekt.kunde}</p>}
              {projekt?.status === 'abgelehnt' && projekt?.ablehnungsgrund && (
                <p className="text-[12.5px] text-red-500 mt-1 italic">Abgelehnt: {projekt.ablehnungsgrund}</p>
              )}
              <div className="mt-3">
                {editBeschreibung ? (
                  <div className="flex flex-col gap-2">
                    <textarea value={beschreibungText} onChange={e => setBeschreibungText(e.target.value)} rows={3}
                      placeholder="Projektbeschreibung – wird für die Ähnlichkeitssuche genutzt"
                      className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent resize-none" autoFocus />
                    <div className="flex gap-2">
                      <button onClick={handleBeschreibungSave} disabled={savingBeschreibung}
                        className="h-8 px-3 bg-accent hover:bg-accent-hover text-white rounded-lg text-[12px] font-semibold transition-colors disabled:opacity-50">
                        {savingBeschreibung ? 'Speichern…' : 'Speichern'}
                      </button>
                      <button onClick={() => { setEditBeschreibung(false); setBeschreibungText(projekt?.beschreibung || '') }}
                        className="h-8 px-3 bg-white border border-slate-200 rounded-lg text-[12px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors">
                        Abbrechen
                      </button>
                    </div>
                  </div>
                ) : (
                  <div onClick={() => setEditBeschreibung(true)} className="group cursor-pointer">
                    {projekt?.beschreibung
                      ? <p className="text-[13px] text-slate-600 leading-relaxed group-hover:text-slate-800 transition-colors">{projekt.beschreibung}<span className="ml-1.5 text-[12px] text-slate-300 group-hover:text-slate-400 transition-colors">✎</span></p>
                      : <p className="text-[13px] text-slate-300 italic group-hover:text-slate-400 transition-colors">Projektbeschreibung hinzufügen… <span className="not-italic">✎</span></p>}
                  </div>
                )}
              </div>
            </div>

            <div className="shrink-0 flex flex-col items-end gap-3">
              <div className="text-right">
                <p className="text-[11px] text-slate-400 uppercase tracking-wide font-semibold mb-0.5">Angebotssumme</p>
                <p className="text-[28px] font-bold text-slate-900 tabular-nums leading-none">{fmtEUR(gesamtSoll)}</p>
              </div>
              <div className="flex gap-2 flex-wrap justify-end">
                {projekt?.status === 'entwurf' && (
                  <button onClick={() => handleStatusChange('angeboten')} disabled={statusSaving}
                    className="h-9 px-3 bg-indigo-50 hover:bg-indigo-100 text-accent border border-indigo-100 rounded-lg text-[13px] font-semibold transition-colors disabled:opacity-50 inline-flex items-center">
                    Versenden →
                  </button>
                )}
                {projekt?.status === 'angeboten' && (
                  <>
                    <button onClick={() => handleStatusChange('beauftragt')} disabled={statusSaving}
                      className="h-9 px-3 bg-emerald-50 hover:bg-emerald-100 text-emerald-700 border border-emerald-100 rounded-lg text-[13px] font-semibold transition-colors disabled:opacity-50 inline-flex items-center">
                      ✓ Auftrag erhalten
                    </button>
                    <button onClick={() => setAblehnModal(true)} disabled={statusSaving}
                      className="h-9 px-3 bg-red-50 hover:bg-red-100 text-red-600 border border-red-100 rounded-lg text-[13px] font-semibold transition-colors disabled:opacity-50 inline-flex items-center">
                      Ablehnen
                    </button>
                  </>
                )}
                {projekt?.status === 'beauftragt' && (
                  <button onClick={() => handleStatusChange('abgeschlossen')} disabled={statusSaving}
                    className="h-9 px-3 bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-200 rounded-lg text-[13px] font-semibold transition-colors disabled:opacity-50 inline-flex items-center">
                    Abschließen
                  </button>
                )}
              </div>
              <div className="flex gap-2">
                <button onClick={handlePdf} disabled={pdfLoading || aktivPositionen.length === 0}
                  className="h-9 px-4 bg-accent hover:bg-accent-hover text-white rounded-lg text-[13px] font-semibold transition-colors shadow-accent disabled:opacity-40 inline-flex items-center gap-1.5">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  {pdfLoading ? 'PDF erstellen…' : 'PDF'}
                </button>
              </div>
            </div>
          </div>

          {/* Add position form */}
          <PositionForm
            beschreibung={beschreibung} setBeschreibung={setBeschreibung}
            stunden={stunden} setStunden={setStunden}
            rolleId={rolleId} handleRolleChange={handleRolleChange}
            satz={satz} setSatz={setSatz}
            phase={phase} setPhase={setPhase}
            rollen={rollen} saving={saving} sucheLoading={sucheLoading}
            onSubmit={handleAddPosition} onSuche={handleSuche}
            suchErgebnis={suchErgebnis}
          />

          {/* Positions table */}
          <PositionenTabelle
            positionen={aktivPositionen} gesamtSoll={gesamtSoll}
            editIstId={editIstId} istValue={istValue} setIstValue={setIstValue}
            setEditIstId={setEditIstId} handleIstSave={handleIstSave}
            onDelete={async id => { await deletePosition(id); load() }}
          />
        </div>

        {/* Reference panel */}
        {isAngebot && (
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
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-[0.04em] text-slate-400 mb-2">Positionen</p>
                    <div className="flex flex-col gap-1">
                      {bestRef.positionen.slice(0, 6).map((p, i) => (
                        <div key={i} className="flex items-start justify-between gap-2 py-1.5 border-b border-slate-100 last:border-0">
                          <p className="text-[12px] text-slate-700 flex-1 min-w-0 leading-snug line-clamp-2">{p.beschreibung_text}</p>
                          <div className="shrink-0 text-right">
                            <span className="text-[12px] font-medium text-slate-900 tabular-nums">{p.soll_stunden} h</span>
                            {p.stundensatz_snapshot && <p className="text-[10.5px] text-slate-400 tabular-nums">{p.stundensatz_snapshot} €/h</p>}
                          </div>
                        </div>
                      ))}
                      {bestRef.n_positionen > 6 && <p className="text-[11.5px] text-slate-400 pt-1">… und {bestRef.n_positionen - 6} weitere</p>}
                    </div>
                  </div>
                  <button onClick={() => handleVorlageUebernehmen(bestRef.projekt_id)} disabled={refUebernommenId === bestRef.projekt_id}
                    className="w-full h-9 bg-accent hover:bg-accent-hover text-white rounded-lg text-[13px] font-semibold transition-colors shadow-accent disabled:opacity-50">
                    {refUebernommenId === bestRef.projekt_id ? 'Übernehme…' : 'Als Vorlage übernehmen'}
                  </button>
                  <p className="text-[11.5px] text-slate-400 text-center -mt-2">Alle Positionen werden in dieses Projekt kopiert</p>
                </div>
              )}
            </div>
          </div>
        )}

        {ablehnModal && (
          <AblehnungModal
            onConfirm={async (grund) => { setAblehnModal(false); await handleStatusChange('abgelehnt', grund || null) }}
            onCancel={() => setAblehnModal(false)}
          />
        )}
      </div>
    )
  }

  // ─── PROJEKT MODE (tabs) ─────────────────────────────────────────────────────
  const TABS = [
    { key: 'uebersicht',   label: 'Übersicht' },
    { key: 'kalkulation',  label: 'Kalkulation' },
    { key: 'zeiterfassung',label: 'Zeiterfassung' },
    { key: 'dokumente',    label: 'Dokumente' },
  ]

  return (
    <div>
      {/* Page header */}
      <div className="bg-white border-b border-slate-200 px-8 pt-5 pb-0">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-[12px] text-slate-400 mb-3">
          <Link to="/projekte" className="hover:text-slate-600 transition-colors">Projekte</Link>
          <span>·</span>
          <span className="font-medium text-slate-600">{PRJ_NR}</span>
          <span>·</span>
          <StatusBadge status={projekt?.status} />
          {istUeberSoll && gesamtIstH > 0 && (
            <>
              <span>·</span>
              <span className="text-amber-600 font-semibold">über Soll</span>
            </>
          )}
        </div>

        <div className="flex items-start justify-between gap-6 mb-4">
          <div>
            <h1 className="text-[22px] font-bold tracking-tight text-slate-900 m-0">
              {projekt?.name}{projekt?.kunde ? ` — ${projekt.kunde}` : ''}
            </h1>
          </div>
          <div className="flex gap-2 shrink-0">
            <button onClick={() => setTab('zeiterfassung')}
              className="h-9 px-4 bg-white border border-slate-200 rounded-lg text-[13px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors inline-flex items-center gap-1.5">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.9"/><path d="M12 7v5l3 3" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/></svg>
              Zeiten erfassen
            </button>
            <button onClick={() => setTab('kalkulation')}
              className="h-9 px-4 bg-accent hover:bg-accent-hover text-white rounded-lg text-[13px] font-semibold transition-colors shadow-accent inline-flex items-center gap-1.5">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round"/><path d="M14 2v6h6M9 13h6M9 17h4" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/></svg>
              Kalkulation öffnen
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-0">
          {TABS.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`h-10 px-4 text-[13px] font-medium border-b-2 transition-colors ${
                tab === t.key
                  ? 'border-accent text-accent font-semibold'
                  : 'border-transparent text-slate-500 hover:text-slate-700'
              }`}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="p-8 pb-16">

        {/* ── Übersicht ── */}
        {tab === 'uebersicht' && (
          <div className="flex items-start gap-6">
            {/* Left */}
            <div className="flex-1 min-w-0 flex flex-col gap-5">

              {/* Soll/Ist nach Phase */}
              <div className="bg-white border border-slate-200 rounded-xl shadow-xs p-5">
                <div className="flex items-center justify-between mb-1">
                  <h2 className="text-[13.5px] font-semibold text-slate-900">Soll / Ist nach Phase</h2>
                  <span className={`text-[12px] font-semibold tabular-nums ${istUeberSoll ? 'text-amber-600' : 'text-emerald-600'}`}>
                    Gesamt {Math.round(gesamtSollH)} → {Math.round(gesamtIstH)} Std.
                    {gesamtSollH > 0 && (
                      <span> · {istUeberSoll ? '+' : ''}{Math.round(((gesamtIstH / gesamtSollH) - 1) * 100)} %</span>
                    )}
                  </span>
                </div>
                {phases.length === 0 ? (
                  <p className="text-[13px] text-slate-400 mt-4">Noch keine Positionen vorhanden.</p>
                ) : (
                  <div className="mt-3 divide-y divide-slate-100">
                    {phases.map(([ph, stat]) => (
                      <PhaseRow key={ph} phase={ph} soll={stat.soll} ist={stat.ist} />
                    ))}
                  </div>
                )}
                <div className="flex items-center gap-4 mt-4 pt-3 border-t border-slate-100">
                  <LegendDot color="#cbd5e1" label="Soll" />
                  <LegendDot color="#0f766e" label="Ist (im Rahmen)" />
                  <LegendDot color="#d97706" label="Ist (über Soll)" />
                </div>
              </div>

              {/* Stunden nach Rolle */}
              {rollenStats.length > 0 && (
                <div className="bg-white border border-slate-200 rounded-xl shadow-xs p-5">
                  <h2 className="text-[13.5px] font-semibold text-slate-900 mb-4">Stunden nach Rolle</h2>
                  <div className="overflow-x-auto">
                    <table className="w-full text-[12.5px]">
                      <thead>
                        <tr className="border-b border-slate-200">
                          {['Rolle', 'Soll', 'Ist', 'Satz', 'Ist-Kosten'].map(h => (
                            <th key={h} className={`py-2 font-semibold text-[10.5px] uppercase tracking-[0.05em] text-slate-400 ${h === 'Rolle' ? 'text-left' : 'text-right'}`}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {rollenStats.map(([name, s]) => (
                          <tr key={name} className="border-b border-slate-100 last:border-0">
                            <td className="py-2.5 pr-4">
                              <span className="inline-flex items-center gap-1.5">
                                <span className="w-2 h-2 rounded-full bg-accent/30 flex-none" />
                                {name}
                              </span>
                            </td>
                            <td className="py-2.5 text-right tabular-nums text-slate-700">{Math.round(s.soll)}</td>
                            <td className={`py-2.5 text-right tabular-nums font-semibold ${s.ist > s.soll ? 'text-amber-600' : 'text-slate-700'}`}>{Math.round(s.ist)}</td>
                            <td className="py-2.5 text-right tabular-nums text-slate-500">{s.satz ? `${s.satz} €` : '–'}</td>
                            <td className="py-2.5 text-right tabular-nums text-slate-700">{s.kosten > 0 ? fmtEUR(s.kosten) : '–'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>

            {/* Right panels */}
            <div className="w-[300px] flex-none flex flex-col gap-4">

              {/* Budget & Marge */}
              <div className="bg-white border border-slate-200 rounded-xl shadow-xs p-5">
                <h2 className="text-[13px] font-semibold text-slate-900 mb-3">Budget & Marge</h2>
                {auftragswert ? (
                  <>
                    <div className="text-[12px] text-slate-500 mb-1 flex items-baseline justify-between">
                      <span>Ist-Kosten / Auftragswert</span>
                    </div>
                    <div className="text-[13px] font-semibold text-slate-900 mb-2 tabular-nums">
                      {fmtEUR(gesamtIst)} / {fmtEUR(auftragswert)}
                    </div>
                    <div className="h-2 bg-slate-100 rounded-full overflow-hidden mb-3">
                      <div className="h-full rounded-full"
                        style={{ width: `${Math.min((gesamtIst / auftragswert) * 100, 100)}%`, background: gesamtIst > auftragswert ? '#dc2626' : '#0f766e' }} />
                    </div>
                    <div className="grid grid-cols-2 gap-3 mb-3">
                      <div className="bg-slate-50 rounded-lg p-3">
                        <p className="text-[10.5px] font-semibold uppercase tracking-wide text-slate-400 mb-0.5">Restbudget</p>
                        <p className={`text-[16px] font-bold tabular-nums ${restbudget < 0 ? 'text-red-600' : 'text-slate-900'}`}>{fmtEUR(restbudget)}</p>
                      </div>
                      <div className="bg-slate-50 rounded-lg p-3">
                        <p className="text-[10.5px] font-semibold uppercase tracking-wide text-slate-400 mb-0.5">Marge aktuell</p>
                        <p className={`text-[16px] font-bold tabular-nums ${margeAktuell < 20 ? 'text-amber-600' : 'text-slate-900'}`}>
                          {margeAktuell != null ? `${margeAktuell.toFixed(1)} %` : '–'}
                        </p>
                      </div>
                    </div>
                    {istUeberSoll && gesamtIstH > 0 && (
                      <div className="bg-amber-50 border border-amber-100 rounded-lg p-3 flex items-start gap-2">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" className="text-amber-500 mt-0.5 flex-none"><path d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/></svg>
                        <p className="text-[11.5px] text-amber-700 leading-snug">Ist-Stunden {Math.round(((gesamtIstH / gesamtSollH) - 1) * 100)} % über Soll — Marge unter Ziel.</p>
                      </div>
                    )}
                  </>
                ) : (
                  <div className="text-center py-4">
                    <p className="text-[12.5px] text-slate-500 mb-3">Kein Auftragswert definiert</p>
                    <button onClick={() => setEditEckdaten(true)}
                      className="h-8 px-3 bg-white border border-slate-200 rounded-lg text-[12px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors">
                      Auftragswert eintragen
                    </button>
                  </div>
                )}
              </div>

              {/* Eckdaten */}
              <div className="bg-white border border-slate-200 rounded-xl shadow-xs p-5">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-[13px] font-semibold text-slate-900">Eckdaten</h2>
                  <button onClick={() => setEditEckdaten(true)}
                    className="text-[11.5px] text-slate-400 hover:text-slate-600 transition-colors">
                    ✎ Bearbeiten
                  </button>
                </div>
                {editEckdaten ? (
                  <div className="flex flex-col gap-2">
                    {[
                      ['kunde', 'Kunde'],
                      ['leitung', 'Projektleitung'],
                      ['laufzeit_start', 'Start (YYYY-MM)'],
                      ['laufzeit_end', 'Ende (YYYY-MM)'],
                      ['auftragswert', 'Auftragswert (€)'],
                      ['abrechnung_typ', 'Abrechnung'],
                    ].map(([k, lbl]) => (
                      <div key={k}>
                        <label className="block text-[10.5px] font-semibold uppercase tracking-wide text-slate-400 mb-0.5">{lbl}</label>
                        <input value={eckForm[k] || ''} onChange={e => setEckForm(f => ({ ...f, [k]: e.target.value }))}
                          className="w-full border border-slate-200 rounded-lg px-2.5 py-1.5 text-[12.5px] focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
                      </div>
                    ))}
                    <div className="flex gap-2 mt-1">
                      <button onClick={handleEckdatenSave} disabled={savingEck}
                        className="h-8 px-3 bg-accent hover:bg-accent-hover text-white rounded-lg text-[12px] font-semibold transition-colors disabled:opacity-50 flex-1">
                        {savingEck ? 'Speichern…' : 'Speichern'}
                      </button>
                      <button onClick={() => setEditEckdaten(false)}
                        className="h-8 px-3 bg-white border border-slate-200 rounded-lg text-[12px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors">
                        Abbrechen
                      </button>
                    </div>
                  </div>
                ) : (
                  <div>
                    <EckdatenRow label="Kunde" value={projekt?.kunde} />
                    <EckdatenRow label="Projektleitung" value={projekt?.leitung} />
                    <EckdatenRow label="Laufzeit"
                      value={projekt?.laufzeit_start
                        ? `${projekt.laufzeit_start}${projekt.laufzeit_end ? ` – ${projekt.laufzeit_end}` : ''}`
                        : null} />
                    <EckdatenRow label="Auftragswert" value={projekt?.auftragswert ? fmtEUR(projekt.auftragswert) : null} />
                    <EckdatenRow label="Abrechnung" value={projekt?.abrechnung_typ} />
                    <EckdatenRow label="Positionen" value={`${aktivPositionen.length}`} />
                  </div>
                )}
              </div>

              {/* Nachkalkulation link */}
              <Link to={`/projekte/${projekt_id}/nachkalkulation`}
                className="bg-white border border-slate-200 rounded-xl shadow-xs p-4 flex items-center gap-3 hover:bg-slate-50 transition-colors group">
                <div className="w-8 h-8 bg-slate-100 rounded-lg flex items-center justify-center flex-none group-hover:bg-slate-200 transition-colors">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" className="text-slate-600"><path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2M9 5a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2M9 5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/></svg>
                </div>
                <div>
                  <p className="text-[13px] font-semibold text-slate-900">Nachkalkulation</p>
                  <p className="text-[11.5px] text-slate-400">Soll / Ist im Detail</p>
                </div>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" className="ml-auto text-slate-300 group-hover:text-slate-500 transition-colors flex-none"><path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
              </Link>
            </div>
          </div>
        )}

        {/* ── Kalkulation ── */}
        {tab === 'kalkulation' && (
          <div className="max-w-[900px]">
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="text-[16px] font-semibold text-slate-900">Kalkulation</h2>
                <p className="text-[13px] text-slate-500 mt-0.5">{aktivPositionen.length} Positionen · {fmtEUR(gesamtSoll)} Gesamt</p>
              </div>
              <button onClick={handlePdf} disabled={pdfLoading || aktivPositionen.length === 0}
                className="h-9 px-4 bg-accent hover:bg-accent-hover text-white rounded-lg text-[13px] font-semibold transition-colors shadow-accent disabled:opacity-40 inline-flex items-center gap-1.5">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
                {pdfLoading ? 'PDF erstellen…' : 'PDF'}
              </button>
            </div>

            <PositionForm
              beschreibung={beschreibung} setBeschreibung={setBeschreibung}
              stunden={stunden} setStunden={setStunden}
              rolleId={rolleId} handleRolleChange={handleRolleChange}
              satz={satz} setSatz={setSatz}
              phase={phase} setPhase={setPhase}
              rollen={rollen} saving={saving} sucheLoading={sucheLoading}
              onSubmit={handleAddPosition} onSuche={handleSuche}
              suchErgebnis={suchErgebnis}
            />

            <PositionenTabelle
              positionen={aktivPositionen} gesamtSoll={gesamtSoll}
              editIstId={editIstId} istValue={istValue} setIstValue={setIstValue}
              setEditIstId={setEditIstId} handleIstSave={handleIstSave}
              onDelete={async id => { await deletePosition(id); load() }}
            />
          </div>
        )}

        {/* ── Zeiterfassung ── */}
        {tab === 'zeiterfassung' && (
          <div className="max-w-[900px]">
            <h2 className="text-[16px] font-semibold text-slate-900 mb-5">Zeiterfassung</h2>
            {aktivPositionen.length === 0 ? (
              <div className="bg-white border border-slate-200 rounded-xl p-12 text-center shadow-xs">
                <p className="text-[14px] font-semibold text-slate-900 mb-1">Keine Positionen</p>
                <p className="text-[13px] text-slate-500">Trage erst Positionen in der Kalkulation ein.</p>
              </div>
            ) : (
              <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
                <div className="grid items-center px-5 py-2.5 bg-slate-50 border-b border-slate-200"
                  style={{ gridTemplateColumns: '1fr 130px 130px 100px' }}>
                  {['Position', 'Soll-Stunden', 'Ist-Stunden', ''].map(h => (
                    <span key={h} className="text-[10.5px] font-semibold uppercase tracking-[0.04em] text-slate-400 last:text-right">{h}</span>
                  ))}
                </div>
                {aktivPositionen.map(pos => {
                  const over = pos.ist_stunden != null && pos.ist_stunden > pos.soll_stunden
                  return (
                    <div key={pos.id} className="grid items-center px-5 py-3 border-t border-slate-100"
                      style={{ gridTemplateColumns: '1fr 130px 130px 100px' }}>
                      <div className="min-w-0 pr-4">
                        <p className="text-[13px] font-medium text-slate-900 truncate">{pos.beschreibung_text}</p>
                        <p className="text-[11.5px] text-slate-400 mt-0.5">{pos.rolle_name || '–'}{pos.phase ? ` · ${pos.phase}` : ''}</p>
                      </div>
                      <div>
                        <span className="text-[13px] text-slate-600 tabular-nums">{pos.soll_stunden} h</span>
                      </div>
                      <div>
                        {editIstId === pos.id ? (
                          <div className="flex items-center gap-1.5">
                            <input type="number" value={istValue} onChange={e => setIstValue(e.target.value)}
                              className="w-20 border border-slate-200 rounded px-2 py-1 text-[12px] text-right focus:outline-none focus:ring-1 focus:ring-accent/30" autoFocus />
                            <button onClick={() => handleIstSave(pos.id)} className="text-[11.5px] text-emerald-600 font-semibold">OK</button>
                            <button onClick={() => setEditIstId(null)} className="text-[11.5px] text-slate-400">✕</button>
                          </div>
                        ) : (
                          <button onClick={() => { setEditIstId(pos.id); setIstValue(pos.ist_stunden ?? '') }}
                            className={`text-[13px] tabular-nums font-medium ${over ? 'text-amber-600' : 'text-emerald-700'} hover:underline`}>
                            {pos.ist_stunden != null ? `${pos.ist_stunden} h` : '+ eintragen'}
                          </button>
                        )}
                      </div>
                      <div className="text-right">
                        {pos.ist_stunden != null && (
                          <span className={`text-[11.5px] font-semibold px-2 py-0.5 rounded-full ${over ? 'bg-amber-50 text-amber-600' : 'bg-emerald-50 text-emerald-700'}`}>
                            {over ? '+' : ''}{Math.round(pos.ist_stunden - pos.soll_stunden)} h
                          </span>
                        )}
                      </div>
                    </div>
                  )
                })}
                <div className="grid items-center px-5 py-3 border-t-2 border-slate-200 bg-slate-50"
                  style={{ gridTemplateColumns: '1fr 130px 130px 100px' }}>
                  <span className="text-[13px] font-semibold text-slate-700">Gesamt</span>
                  <span className="text-[13px] font-semibold text-slate-900 tabular-nums">{Math.round(gesamtSollH)} h</span>
                  <span className={`text-[13px] font-semibold tabular-nums ${istUeberSoll ? 'text-amber-600' : 'text-slate-900'}`}>{Math.round(gesamtIstH)} h</span>
                  <span className={`text-right text-[12px] font-semibold tabular-nums ${istUeberSoll ? 'text-amber-600' : 'text-emerald-600'}`}>
                    {gesamtSollH > 0 ? `${istUeberSoll ? '+' : ''}${Math.round(gesamtIstH - gesamtSollH)} h` : ''}
                  </span>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Dokumente ── */}
        {tab === 'dokumente' && (
          <div className="max-w-[900px]">
            <h2 className="text-[16px] font-semibold text-slate-900 mb-5">Dokumente</h2>
            <div className="bg-white border border-slate-200 rounded-xl p-16 text-center shadow-xs">
              <svg width="36" height="36" viewBox="0 0 24 24" fill="none" className="text-slate-300 mx-auto mb-3"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/><path d="M14 2v6h6" stroke="currentColor" strokeWidth="1.5"/></svg>
              <p className="text-[14px] font-semibold text-slate-900 mb-1">Keine Dokumente</p>
              <p className="text-[13px] text-slate-500">Dokumentenverwaltung folgt in einer späteren Version.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Shared sub-components ────────────────────────────────────────────────────

function LegendDot({ color, label }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="w-3 h-1.5 rounded-full flex-none" style={{ background: color }} />
      <span className="text-[11.5px] text-slate-500">{label}</span>
    </div>
  )
}

function PositionForm({ beschreibung, setBeschreibung, stunden, setStunden, rolleId, handleRolleChange,
  satz, setSatz, phase, setPhase, rollen, saving, sucheLoading, onSubmit, onSuche, suchErgebnis }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs mb-5">
      <h2 className="text-[13.5px] font-semibold text-slate-900 mb-4">Position hinzufügen</h2>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <div>
          <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Beschreibung *</label>
          <textarea value={beschreibung} onChange={e => { setBeschreibung(e.target.value); }} rows={2}
            placeholder="Was wird in dieser Position geleistet?"
            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent resize-none" />
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Soll-Stunden *</label>
            <input type="number" min="0.5" step="0.5" value={stunden} onChange={e => setStunden(e.target.value)} placeholder="8"
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
          </div>
          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Rolle</label>
            <select value={rolleId} onChange={handleRolleChange}
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent bg-white">
              <option value="">– keine –</option>
              {rollen.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Stundensatz €/h</label>
            <input type="number" min="1" step="1" value={satz} onChange={e => setSatz(e.target.value)} placeholder="120"
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
          </div>
          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Phase</label>
            <input value={phase} onChange={e => setPhase(e.target.value)} placeholder="z. B. Analyse"
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
          </div>
          <div className="flex flex-col justify-end gap-2">
            <button type="button" onClick={onSuche} disabled={sucheLoading || !beschreibung.trim()}
              className="h-9 px-3 bg-white border border-slate-200 rounded-lg text-[12.5px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors disabled:opacity-40">
              {sucheLoading ? 'Suche…' : 'Ähnliche'}
            </button>
            <button type="submit" disabled={saving || !beschreibung.trim() || !stunden}
              className="h-9 px-3 bg-accent hover:bg-accent-hover text-white rounded-lg text-[12.5px] font-semibold transition-colors disabled:opacity-40">
              {saving ? 'Hinzufügen…' : '+ Hinzufügen'}
            </button>
          </div>
        </div>
      </form>

      {suchErgebnis && (
        <div className="mt-5 pt-4 border-t border-slate-100">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <p className="text-[13px] font-semibold text-slate-900">Ähnliche historische Positionen</p>
              <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${
                suchErgebnis.konfidenz === 'hoch' ? 'bg-emerald-50 text-emerald-700' :
                suchErgebnis.konfidenz === 'mittel' ? 'bg-amber-50 text-amber-700' : 'bg-slate-100 text-slate-500'
              }`}>Konfidenz: {suchErgebnis.konfidenz}</span>
            </div>
            <p className="text-[12px] text-slate-400">Vorschlag: <strong className="text-slate-700">{suchErgebnis.schaetzvorschlag} h</strong> ({suchErgebnis.n_verglichen} verglichen)</p>
          </div>
          {suchErgebnis.treffer.length === 0 ? (
            <p className="text-[13px] text-slate-400">Keine ähnlichen Positionen gefunden.</p>
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
  )
}

function PositionenTabelle({ positionen, gesamtSoll, editIstId, istValue, setIstValue, setEditIstId, handleIstSave, onDelete }) {
  return (
    <div>
      <h2 className="text-[14px] font-semibold text-slate-900 mb-3">
        Positionen <span className="text-slate-400 font-normal">({positionen.length})</span>
      </h2>
      {positionen.length === 0 ? (
        <div className="bg-white border border-slate-200 rounded-xl p-12 text-center shadow-xs">
          <p className="text-[14px] font-semibold text-slate-900 mb-1">Noch keine Positionen</p>
          <p className="text-[13px] text-slate-500">Füge oben eine Position hinzu.</p>
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
          <div className="grid items-center px-5 py-2.5 bg-slate-50 border-b border-slate-200"
            style={{ gridTemplateColumns: '1fr 80px 100px 110px 100px 90px' }}>
            {['Beschreibung', 'Phase', 'Stunden', 'Stundensatz', 'Summe', ''].map(h => (
              <span key={h} className="text-[10.5px] font-semibold uppercase tracking-[0.04em] text-slate-400 text-right first:text-left">{h}</span>
            ))}
          </div>

          {positionen.map((pos) => {
            const summe = pos.soll_stunden * (pos.stundensatz_snapshot || 0)
            return (
              <div key={pos.id} className="grid items-center px-5 py-3.5 border-t border-slate-100 group"
                style={{ gridTemplateColumns: '1fr 80px 100px 110px 100px 90px' }}>
                <div className="min-w-0 pr-4">
                  <p className="text-[13px] font-medium text-slate-900 truncate">{pos.beschreibung_text}</p>
                  <p className="text-[11.5px] text-slate-400 mt-0.5">{pos.rolle_name || '–'}</p>
                </div>
                <div className="text-right">
                  <span className="text-[11.5px] text-slate-400 truncate">{pos.phase || '–'}</span>
                </div>
                <div className="text-right">
                  {editIstId === pos.id ? (
                    <div className="flex items-center gap-1 justify-end">
                      <input type="number" value={istValue} onChange={e => setIstValue(e.target.value)}
                        className="w-16 border border-slate-200 rounded px-2 py-1 text-[12px] text-right focus:outline-none focus:ring-1 focus:ring-accent/30" autoFocus />
                      <button onClick={() => handleIstSave(pos.id)} className="text-[11.5px] text-emerald-600 font-semibold">OK</button>
                      <button onClick={() => setEditIstId(null)} className="text-[11.5px] text-slate-400">✕</button>
                    </div>
                  ) : (
                    <div>
                      <p className="text-[13px] font-medium text-slate-900 tabular-nums">{pos.soll_stunden} h</p>
                      {pos.ist_stunden != null && <p className="text-[11px] text-emerald-600 tabular-nums">{pos.ist_stunden} h Ist</p>}
                    </div>
                  )}
                </div>
                <div className="text-right">
                  <p className="text-[13px] text-slate-600 tabular-nums">{pos.stundensatz_snapshot ? `${pos.stundensatz_snapshot} €/h` : '–'}</p>
                </div>
                <div className="text-right">
                  {summe > 0 && <p className="text-[13px] font-semibold text-slate-900 tabular-nums">{new Intl.NumberFormat('de-DE',{style:'currency',currency:'EUR',maximumFractionDigits:0}).format(summe)}</p>}
                </div>
                <div className="flex items-center justify-end gap-1">
                  {editIstId !== pos.id && (
                    <button onClick={() => { setEditIstId(pos.id); setIstValue(pos.ist_stunden ?? '') }}
                      className="opacity-0 group-hover:opacity-100 text-[11px] text-slate-500 hover:text-accent px-1.5 py-1 transition-opacity">
                      {pos.ist_stunden != null ? 'Ist ✎' : '+ Ist'}
                    </button>
                  )}
                  <button onClick={() => onDelete(pos.id)}
                    className="opacity-0 group-hover:opacity-100 text-[11px] text-red-400 hover:text-red-600 px-1 py-1 transition-opacity">✕</button>
                </div>
              </div>
            )
          })}

          <div className="grid items-center px-5 py-3.5 border-t-2 border-slate-200 bg-slate-50"
            style={{ gridTemplateColumns: '1fr 80px 100px 110px 100px 90px' }}>
            <span className="text-[13px] font-semibold text-slate-700">Gesamt (netto)</span>
            <div /><div /><div />
            <div className="text-right"><p className="text-[15px] font-bold text-slate-900 tabular-nums">{new Intl.NumberFormat('de-DE',{style:'currency',currency:'EUR',maximumFractionDigits:0}).format(gesamtSoll)}</p></div>
            <div />
          </div>
        </div>
      )}
    </div>
  )
}
