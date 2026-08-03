const fmtEUR = n =>
  new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(n)

function formatWert(wert, format) {
  if (wert === null || wert === undefined) return '–'
  if (format === 'eur') return fmtEUR(wert)
  if (format === 'stunden') return `${new Intl.NumberFormat('de-DE', { maximumFractionDigits: 0 }).format(wert)} Std`
  if (format === 'prozent') return `${wert} %`
  return new Intl.NumberFormat('de-DE', { maximumFractionDigits: 1 }).format(wert)
}

/** Rendert ein einzelnes Dashboard-Widget generisch nach darstellungstyp – System- und
 * Custom-Kennzahlen sehen aus dem Frontend identisch aus. */
export default function DashboardWidget({ widget, editMode, onRemove }) {
  return (
    <div className="h-full bg-white border border-slate-200 rounded-xl shadow-xs px-5 py-4 overflow-hidden relative">
      {editMode && (
        <button
          onClick={onRemove}
          title="Widget entfernen"
          className="absolute top-2 right-2 w-6 h-6 rounded-md text-slate-400 hover:text-red-600 hover:bg-red-50 flex items-center justify-center transition-colors z-10"
        >
          ✕
        </button>
      )}
      <p className="text-[10.5px] font-semibold uppercase tracking-[0.06em] text-slate-400 mb-3 pr-6 truncate">
        {widget.label}
      </p>

      {widget.typ === 'tabelle' ? (
        <div className="overflow-y-auto" style={{ maxHeight: 'calc(100% - 28px)' }}>
          {(widget.zeilen || []).length === 0 ? (
            <p className="text-[13px] text-slate-400">Keine Daten</p>
          ) : (
            <table className="w-full text-[11.5px] table-fixed">
              <tbody>
                {widget.zeilen.map(z => (
                  <tr key={z.id} className="border-t border-slate-100 first:border-t-0">
                    <td className="py-1.5 pr-1.5 w-auto">
                      <p className="font-medium text-slate-800 truncate">{z.name}</p>
                      <p className="text-slate-400 text-[10.5px] truncate">{z.kunde}</p>
                    </td>
                    <td className="py-1.5 text-right tabular-nums text-slate-600 w-12">
                      {Math.round(z.ist_stunden)}/{Math.round(z.soll_stunden)}h
                    </td>
                    {z.marge_pct != null && (
                      <td className="py-1.5 pl-1.5 text-right tabular-nums font-semibold text-teal-700 w-10">
                        {z.marge_pct}%
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : (
        <div>
          <p className="text-[28px] font-bold text-slate-900 leading-none tabular-nums">
            {formatWert(widget.wert, widget.format)}
          </p>
          {(widget.n_gewonnen != null || widget.n_verloren != null) && (
            <p className="text-[12px] text-slate-400 mt-1.5">
              {widget.n_gewonnen ?? 0} gew. · {widget.n_verloren ?? 0} verl.
            </p>
          )}
        </div>
      )}
    </div>
  )
}
