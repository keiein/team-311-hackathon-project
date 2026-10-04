/**
 * Dynamic legend for Today's Jobs — one row per active crew in the CURRENT plan.
 */
function CrewLegend({ crews, highlightCrew = 'all' }) {
  if (!crews?.length) return null

  const rows =
    highlightCrew === 'all' ? crews : crews.filter((row) => row.crew === highlightCrew)

  if (!rows.length) return null

  return (
    <div className="pointer-events-auto max-h-56 w-44 overflow-auto rounded-md border border-border bg-white p-3 shadow-sm">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text">Today&apos;s Crews</h3>
      <ul className="space-y-1">
        {rows.map((row) => (
          <li key={row.crew} className="flex items-center gap-2 text-xs text-text">
            <span
              aria-hidden="true"
              className="inline-block h-2.5 w-2.5 shrink-0 rounded-full border border-white shadow-sm"
              style={{ backgroundColor: row.color }}
            />
            <span className="min-w-0 flex-1 truncate font-medium">{row.crew}</span>
            <span className="tabular-nums text-text-muted">{row.jobs} job{row.jobs === 1 ? '' : 's'}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export default CrewLegend
