import { REQUEST_PRIORITY_LEGEND } from '../simulation/requestPriorityColors.js'

/** Compact legend for 311 request marker colors (map display only). */
function RequestPriorityLegend() {
  return (
    <div className="pointer-events-auto w-48 rounded-md border border-border bg-white p-3 shadow-sm">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text">Priority</h3>
      <ul className="space-y-1.5">
        {REQUEST_PRIORITY_LEGEND.map((row) => (
          <li key={row.id} className="flex items-center gap-2 text-xs text-text">
            <span
              aria-hidden="true"
              className="inline-block h-2.5 w-2.5 shrink-0 rounded-full border border-black/10"
              style={{ backgroundColor: row.color }}
            />
            <span>{row.label}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export default RequestPriorityLegend
