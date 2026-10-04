import { useMemo, useState } from 'react'

// Same colours as the map and the Requests page. The word is always shown too.
const BAND_STYLE = {
  High: { background: '#c8102e', color: '#ffffff' },
  Medium: { background: '#f59e0b', color: '#1a1a1a' },
  Low: { background: '#9ca3af', color: '#1a1a1a' },
}

// Same look as the dropdowns and buttons on the Requests page
const SELECT_CLASS =
  'rounded-md border border-border bg-white px-2.5 py-1.5 text-sm text-text shadow-sm focus:border-calgary-red focus:outline-none focus:ring-1 focus:ring-calgary-red'
const BUTTON_CLASS =
  'rounded-md border border-border bg-white px-3 py-1.5 text-sm text-text shadow-sm hover:bg-panel'
const ACTIVE_BUTTON_CLASS =
  'rounded-md border border-calgary-red bg-white px-3 py-1.5 text-sm font-semibold text-calgary-red shadow-sm'

const COLUMNS = [
  { label: 'Stop', numeric: true },
  { label: 'Ticket no.', numeric: false },
  { label: 'Type of problem', numeric: false },
  { label: 'Community', numeric: false },
  { label: 'Priority', numeric: true },
  { label: 'Days waiting', numeric: true },
  { label: 'Assignment', numeric: false },
  { label: 'Why', numeric: false },
]

// Inside one crew: by stop, and for the same stop a moved-in job comes before the job it replaced
const ASSIGNMENT_ORDER = { 'Done before noon': 0, Planned: 1, Moved: 2, 'Pushed to tomorrow': 3 }

const show = (value) => (value === undefined || value === null || value === '' ? '-' : value)

function assignmentText(row) {
  if (row.assignment === 'Moved') return row.movedFrom ? `Moved from ${row.movedFrom}` : 'Moved'
  return show(row.assignment)
}

function Card({ label, value, note }) {
  return (
    <div className="rounded-md border border-border bg-white px-4 py-3">
      <div className="text-xs text-text-muted">{label}</div>
      <div className="text-2xl font-semibold text-text">{value}</div>
      {note && <div className="text-xs text-text-muted">{note}</div>}
    </div>
  )
}

function DispatchTable({ data }) {
  const { summary, crews } = data
  const livePlan = Boolean(summary.livePlan)
  const [scenario, setScenario] = useState('morning')
  const [crew, setCrew] = useState('all')

  const missingCrew = summary.noon?.missingCrew
  const activeScenario = livePlan ? 'morning' : scenario

  // Rows for the chosen scenario and crew, grouped by crew in the file's crew order
  const groups = useMemo(() => {
    const rows = data[activeScenario].filter((row) => crew === 'all' || row.crew === crew)
    const byCrew = new Map()
    rows.forEach((row) => {
      if (!byCrew.has(row.crew)) byCrew.set(row.crew, [])
      byCrew.get(row.crew).push(row)
    })
    const order = [...crews, ...[...byCrew.keys()].filter((name) => !crews.includes(name))]
    return order
      .filter((name) => byCrew.has(name))
      .map((name) => ({
        name,
        rows: byCrew.get(name).sort(
          (a, b) => a.stop - b.stop || (ASSIGNMENT_ORDER[a.assignment] ?? 9) - (ASSIGNMENT_ORDER[b.assignment] ?? 9),
        ),
      }))
  }, [data, crews, activeScenario, crew])

  const rowCount = groups.reduce((total, group) => total + group.rows.length, 0)

  // Group header text, like "5 jobs, 4 High" (jobs pushed to tomorrow are counted separately)
  const groupSummary = (rows) => {
    const pushed = rows.filter((row) => row.assignment === 'Pushed to tomorrow').length
    const active = rows.length - pushed
    const high = rows.filter((row) => row.assignment !== 'Pushed to tomorrow' && row.priorityBand === 'High').length
    return `${active} jobs, ${high} High${pushed ? `, ${pushed} pushed to tomorrow` : ''}`
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Scenario switch, crew filter, and the preview note */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border bg-white px-5 py-3">
        <div className="flex flex-wrap items-center gap-2">
          {!livePlan && (
            <div className="flex items-center gap-2" role="group" aria-label="Plan to show">
              <button
                type="button"
                aria-pressed={scenario === 'morning'}
                onClick={() => setScenario('morning')}
                className={scenario === 'morning' ? ACTIVE_BUTTON_CLASS : BUTTON_CLASS}
              >
                8 a.m. plan
              </button>
              <button
                type="button"
                aria-pressed={scenario === 'noon'}
                onClick={() => setScenario('noon')}
                className={scenario === 'noon' ? ACTIVE_BUTTON_CLASS : BUTTON_CLASS}
              >
                After crew goes missing{missingCrew ? ` (${missingCrew})` : ''}
              </button>
            </div>
          )}
          <select
            value={crew}
            onChange={(event) => setCrew(event.target.value)}
            aria-label="Filter by crew"
            className={SELECT_CLASS}
          >
            <option value="all">All Crews</option>
            {crews.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
        <div className="text-right text-xs text-text-muted">
          <div className="text-sm font-medium text-text">{rowCount.toLocaleString()} assignments</div>
          {summary.isStandIn && <div>Live capacity plan from shared workforce disruptions.</div>}
          {typeof summary.noon?.pushed === 'number' && summary.noon.pushed > 0 && (
            <div>{summary.noon.pushed.toLocaleString()} tickets waiting (below capacity)</div>
          )}
        </div>
      </div>

      {/* Counters */}
      <div className={`grid shrink-0 grid-cols-1 gap-3 border-b border-border bg-white px-5 py-3 ${livePlan ? 'md:grid-cols-4' : 'md:grid-cols-3'}`}>
        {activeScenario === 'morning' || livePlan ? (
          <>
            <Card
              label="Planned jobs"
              value={`${show(summary.plannedJobs)} of ${(summary.poolSize ?? 0).toLocaleString()}`}
              note="open crew jobs today"
            />
            <Card
              label="Crews"
              value={show(summary.crewCount)}
              note={livePlan ? `${show(summary.peoplePerCrew)} people per crew` : `${show(summary.jobsPerCrew)} jobs each`}
            />
            {livePlan && (
              <Card
                label="Jobs per crew"
                value={show(summary.jobsPerCrew)}
                note={`daily capacity ${show(summary.dailyJobCapacity ?? summary.plannedJobs)}`}
              />
            )}
            <Card
              label="High-priority jobs planned"
              value={show(summary.morning?.highPriorityPlanned)}
              note={livePlan && typeof summary.waitingJobs === 'number' ? `${summary.waitingJobs.toLocaleString()} waiting` : undefined}
            />
          </>
        ) : (
          <>
            <Card label="Moved to another crew" value={show(summary.noon?.moved)} note={missingCrew ? `from ${missingCrew}` : undefined} />
            <Card label="Pushed to tomorrow" value={show(summary.noon?.pushed)} />
            <Card label="Urgent jobs still covered" value={show(summary.noon?.urgentStillCovered)} note="High priority, still planned today" />
          </>
        )}
      </div>

      {rowCount === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-5">
          <p className="text-sm text-text-muted">No assignments for this crew</p>
          <button type="button" onClick={() => setCrew('all')} className={`${BUTTON_CLASS} text-calgary-red`}>
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
            {groups.map((group) => (
              <tbody key={group.name}>
                <tr>
                  <th
                    colSpan={COLUMNS.length}
                    scope="colgroup"
                    className="border-b border-border bg-panel px-4 py-2 text-left text-sm font-semibold text-text"
                  >
                    {group.name}{' '}
                    <span className="ml-1 font-normal text-text-muted">
                      {groupSummary(group.rows)}
                      {scenario === 'noon' && group.name === missingCrew ? ', out from noon' : ''}
                    </span>
                  </th>
                </tr>
                {group.rows.map((row) => (
                  <tr key={`${row.crew}-${row.id}`} className="border-b border-border/60 hover:bg-panel">
                    <td className="px-4 py-2 text-right tabular-nums text-text">{show(row.stop)}</td>
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
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums text-text">{show(row.daysWaiting)}</td>
                    <td
                      className={`px-4 py-2 whitespace-nowrap text-text ${row.assignment === 'Moved' || row.assignment === 'Pushed to tomorrow' ? 'font-semibold' : ''}`}
                    >
                      {assignmentText(row)}
                    </td>
                    <td className="px-4 py-2 text-text-muted">{show(row.why)}</td>
                  </tr>
                ))}
              </tbody>
            ))}
          </table>
        </div>
      )}
    </div>
  )
}

export default DispatchTable
