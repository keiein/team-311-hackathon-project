import { Fragment, useMemo, useState } from 'react'

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
  { key: 'planStatus', label: 'Plan', numeric: false },
  { key: 'crew', label: 'Service area', numeric: false },
  { key: 'status', label: 'Status', numeric: false },
]
const PLAN_OPTIONS = ['Assigned', 'Waiting']

// The four parts of the team score. The weights come from the data file (meta.weights).
const PARTS = [
  { key: 'basicKnowledgeScore', label: 'Keywords', detail: (row) => row.severityWhy },
  { key: 'geoScore', label: 'Geography', detail: (row) => `people and businesses near ${row.community || 'this place'}` },
  {
    key: 'ageScore',
    label: 'Age vs deadline',
    detail: (row) => (row.slaDays ? `open ${row.daysWaiting ?? '-'} days, deadline ${row.slaDays} days` : 'no deadline found'),
  },
  {
    key: 'ticketCountScore',
    label: 'Repeat reports',
    detail: (row) => (row.sameDayTickets ? `${row.sameDayTickets} report(s) of this job that day` : 'one report'),
  },
]

const show = (value) => (value === undefined || value === null || value === '' ? '-' : value)

function compare(a, b, key) {
  const x = a[key]
  const y = b[key]
  if (typeof x === 'number' && typeof y === 'number') return x - y
  return String(x ?? '').localeCompare(String(y ?? ''), undefined, { numeric: true })
}

function RequestsTable({ rows, weights = {} }) {
  const [search, setSearch] = useState('')
  const [priority, setPriority] = useState('all')
  const [planFilter, setPlanFilter] = useState('all')
  const [crew, setCrew] = useState('all')
  // Default order: highest priority first, then the one waiting longest
  const [sort, setSort] = useState({ key: 'priorityScore', direction: 'desc' })
  const [page, setPage] = useState(0)
  const [openWhy, setOpenWhy] = useState(null) // the ticket whose score breakdown is open

  const hasPlanStatus = rows.some((row) => row.planStatus)
  const crewOptions = useMemo(() => [...new Set(rows.map((row) => row.crew))].filter(Boolean).sort(), [rows])

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase()
    const matches = rows.filter((row) => {
      if (priority !== 'all' && row.priorityBand !== priority) return false
      if (planFilter !== 'all' && row.planStatus !== planFilter) return false
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
  }, [rows, search, priority, planFilter, crew, sort])

  // Changing search, filters or sort always goes back to page 1 (done in the handlers, not an effect)
  const changeSearch = (value) => { setSearch(value); setPage(0) }
  const changePriority = (value) => { setPriority(value); setPage(0) }
  const changePlanFilter = (value) => { setPlanFilter(value); setPage(0) }
  const changeCrew = (value) => { setCrew(value); setPage(0) }
  const clearFilters = () => { setSearch(''); setPriority('all'); setPlanFilter('all'); setCrew('all'); setPage(0) }
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
          {hasPlanStatus && (
            <select
              value={planFilter}
              onChange={(event) => changePlanFilter(event.target.value)}
              aria-label="Filter by plan status"
              className={SELECT_CLASS}
            >
              <option value="all">All plan statuses</option>
              {PLAN_OPTIONS.map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
          )}
          <select
            value={crew}
            onChange={(event) => changeCrew(event.target.value)}
            aria-label="Filter by service area"
            className={`${SELECT_CLASS} capitalize`}
          >
            <option value="all">All service areas</option>
            {crewOptions.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </div>
        <div className="text-sm font-medium text-text">
          {visible.length.toLocaleString()} of {rows.length.toLocaleString()} requests
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
                  <th scope="col" className="border-b border-border px-4 py-2 font-semibold text-text">
                    Why?
                  </th>
                </tr>
              </thead>
              <tbody>
                {pageRows.map((row) => (
                  <Fragment key={row.id}>
                  <tr className="border-b border-border/60 hover:bg-panel">
                    <td className="px-4 py-2 whitespace-nowrap text-text">{show(row.id)}</td>
                    <td className="px-4 py-2 text-text">{show(row.serviceType)}</td>
                    <td className="px-4 py-2 text-text">{show(row.community)}</td>
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
                    <td className="px-4 py-2 text-right tabular-nums text-text">
                      <div>{show(row.daysWaiting)}</div>
                      {row.overdue && <div className="text-xs font-semibold text-text">Overdue</div>}
                    </td>
                    <td className="px-4 py-2 text-text">
                      <div className={row.planStatus === 'Assigned' ? 'font-semibold text-text' : 'text-text-muted'}>
                        {show(row.planStatus)}
                      </div>
                      {row.assignedCrew && <div className="text-xs text-text-muted">{row.assignedCrew}</div>}
                    </td>
                    <td className="px-4 py-2 text-text capitalize">{show(row.crew)}</td>
                    <td className="px-4 py-2 text-text">{show(row.status)}</td>
                    <td className="px-4 py-2">
                      <button
                        type="button"
                        aria-expanded={openWhy === row.id}
                        onClick={() => setOpenWhy(openWhy === row.id ? null : row.id)}
                        className={`${BUTTON_CLASS} px-2 py-0.5 text-xs`}
                      >
                        {openWhy === row.id ? 'Hide' : 'Why?'}
                      </button>
                    </td>
                  </tr>
                  {openWhy === row.id && (
                    <tr className="border-b border-border/60 bg-panel">
                      <td colSpan={COLUMNS.length + 1} className="px-4 py-3">
                        <div className="text-xs text-text-muted">How this score is made (team formula, each part 0 to 1):</div>
                        <table className="mt-1 text-sm">
                          <tbody>
                            {PARTS.map((part) => {
                              const weight = weights[part.key]
                              const value = row[part.key]
                              const points = typeof weight === 'number' && typeof value === 'number' ? weight * value * 100 : null
                              return (
                                <tr key={part.key}>
                                  <td className="py-0.5 pr-4 font-medium text-text">{part.label}</td>
                                  <td className="py-0.5 pr-4 text-right tabular-nums text-text">
                                    {show(weight)} x {typeof value === 'number' ? value.toFixed(2) : '-'}
                                  </td>
                                  <td className="py-0.5 pr-4 text-right tabular-nums text-text">
                                    = {points === null ? '-' : points.toFixed(1)}
                                  </td>
                                  <td className="py-0.5 text-text-muted">{show(part.detail(row))}</td>
                                </tr>
                              )
                            })}
                            <tr>
                              <td className="pt-1 pr-4 font-semibold text-text">Score</td>
                              <td />
                              <td className="pt-1 pr-4 text-right font-semibold tabular-nums text-text">
                                = {show(row.priorityScore)}
                              </td>
                              <td className="pt-1 text-text-muted">{show(row.priorityBand)}</td>
                            </tr>
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  )}
                  </Fragment>
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
