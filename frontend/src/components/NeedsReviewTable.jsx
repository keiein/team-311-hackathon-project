import { useMemo, useState } from 'react'

const PAGE_SIZE = 50

// Same look as the Requests table
const INPUT_CLASS =
  'rounded-md border border-border bg-white px-3 py-1.5 text-sm text-text shadow-sm placeholder:text-neutral-400 focus:border-calgary-red focus:outline-none focus:ring-1 focus:ring-calgary-red'
const SELECT_CLASS =
  'rounded-md border border-border bg-white px-2.5 py-1.5 text-sm text-text shadow-sm focus:border-calgary-red focus:outline-none focus:ring-1 focus:ring-calgary-red'
const BUTTON_CLASS =
  'rounded-md border border-border bg-white px-3 py-1.5 text-sm text-text shadow-sm hover:bg-panel disabled:cursor-not-allowed disabled:text-neutral-400 disabled:hover:bg-white'

const COLUMNS = [
  { label: 'Ticket no.', numeric: false },
  { label: 'Type of problem', numeric: false },
  { label: 'Community', numeric: false },
  { label: 'Severity', numeric: false },
  { label: 'Days waiting', numeric: true },
  { label: 'Crew', numeric: false },
]

const show = (value) => (value === undefined || value === null || value === '' ? '-' : value)

// Rows arrive already sorted (most dangerous type first, then oldest); this table keeps that order.
function NeedsReviewTable({ data }) {
  const [search, setSearch] = useState('')
  const [crew, setCrew] = useState('all')
  const [page, setPage] = useState(0)

  const crewOptions = useMemo(() => [...new Set(data.rows.map((row) => row.crew))].filter(Boolean).sort(), [data.rows])
  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return data.rows.filter((row) => {
      if (crew !== 'all' && row.crew !== crew) return false
      if (!needle) return true
      return [row.id, row.serviceType, row.community].some((value) => String(value ?? '').toLowerCase().includes(needle))
    })
  }, [data.rows, search, crew])

  const pageCount = Math.max(1, Math.ceil(visible.length / PAGE_SIZE))
  const currentPage = Math.min(page, pageCount - 1)
  const first = currentPage * PAGE_SIZE
  const pageRows = visible.slice(first, first + PAGE_SIZE)

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border bg-white px-5 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="search"
            value={search}
            onChange={(event) => { setSearch(event.target.value); setPage(0) }}
            placeholder="Search ticket, type or community..."
            aria-label="Search tickets to review"
            className={`w-64 ${INPUT_CLASS}`}
          />
          <select
            value={crew}
            onChange={(event) => { setCrew(event.target.value); setPage(0) }}
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
            {visible.length.toLocaleString()} of {data.rows.length.toLocaleString()} tickets to review
          </div>
          <div>{show(data.note)}</div>
        </div>
      </div>

      {visible.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-5">
          <p className="text-sm text-text-muted">No tickets match your filters</p>
          <button
            type="button"
            onClick={() => { setSearch(''); setCrew('all'); setPage(0) }}
            className={`${BUTTON_CLASS} text-calgary-red`}
          >
            Clear filters
          </button>
        </div>
      ) : (
        <>
          <div className="min-h-0 flex-1 overflow-auto">
            <table className="w-full border-collapse text-left text-sm">
              <thead className="sticky top-0 z-10 bg-panel">
                <tr>
                  {COLUMNS.map((column) => (
                    <th
                      key={column.label}
                      scope="col"
                      className={`border-b border-border px-4 py-2 font-semibold text-text ${column.numeric ? 'text-right' : ''}`}
                    >
                      {column.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pageRows.map((row) => (
                  <tr key={row.id} className="border-b border-border/60 hover:bg-panel">
                    <td className="px-4 py-2 whitespace-nowrap text-text">{show(row.id)}</td>
                    <td className="px-4 py-2 text-text">{show(row.serviceType)}</td>
                    <td className="px-4 py-2 text-text">{show(row.community)}</td>
                    <td className="px-4 py-2 text-text">{show(row.severityName)}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-text">{show(row.daysWaiting)}</td>
                    <td className="px-4 py-2 text-text capitalize">{show(row.crew)}</td>
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

export default NeedsReviewTable
