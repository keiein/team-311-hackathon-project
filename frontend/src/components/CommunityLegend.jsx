import { useState } from 'react'

/**
 * Compact/collapsible legend of communities that have Today's Jobs.
 */
function CommunityLegend({ communities }) {
  const [open, setOpen] = useState(true)

  if (!communities?.length) return null

  return (
    <div className="pointer-events-auto w-48 rounded-md border border-border bg-white shadow-sm">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2 text-left"
        aria-expanded={open}
      >
        <span className="text-xs font-semibold uppercase tracking-wide text-text">Communities</span>
        <span className="text-xs text-text-muted">
          {communities.length} with work {open ? '▴' : '▾'}
        </span>
      </button>
      {open && (
        <ul className="max-h-40 space-y-1 overflow-auto border-t border-border px-3 py-2">
          {communities.map((row) => (
            <li key={row.key} className="flex items-center gap-2 text-xs text-text">
              <span
                aria-hidden="true"
                className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm border border-black/10"
                style={{ backgroundColor: row.color }}
              />
              <span className="min-w-0 flex-1 truncate font-medium" title={row.name}>
                {row.name}
              </span>
              <span className="tabular-nums text-text-muted">{row.jobs}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default CommunityLegend
