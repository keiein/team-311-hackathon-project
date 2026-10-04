import { useMemo, useState } from 'react'

// Same look as the dropdowns and buttons on the Requests and Dispatch pages
const SELECT_CLASS =
  'rounded-md border border-border bg-white px-2.5 py-1.5 text-sm text-text shadow-sm focus:border-calgary-red focus:outline-none focus:ring-1 focus:ring-calgary-red'
const BUTTON_CLASS =
  'rounded-md border border-border bg-white px-3 py-1.5 text-sm text-text shadow-sm hover:bg-panel'

const COLUMNS = [
  { label: 'Crew', numeric: false },
  { label: 'Kind', numeric: false },
  { label: 'Status at noon', numeric: false },
  { label: 'Planned jobs', numeric: true },
  { label: 'High priority', numeric: true },
  { label: 'Done before noon', numeric: true },
  { label: 'Still to do', numeric: true },
  { label: 'Moved in', numeric: true },
  { label: 'Pushed to tomorrow', numeric: true },
  { label: 'Areas', numeric: false },
]

const show = (value) => (value === undefined || value === null || value === '' ? '-' : value)

function Card({ label, value, note }) {
  return (
    <div className="rounded-md border border-border bg-white px-4 py-3">
      <div className="text-xs text-text-muted">{label}</div>
      <div className="text-2xl font-semibold text-text">{value}</div>
      {note && <div className="text-xs text-text-muted">{note}</div>}
    </div>
  )
}

// The first 3 areas, then "+N more". The full list is in the tooltip.
function areasText(communities = []) {
  if (communities.length === 0) return '-'
  const first = communities.slice(0, 3).join(', ')
  return communities.length > 3 ? `${first} +${communities.length - 3} more` : first
}

function CrewsTable({ data }) {
  const { summary, crewSummary } = data
  const [kind, setKind] = useState('all')

  const kinds = useMemo(() => [...new Set(crewSummary.map((row) => row.crewKind))].filter(Boolean), [crewSummary])
  const rows = useMemo(
    () => crewSummary.filter((row) => kind === 'all' || row.crewKind === kind),
    [crewSummary, kind],
  )

  const out = crewSummary.filter((row) => row.noon?.status === 'Out from noon')
  const active = crewSummary.filter((row) => row.noon?.status === 'Active')

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border bg-white px-5 py-3">
        <select
          value={kind}
          onChange={(event) => setKind(event.target.value)}
          aria-label="Filter by kind"
          className={`${SELECT_CLASS} capitalize`}
        >
          <option value="all">All Kinds</option>
          {kinds.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <div className="text-right text-xs text-text-muted">
          <div className="text-sm font-medium text-text">
            {rows.length} of {crewSummary.length} crews
          </div>
          {summary.isStandIn && <div>Preview plan: not the final algorithm output.</div>}
        </div>
      </div>

      <div className="grid shrink-0 grid-cols-2 gap-3 border-b border-border bg-white px-5 py-3 md:grid-cols-4">
        <Card label="Crews" value={crewSummary.length} />
        <Card label="Active at noon" value={active.length} />
        <Card label="Out from noon" value={out.length} note={out.map((row) => row.crew).join(', ') || undefined} />
        <Card label="Jobs per crew" value={show(summary.jobsPerCrew)} />
      </div>

      {rows.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-5">
          <p className="text-sm text-text-muted">No crews match</p>
          <button type="button" onClick={() => setKind('all')} className={`${BUTTON_CLASS} text-calgary-red`}>
            Clear filter
          </button>
        </div>
      ) : (
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
              {rows.map((row) => (
                <tr key={row.crew} className="border-b border-border/60 hover:bg-panel">
                  <td className="px-4 py-2 whitespace-nowrap font-medium text-text">{show(row.crew)}</td>
                  <td className="px-4 py-2 text-text capitalize">{show(row.crewKind)}</td>
                  <td
                    className={`px-4 py-2 whitespace-nowrap text-text ${row.noon?.status === 'Out from noon' ? 'font-semibold' : ''}`}
                  >
                    {show(row.noon?.status)}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums text-text">{show(row.jobsPlanned)}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-text">{show(row.highPlanned)}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-text">{show(row.noon?.doneBeforeNoon)}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-text">{show(row.noon?.stillToDo)}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-text">{show(row.noon?.movedIn)}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-text">{show(row.noon?.pushedToTomorrow)}</td>
                  <td className="px-4 py-2 text-text-muted" title={(row.communities ?? []).join(', ')}>
                    {areasText(row.communities)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default CrewsTable
