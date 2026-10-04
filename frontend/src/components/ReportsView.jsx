const show = (value) => (value === undefined || value === null || value === '' ? '-' : value)
// Two numbers shown side by side get the same decimals, so 5 and 49.4 read as 5.0 and 49.4
const asPair = (a, b) => {
  const decimal = [a, b].some((v) => typeof v === 'number' && !Number.isInteger(v))
  const fmt = (v) => (typeof v === 'number' && decimal ? v.toFixed(1) : show(v))
  return [fmt(a), fmt(b)]
}
// One decimal place for the loop table, so 43 and 14.6 line up as 43.0 and 14.6
const oneDecimal = (value) => (typeof value === 'number' ? value.toFixed(1) : show(value))

function Card({ label, value, note }) {
  return (
    <div className="rounded-md border border-border bg-white px-4 py-3">
      <div className="text-xs text-text-muted">{label}</div>
      <div className="text-2xl font-semibold text-text">{value}</div>
      {note && <div className="text-xs text-text-muted">{note}</div>}
    </div>
  )
}

function Section({ title, children }) {
  return (
    <section className="space-y-3">
      <h3 className="text-base font-semibold text-text">{title}</h3>
      {children}
    </section>
  )
}

// Same table look as the Requests, Dispatch and Crews pages
function Table({ columns, children }) {
  return (
    <div className="overflow-auto rounded-md border border-border">
      <table className="w-full border-collapse text-left text-sm">
        <thead className="bg-panel">
          <tr>
            {columns.map((column) => (
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
        <tbody>{children}</tbody>
      </table>
    </div>
  )
}

const COMPARISON_COLUMNS = [
  { label: 'Measure', numeric: false },
  { label: 'Oldest first', numeric: true },
  { label: 'Our plan', numeric: true },
  { label: 'Better', numeric: false },
]

const LOOP_COLUMNS = [
  { label: 'Try', numeric: true },
  { label: 'Setting', numeric: true },
  { label: 'High-priority planned', numeric: true },
  { label: 'Avg priority', numeric: true },
  { label: 'km per crew', numeric: true },
  { label: 'Quality', numeric: true },
  { label: 'Result', numeric: false },
]

function ReportsView({ data }) {
  const { summary, headline, comparison, loop, noon, limits } = data

  return (
    <div className="h-full overflow-auto px-5 py-4">
      <div className="mx-auto max-w-5xl space-y-6">
        {summary.isStandIn && (
          <p className="text-xs text-text-muted">Preview results: not the final algorithm output.</p>
        )}

        {/* 1. The headline numbers */}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {headline.map((item) => {
            const [ours, oldest] = asPair(item.ourPlan, item.oldestFirst)
            return (
            <Card
              key={item.label}
              label={item.label}
              value={ours}
              note={
                <>
                  Oldest first: {oldest}
                  {item.note ? <><br />{item.note}</> : null}
                </>
              }
            />
            )
          })}
        </div>

        {/* 2. Our plan vs oldest-first */}
        <Section title="Our plan vs oldest-first">
          <Table columns={COMPARISON_COLUMNS}>
            {comparison.map((row) => {
              const [oldest, ours] = asPair(row.oldestFirst, row.ourPlan)
              return (
              <tr key={row.label} className="border-b border-border/60 hover:bg-panel">
                <td className="px-4 py-2 text-text">
                  <div>{row.label}</div>
                  <div className="text-xs text-text-muted">
                    {row.betterIs === 'lower' ? 'Lower is better' : 'Higher is better'}
                  </div>
                </td>
                <td className="px-4 py-2 text-right tabular-nums text-text">{oldest}</td>
                <td className="px-4 py-2 text-right tabular-nums text-text">{ours}</td>
                <td className={`px-4 py-2 whitespace-nowrap text-text ${row.winner === 'Our plan' ? 'font-semibold' : ''}`}>
                  {show(row.winner)}
                </td>
              </tr>
              )
            })}
          </Table>
        </Section>

        {/* 3. How the planner improved */}
        <Section title="How the planner improved">
          <p className="text-sm text-text-muted">{show(loop.setting)}</p>
          <Table columns={LOOP_COLUMNS}>
            {loop.tries.map((row) => (
              <tr
                key={row.try}
                className={`border-b border-border/60 hover:bg-panel ${row.note.includes('Kept') ? 'font-semibold' : ''}`}
              >
                <td className="px-4 py-2 text-right tabular-nums text-text">{show(row.try)}</td>
                <td className="px-4 py-2 text-right tabular-nums text-text">{oneDecimal(row.setting)}</td>
                <td className="px-4 py-2 text-right tabular-nums text-text">{show(row.highPlanned)}</td>
                <td className="px-4 py-2 text-right tabular-nums text-text">{oneDecimal(row.avgPriority)}</td>
                <td className="px-4 py-2 text-right tabular-nums text-text">{oneDecimal(row.kmPerCrew)}</td>
                <td className="px-4 py-2 text-right tabular-nums text-text">{oneDecimal(row.quality)}</td>
                <td className="px-4 py-2 text-text">{show(row.note)}</td>
              </tr>
            ))}
          </Table>
          <p className="text-sm text-text-muted">
            {show(loop.qualityFormula)}. Stopped because: {show(loop.stoppedBecause)}.
          </p>
        </Section>

        {/* 4. When a crew goes missing */}
        <Section title="When a crew goes missing">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Card label="Crew out at noon" value={show(noon.missingCrew)} />
            <Card label="Moved to another crew" value={show(noon.moved)} />
            <Card label="Pushed to tomorrow" value={show(noon.pushed)} />
            <Card label="Urgent jobs still covered" value={show(noon.urgentStillCovered)} note="High priority, still planned today" />
          </div>
        </Section>

        {/* 5. Limits */}
        <Section title="Limits">
          <ul className="list-disc space-y-1 pl-5 text-sm text-text">
            {limits.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </Section>
      </div>
    </div>
  )
}

export default ReportsView
