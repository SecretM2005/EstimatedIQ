import { useEffect, useMemo, useState } from 'react'
import { previewKpi } from '../api/angebot'

const SCHRITTE = ['Quelle', 'Berechnung', 'Filter', 'Darstellung']

const QUELLE_LABEL = { projekte: 'Projekte', leistungspositionen: 'Leistungspositionen' }
const FELD_LABEL = {
  auftragswert: 'Auftragswert', status: 'Status', kunde: 'Kunde',
  soll_stunden: 'Soll-Stunden', ist_stunden: 'Ist-Stunden',
  soll_kosten: 'Soll-Kosten', ist_kosten: 'Ist-Kosten', phase: 'Phase',
  projekt_status: 'Projekt-Status (übergeordnet)',
}
const AGG_LABEL = { count: 'Anzahl', sum: 'Summe', avg: 'Durchschnitt', min: 'Minimum', max: 'Maximum', median: 'Median' }
const OP_LABEL = { '=': 'ist gleich', '!=': 'ist ungleich', '<': 'kleiner als', '<=': 'kleiner/gleich', '>': 'größer als', '>=': 'größer/gleich', in: 'ist einer von' }
const FORMAT_LABEL = { eur: 'Euro (€)', stunden: 'Stunden', prozent: 'Prozent (%)', anzahl: 'Anzahl (ohne Einheit)' }
const ZEITRAUM_LABEL = { letzte_30_tage: 'Letzte 30 Tage', quartal: 'Aktuelles Quartal', jahr: 'Aktuelles Jahr', benutzerdefiniert: 'Benutzerdefiniert' }

function fehlerText(err) {
  return err?.response?.data?.detail || 'Aktion fehlgeschlagen.'
}

export default function KpiWizardModal({ katalog, permissionsListe, bestehend, onSave, onCancel }) {
  const istBearbeiten = !!bestehend

  const [schritt, setSchritt] = useState(0)
  const [quelle, setQuelle] = useState(bestehend?.quelle || '')
  const [feld, setFeld] = useState(bestehend?.feld || '')
  const [aggregation, setAggregation] = useState(bestehend?.aggregation || '')
  const [filters, setFilters] = useState(bestehend?.filters || [])
  const [zeitraumTyp, setZeitraumTyp] = useState(bestehend?.zeitraum?.typ || '')
  const [zeitraumVon, setZeitraumVon] = useState(bestehend?.zeitraum?.von || '')
  const [zeitraumBis, setZeitraumBis] = useState(bestehend?.zeitraum?.bis || '')
  const [key, setKey] = useState(bestehend?.key || '')
  const [label, setLabel] = useState(bestehend?.label || '')
  const [beschreibung, setBeschreibung] = useState(bestehend?.beschreibung || '')
  const [format, setFormat] = useState(bestehend?.format || '')
  const [requiredPermission, setRequiredPermission] = useState(bestehend?.required_permission || '')

  const [vorschau, setVorschau] = useState(null)
  const [vorschauFehler, setVorschauFehler] = useState(null)
  const [ladeVorschau, setLadeVorschau] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const felderDerQuelle = quelle ? katalog.quellen[quelle] || [] : []
  const feldTypMap = useMemo(() => {
    const map = {}
    Object.values(katalog.quellen).flat().forEach(f => { map[f.feld] = f.typ })
    return map
  }, [katalog])
  const filterfelderDerQuelle = quelle ? (katalog.filterfelder[quelle] || []) : []
  const aggregationenErlaubt = feld && feldTypMap[feld] !== 'numerisch'
    ? ['count']
    : katalog.aggregationen

  const definitionKomplett = quelle && feld && aggregation

  const filterBody = () => filters
    .filter(f => f.feld && f.operator && f.wert !== '')
    .map(f => ({
      feld: f.feld, operator: f.operator,
      wert: f.operator === 'in' ? f.wert.split(',').map(s => s.trim()).filter(Boolean) : f.wert,
    }))

  const zeitraumBody = () => zeitraumTyp
    ? { typ: zeitraumTyp, ...(zeitraumTyp === 'benutzerdefiniert' ? { von: zeitraumVon, bis: zeitraumBis } : {}) }
    : null

  const definitionBody = () => ({
    quelle, feld, aggregation, filters: filterBody(), zeitraum: zeitraumBody(),
  })

  // Live-Vorschau, sobald Quelle/Feld/Aggregation vollständig sind (Schritt 3+).
  useEffect(() => {
    if (schritt < 2 || !definitionKomplett) { setVorschau(null); return }
    setLadeVorschau(true); setVorschauFehler(null)
    const timer = setTimeout(() => {
      previewKpi(definitionBody())
        .then(r => setVorschau(r.wert))
        .catch(err => setVorschauFehler(fehlerText(err)))
        .finally(() => setLadeVorschau(false))
    }, 300)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schritt, quelle, feld, aggregation, JSON.stringify(filters), zeitraumTyp, zeitraumVon, zeitraumBis])

  const weiterMoeglich = () => {
    if (schritt === 0) return !!quelle
    if (schritt === 1) return !!feld && !!aggregation
    if (schritt === 2) return true
    return !!key.trim() && !!label.trim()
  }

  const handleSave = async () => {
    setSaving(true); setError(null)
    try {
      await onSave({
        key: key.trim(), label: label.trim(), beschreibung: beschreibung.trim() || null,
        ...definitionBody(),
        darstellungstyp: 'zahl',
        format: format || null,
        required_permission: requiredPermission || null,
      })
    } catch (err) {
      setError(fehlerText(err))
      setSaving(false)
    }
  }

  const updateFilter = (i, patch) => setFilters(prev => prev.map((f, idx) => idx === i ? { ...f, ...patch } : f))
  const addFilter = () => setFilters(prev => [...prev, { feld: filterfelderDerQuelle[0] || '', operator: '=', wert: '' }])
  const removeFilter = (i) => setFilters(prev => prev.filter((_, idx) => idx !== i))

  return (
    <div className="fixed inset-0 bg-slate-900/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl border border-slate-200 w-full max-w-lg max-h-[88vh] overflow-y-auto p-6">
        <h3 className="text-[15px] font-semibold text-slate-900 mb-1">
          {istBearbeiten ? `Kennzahl "${bestehend.label}" bearbeiten` : 'Neue Kennzahl erstellen'}
        </h3>
        <p className="text-[12.5px] text-slate-500 mb-4">
          Keine freie SQL-Eingabe – nur Quelle, Feld und Filter aus der freigegebenen Liste.
        </p>

        {/* Step-Indikator */}
        <div className="flex items-center gap-1.5 mb-5">
          {SCHRITTE.map((s, i) => (
            <div key={s} className="flex-1 flex items-center gap-1.5">
              <div className={`h-1.5 flex-1 rounded-full ${i <= schritt ? 'bg-accent' : 'bg-slate-100'}`} />
            </div>
          ))}
        </div>
        <p className="text-[10.5px] font-semibold uppercase tracking-[0.06em] text-slate-400 mb-4">
          Schritt {schritt + 1} von 4 · {SCHRITTE[schritt]}
        </p>

        {/* Schritt 1: Quelle */}
        {schritt === 0 && (
          <div className="flex flex-col gap-2">
            {Object.keys(katalog.quellen).map(q => (
              <button
                key={q}
                onClick={() => { setQuelle(q); setFeld(''); setAggregation(''); setFilters([]) }}
                className={`text-left px-4 py-3 rounded-lg border text-[13px] font-medium transition-colors ${
                  quelle === q ? 'border-accent bg-indigo-50 text-accent' : 'border-slate-200 text-slate-700 hover:bg-slate-50'
                }`}
              >
                {QUELLE_LABEL[q] || q}
              </button>
            ))}
          </div>
        )}

        {/* Schritt 2: Berechnung */}
        {schritt === 1 && (
          <div className="flex flex-col gap-4">
            <div>
              <label className="block text-[11.5px] font-semibold text-slate-600 mb-1.5">Feld</label>
              <select value={feld} onChange={e => { setFeld(e.target.value); setAggregation('') }}
                className="w-full h-9 px-2.5 border border-slate-200 rounded-lg text-[13px] bg-white">
                <option value="">– auswählen –</option>
                {felderDerQuelle.map(f => (
                  <option key={f.feld} value={f.feld}>
                    {FELD_LABEL[f.feld] || f.feld}{f.sensibel ? ' (intern)' : ''}
                  </option>
                ))}
              </select>
              {felderDerQuelle.find(f => f.feld === feld)?.sensibel && (
                <p className="text-[11.5px] text-amber-600 mt-1.5">
                  Internes Feld – setze in Schritt 4 eine Sichtbarkeits-Berechtigung, sonst sehen alle den Wert.
                </p>
              )}
            </div>
            {feld && (
              <div>
                <label className="block text-[11.5px] font-semibold text-slate-600 mb-1.5">Aggregation</label>
                <select value={aggregation} onChange={e => setAggregation(e.target.value)}
                  className="w-full h-9 px-2.5 border border-slate-200 rounded-lg text-[13px] bg-white">
                  <option value="">– auswählen –</option>
                  {aggregationenErlaubt.map(a => <option key={a} value={a}>{AGG_LABEL[a] || a}</option>)}
                </select>
              </div>
            )}
          </div>
        )}

        {/* Schritt 3: Filter + Zeitraum */}
        {schritt === 2 && (
          <div className="flex flex-col gap-5">
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-[11.5px] font-semibold text-slate-600">Filter (optional)</label>
                <button onClick={addFilter} className="text-[12px] text-accent hover:text-accent-hover font-medium">+ Filter hinzufügen</button>
              </div>
              {filters.length === 0 && <p className="text-[12.5px] text-slate-400">Keine Filter – Kennzahl bezieht sich auf alle {QUELLE_LABEL[quelle]}.</p>}
              <div className="flex flex-col gap-2">
                {filters.map((f, i) => {
                  const typ = feldTypMap[f.feld] || 'text'
                  return (
                    <div key={i} className="flex gap-1.5 items-center">
                      <select value={f.feld} onChange={e => updateFilter(i, { feld: e.target.value })}
                        className="flex-1 h-8 px-2 border border-slate-200 rounded-md text-[12px] bg-white">
                        {filterfelderDerQuelle.map(ff => <option key={ff} value={ff}>{FELD_LABEL[ff] || ff}</option>)}
                      </select>
                      <select value={f.operator} onChange={e => updateFilter(i, { operator: e.target.value })}
                        className="w-32 h-8 px-2 border border-slate-200 rounded-md text-[12px] bg-white">
                        {(katalog.operatoren_je_typ[typ] || []).map(op => <option key={op} value={op}>{OP_LABEL[op] || op}</option>)}
                      </select>
                      <input value={f.wert} onChange={e => updateFilter(i, { wert: e.target.value })}
                        placeholder={f.operator === 'in' ? 'a, b, c' : 'Wert'}
                        className="flex-1 h-8 px-2 border border-slate-200 rounded-md text-[12px]" />
                      <button onClick={() => removeFilter(i)} className="w-8 h-8 flex-none text-slate-400 hover:text-red-600 flex items-center justify-center">✕</button>
                    </div>
                  )
                })}
              </div>
            </div>
            <div>
              <label className="block text-[11.5px] font-semibold text-slate-600 mb-1.5">Zeitraum (optional)</label>
              <select value={zeitraumTyp} onChange={e => setZeitraumTyp(e.target.value)}
                className="w-full h-9 px-2.5 border border-slate-200 rounded-lg text-[13px] bg-white">
                <option value="">Kein Zeitraumfilter</option>
                {katalog.zeitraum_typen.map(z => <option key={z} value={z}>{ZEITRAUM_LABEL[z] || z}</option>)}
              </select>
              {zeitraumTyp === 'benutzerdefiniert' && (
                <div className="flex gap-2 mt-2">
                  <input type="date" value={zeitraumVon} onChange={e => setZeitraumVon(e.target.value)}
                    className="flex-1 h-9 px-2.5 border border-slate-200 rounded-lg text-[13px]" />
                  <input type="date" value={zeitraumBis} onChange={e => setZeitraumBis(e.target.value)}
                    className="flex-1 h-9 px-2.5 border border-slate-200 rounded-lg text-[13px]" />
                </div>
              )}
            </div>
          </div>
        )}

        {/* Schritt 4: Darstellung & Sichtbarkeit */}
        {schritt === 3 && (
          <div className="flex flex-col gap-4">
            <div className="bg-slate-50 border border-slate-200 rounded-lg px-4 py-3">
              <p className="text-[10.5px] font-semibold uppercase tracking-[0.06em] text-slate-400 mb-1">Live-Vorschau</p>
              {ladeVorschau ? (
                <p className="text-[13px] text-slate-400">Berechne…</p>
              ) : vorschauFehler ? (
                <p className="text-[13px] text-red-600">{vorschauFehler}</p>
              ) : (
                <p className="text-[22px] font-bold text-slate-900 tabular-nums">{vorschau ?? '–'}</p>
              )}
            </div>
            <div>
              <label className="block text-[11.5px] font-semibold text-slate-600 mb-1.5">Interner Key</label>
              <input value={key} onChange={e => setKey(e.target.value)} disabled={istBearbeiten}
                placeholder="z. B. offene_grossprojekte"
                className="w-full h-9 px-2.5 border border-slate-200 rounded-lg text-[13px] disabled:bg-slate-50 disabled:text-slate-400" />
            </div>
            <div>
              <label className="block text-[11.5px] font-semibold text-slate-600 mb-1.5">Anzeigename</label>
              <input value={label} onChange={e => setLabel(e.target.value)}
                className="w-full h-9 px-2.5 border border-slate-200 rounded-lg text-[13px]" />
            </div>
            <div>
              <label className="block text-[11.5px] font-semibold text-slate-600 mb-1.5">Beschreibung (optional)</label>
              <input value={beschreibung} onChange={e => setBeschreibung(e.target.value)}
                className="w-full h-9 px-2.5 border border-slate-200 rounded-lg text-[13px]" />
            </div>
            <div>
              <label className="block text-[11.5px] font-semibold text-slate-600 mb-1.5">Format</label>
              <select value={format} onChange={e => setFormat(e.target.value)}
                className="w-full h-9 px-2.5 border border-slate-200 rounded-lg text-[13px] bg-white">
                <option value="">Ohne Einheit</option>
                {Object.entries(FORMAT_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-[11.5px] font-semibold text-slate-600 mb-1.5">Sichtbar nur mit Berechtigung</label>
              <select value={requiredPermission} onChange={e => setRequiredPermission(e.target.value)}
                className="w-full h-9 px-2.5 border border-slate-200 rounded-lg text-[13px] bg-white">
                <option value="">Für alle sichtbar, die das Dashboard sehen</option>
                {permissionsListe.map(p => <option key={p.key} value={p.key}>{p.beschreibung}</option>)}
              </select>
              <p className="text-[11.5px] text-slate-400 mt-1.5">
                Ohne diese Berechtigung fehlt der Wert serverseitig komplett aus der Antwort – nicht nur im Frontend ausgeblendet.
              </p>
            </div>
          </div>
        )}

        {error && <p className="text-[12.5px] text-red-600 mt-4">{error}</p>}

        <div className="flex items-center justify-between mt-6 pt-4 border-t border-slate-100">
          <button onClick={onCancel} className="h-9 px-4 text-[13px] font-medium text-slate-500 hover:text-slate-800">
            Abbrechen
          </button>
          <div className="flex gap-2">
            {schritt > 0 && (
              <button onClick={() => setSchritt(s => s - 1)}
                className="h-9 px-4 border border-slate-200 rounded-lg text-[13px] font-medium text-slate-700 hover:bg-slate-50">
                Zurück
              </button>
            )}
            {schritt < 3 ? (
              <button onClick={() => setSchritt(s => s + 1)} disabled={!weiterMoeglich()}
                className="h-9 px-4 bg-accent hover:bg-accent-hover disabled:opacity-40 text-white rounded-lg text-[13px] font-semibold">
                Weiter
              </button>
            ) : (
              <button onClick={handleSave} disabled={!weiterMoeglich() || saving}
                className="h-9 px-4 bg-accent hover:bg-accent-hover disabled:opacity-40 text-white rounded-lg text-[13px] font-semibold">
                {saving ? 'Speichert…' : 'Speichern'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
