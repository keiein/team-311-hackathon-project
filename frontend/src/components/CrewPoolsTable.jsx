// Alvin's crew_pool table (scoring/CREW_POOL.md): total_people, busy_people, available_people,
// at 8 a.m. and after the noon sick call, next to each pool's jobs today.
const COLUMNS = [
  { label: 'Pool (department)', numeric: false },
  { label: 'People', numeric: true },
  { label: 'Crews', numeric: true },
  { label: 'Busy 8 a.m.', numeric: true },
  { label: 'Available 8 a.m.', numeric: true },
  { label: 'People after noon', numeric: true },
  { label: 'Busy after noon', numeric: true },
  { label: 'Available after noon', numeric: true },
  { label: 'Open jobs today', numeric: true },
  { label: 'High priority', numeric: true },
]

const show = (value) => (value === undefined || value === null || value === '' ? '-' : value)
const num = (value) => (typeof value === 'number' ? value.toLocaleString() : show(value))

function CrewPoolsTable({ data }) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-start justify-between gap-3 border-b border-border bg-white px-5 py-3">
        <ul className="list-disc space-y-0.5 pl-5 text-xs text-text-muted">
          {(data.rules ?? []).map((rule) => (
            <li key={rule}>{rule}</li>
          ))}
        </ul>
        <div className="text-right text-xs text-text-muted">
          <div className="text-sm font-medium text-text">{data.pools.length} crew pools</div>
          <div>{show(data.note)}</div>
          <div>Source: {show(data.source)}</div>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-collapse text-left text-sm">
          <thead className="sticky top-0 z-10 bg-panel">
            <tr>
              {COLUMNS.map((column) => (
                <th
                  key={column.label}
                  scope="col"
                  className={`border-b border-border px-3 py-2 font-semibold text-text ${column.numeric ? 'text-right' : ''}`}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.pools.map((row) => (
              <tr key={row.pool} className="border-b border-border/60 hover:bg-panel">
                <td className="px-3 py-2 text-text">
                  <div>{show(row.pool)}</div>
                  {row.sickAtNoon > 0 && (
                    <div className="text-xs font-semibold text-text">{row.sickAtNoon} people call in sick at noon</div>
                  )}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-text">{num(row.people)}</td>
                <td className="px-3 py-2 text-right tabular-nums text-text">{num(row.crews)}</td>
                <td className="px-3 py-2 text-right tabular-nums text-text">{num(row.busy8am)}</td>
                <td className="px-3 py-2 text-right tabular-nums text-text">{num(row.available8am)}</td>
                <td className={`px-3 py-2 text-right tabular-nums text-text ${row.sickAtNoon > 0 ? 'font-semibold' : ''}`}>
                  {num(row.peopleNoon)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-text">{num(row.busyNoon)}</td>
                <td className="px-3 py-2 text-right tabular-nums text-text">{num(row.availableNoon)}</td>
                <td className="px-3 py-2 text-right tabular-nums text-text">{num(row.openJobs)}</td>
                <td className="px-3 py-2 text-right tabular-nums text-text">{num(row.highPriorityJobs)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default CrewPoolsTable
