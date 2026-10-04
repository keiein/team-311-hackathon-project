import { useMemo, useState } from 'react'

const PAGE_SIZE = 50

// Same colours as the map's priority ramp (CalgaryMap.jsx). The word is always shown too.
const BAND_STYLE = {
  High: { background: '#c8102e', color: '#ffffff' },
  Medium: { background: '#f59e0b', color: '#1a1a1a' },
  Low: { background: '#9ca3af', color: '#1a1a1a' },
}
const PRIORITY_OPTIONS = ['High', 'Medium', 'Low']

// Same look as the search box and dropdowns on the Dashboard map
const INPUT_CLASS =
  'rounded-md border border-border bg-white px-3 py-1.5 text-sm text-text shadow-sm placeholder:text-neutral-400 focus:border-calgary-red focus:outline-none focus:ring-1 focus:ring-calgary-red'
const SELECT_CLASS =
  'rounded-md border border-border bg-white px-2.5 py-1.5 text-sm text-text shadow-sm focus:border-calgary-red focus:outline-none focus:ring-1 focus:ring-calgary-red'
const BUTTON_CLASS =
  'rounded-md border border-border bg-white px-3 py-1.5 text-sm text-text shadow-sm hover:bg-panel disabled:cursor-not-allowed disabled:text-neutral-400 disabled:hover:bg-white'

const COLUMNS = [
  { key: 'id', label: 'Ticket no.', numeric: false },
  { key: 'serviceType', label: 'Type of problem', numeric: false },
  { key: 'community', label: 'Community', numeric: false },
  { key: 'priorityScore', label: 'Priority', numeric: true },
  { key: 'daysWaiting', label: 'Days waiting', numeric: true },
  { key: 'crew', label: 'Crew', numeric: false },
  { key: 'status', label: 'Status', numeric: false },
]

const show = (value) => (value === undefined || value === null || value === '' ? '-' : value)

function compare(a, b, key) {
  const x = a[key]
  const y = b[key]
  if (typeof x === 'number' && typeof y === 'number') return x - y
  return String(x ?? '').localeCompare(String(y ?? ''), undefined, { numeric: true })
}

function RequestsTable({ rows }) {
  const [search, setSearch] = useState('')
  const [priority, setPriority] = useState('all')
  const [crew, setCrew] = useState('all')
  // Default order: highest priority first, then the one waiting longest
  const [sort, setSort] = useState({ key: 'priorityScore', direction: 'desc' })
  const [page, setPage] = useState(0)

  const crewOptions = useMemo(() => [...new Set(rows.map((row) => row.crew))].filter(Boolean).sort(), [rows])

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase()
    const matches = rows.filter((row) => {
      if (priority !== 'all' && row.priorityBand !== priority) return false
      if (crew !== 'all' && row.crew !== crew) return false
      if (!needle) return true
      return [row.id, row.serviceType, row.community].some((value) => String(value ?? '').toLowerCase().includes(needle))
    })

    const direction = sort.direction === 'asc' ? 1 : -1
    return matches.sort((a, b) => {
      const primary = compare(a, b, sort.key) * direction
      if (primary !== 0) return primary
      // Ties: higher priority first, then longer wait first
      return compare(b, a, 'priorityScore') || compare(b, a, 'daysWaiting')
    })
  }, [rows, search, priority, crew, sort])

  // Changing search, filters or sort always goes back to page 1 (done in the handlers, not an effect)
  const changeSearch = (value) => { setSearch(value); setPage(0) }
  const changePriority = (value) => { setPriority(value); setPage(0) }
  const changeCrew = (value) => { setCrew(value); setPage(0) }
  const clearFilters = () => { setSearch(''); setPriority('all'); setCrew('all'); setPage(0) }
  const changeSort = (key) => {
    setSort((current) => ({
      key,
      direction: current.key === key && current.direction === 'desc' ? 'asc' : 'desc',
    }))
    setPage(0)
  }

  const pageCount = Math.max(1, Math.ceil(visible.length / PAGE_SIZE))
  const currentPage = Math.min(page, pageCount - 1)
  const first = currentPage * PAGE_SIZE
  const pageRows = visible.slice(first, first + PAGE_SIZE)

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Search, filters and the honest note about locations */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border bg-white px-5 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="search"
            value={search}
            onChange={(event) => changeSearch(event.target.value)}
            placeholder="Search ticket, type or community..."
            aria-label="Search requests"
            className={`w-64 ${INPUT_CLASS}`}
          />
          <select
            value={priority}
            onChange={(event) => changePriority(event.target.value)}
            aria-label="Filter by priority"
            className={SELECT_CLASS}
          >
            <option value="all">All Priorities</option>
            {PRIORITY_OPTIONS.map((band) => (
              <option key={band} value={band}>{band}</option>
            ))}
          </select>
          <select
            value={crew}
            onChange={(event) => changeCrew(event.target.value)}
            aria-label="Filter by crew"
            className={`${SELECT_CLASS} capitalize`}
          >
            <option value="all">All Crews</option>
            {crewOptions.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </div>
        <div className="text-right text-xs text-text-muted">
          <div className="text-sm font-medium text-text">
            {visible.length.toLocaleString()} of {rows.length.toLocaleString()} requests
          </div>
          <div>Locations are neighbourhood centres, not exact addresses.</div>
        </div>
      </div>

      {visible.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-5">
          <p className="text-sm text-text-muted">No requests match your filters</p>
          <button type="button" onClick={clearFilters} className={`${BUTTON_CLASS} text-calgary-red`}>
            Clear filters
          </button>
        </div>
      ) : (
        <>
          <div className="min-h-0 flex-1 overflow-auto">
            <table className="w-full border-collapse text-left text-sm">
              <thead className="sticky top-0 z-10 bg-panel">
                <tr>
                  {COLUMNS.map((column) => {
                    const active = sort.key === column.key
                    return (
                      <th
                        key={column.key}
                        scope="col"
                        aria-sort={active ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'}
                        className={`border-b border-border px-4 py-2 font-semibold text-text ${column.numeric ? 'text-right' : ''}`}
                      >
                        <button
                          type="button"
                          onClick={() => changeSort(column.key)}
                          className="inline-flex items-center gap-1 hover:text-calgary-red"
                        >
                          {column.label}
                          <span aria-hidden="true" className={active ? 'text-calgary-red' : 'text-transparent'}>
                            {active && sort.direction === 'asc' ? '↑' : '↓'}
                          </span>
                        </button>
                      </th>
                    )
                  })}
                </tr>
              </thead>
              <tbody>
                {pageRows.map((row) => (
                  <tr key={row.id} className="border-b border-border/60 hover:bg-panel">
                    <td className="px-4 py-2 whitespace-nowrap text-text">{show(row.id)}</td>
                    <td className="px-4 py-2 text-text">{show(row.serviceType)}</td>
                    <td className="px-4 py-2 text-text">
                      <div>{show(row.community)}</div>
                      <div className="text-xs text-text-muted">neighbourhood centre</div>
                    </td>
                    <td className="px-4 py-2 text-right whitespace-nowrap">
                      <div className="flex items-center justify-end gap-2">
                        <span className="tabular-nums text-text">{show(row.priorityScore)}</span>
                        <span
                          className="rounded px-2 py-0.5 text-xs font-semibold"
                          style={BAND_STYLE[row.priorityBand] ?? { background: '#e5e5e5', color: '#1a1a1a' }}
                        >
                          {show(row.priorityBand)}
                        </span>
                      </div>
                      <div className="text-xs text-text-muted">{show(row.severityName)}</div>
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums text-text">{show(row.daysWaiting)}</td>
                    <td className="px-4 py-2 text-text capitalize">{show(row.crew)}</td>
                    <td className="px-4 py-2 text-text">{show(row.status)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex shrink-0 items-center justify-between border-t border-border bg-white px-5 py-2">
            <span className="text-sm text-text-muted">
              Showing {(first + 1).toLocaleString()}-{Math.min(first + PAGE_SIZE, visible.length).toLocaleString()} of{' '}
              {visible.length.toLocaleString()}
            </span>
            <div className="flex items-center gap-2">
              <span className="text-sm text-text-muted">
                Page {currentPage + 1} of {pageCount.toLocaleString()}
              </span>
              <button type="button" className={BUTTON_CLASS} disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>
                Previous
              </button>
              <button
                type="button"
                className={BUTTON_CLASS}
                disabled={currentPage >= pageCount - 1}
                onClick={() => setPage(currentPage + 1)}
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

export default RequestsTable
