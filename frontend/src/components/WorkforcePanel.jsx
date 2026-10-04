import DisruptionControls from './DisruptionControls'
import { useSimulation } from '../simulation/SimulationContext'

const show = (value) => (value === undefined || value === null || value === '' ? '-' : value)
const num = (value) => (typeof value === 'number' ? value.toLocaleString() : show(value))

function Card({ label, value, note }) {
  return (
    <div className="rounded-md border border-border bg-white px-4 py-3">
      <div className="text-xs text-text-muted">{label}</div>
      <div className="text-2xl font-semibold text-text">{value}</div>
      {note && <div className="text-xs text-text-muted">{note}</div>}
    </div>
  )
}

function WorkforcePanel() {
  const { workforce, rules, source, note, deferredCount } = useSimulation()

  if (!workforce) return null

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-start justify-between gap-3 border-b border-border bg-white px-5 py-3">
        <div>
          <div className="text-sm font-semibold text-text">Shared Operational Workforce</div>
          <p className="mt-1 max-w-2xl text-xs text-text-muted">
            {show(note)} One workforce for all 311 jobs. Ticket <code className="text-xs">crew_pool</code> is
            service-area metadata only — it does not limit who can take a job.
          </p>
        </div>
        <div className="text-right text-xs text-text-muted">
          <div>Source: {show(source)}</div>
          {workforce.isSimulatedPlaceholder && <div>Simulated hackathon placeholder</div>}
        </div>
      </div>

      <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-border bg-white px-5 py-3">
        <DisruptionControls />
      </div>

      <div className="grid shrink-0 grid-cols-2 gap-3 border-b border-border bg-white px-5 py-3 md:grid-cols-4">
        <Card label="Total Personnel" value={num(workforce.total_people)} note="Stable headcount" />
        <Card label="Usable Personnel" value={num(workforce.usable_people)} note="total − sick − snow" />
        <Card label="Busy on 311 Jobs" value={num(workforce.busy_people)} />
        <Card
          label="Plan Capacity"
          value={num(workforce.plan_capacity)}
          note={`${num(workforce.people_per_crew)} people per crew`}
        />
        <Card label="Sick" value={num(workforce.sick_people)} />
        <Card label="Snow Redeployed" value={num(workforce.snow_redeployed)} />
        <Card label="People Per Crew" value={num(workforce.people_per_crew)} />
        <Card label="Jobs deferred" value={num(deferredCount)} note="below plan capacity" />
      </div>

      <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
        <ul className="list-disc space-y-1 pl-5 text-xs text-text-muted">
          {(rules ?? []).map((rule) => (
            <li key={rule}>{rule}</li>
          ))}
          <li>Sick Call picks a random 0–10 people when turned on; Blizzard picks a random 20–35. Values stay fixed until toggled off.</li>
          <li>Dispatch and Requests replan from the same disruption state (highest priority_rank first).</li>
        </ul>
      </div>
    </div>
  )
}

export default WorkforcePanel
