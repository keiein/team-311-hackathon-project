import { useState } from 'react'
import DisruptionControls from './DisruptionControls'
import WorkforceGrid from './WorkforceGrid'
import ReorganizedCrewsGrid from './ReorganizedCrewsGrid'
import { useSimulation } from '../simulation/SimulationContext'

const show = (value) => (value === undefined || value === null || value === '' ? '-' : value)
const num = (value) => (typeof value === 'number' ? value.toLocaleString() : show(value))

const BUTTON_CLASS = 'rounded-md border border-border bg-white px-3 py-1.5 text-sm text-text shadow-sm hover:bg-panel'
const ACTIVE_BUTTON_CLASS =
  'rounded-md border border-calgary-red bg-white px-3 py-1.5 text-sm font-semibold text-calgary-red shadow-sm'

function Card({ label, value, note }) {
  return (
    <div className="rounded-md border border-border bg-white px-4 py-3">
      <div className="text-xs text-text-muted">{label}</div>
      <div className="text-2xl font-semibold text-text">{value}</div>
      {note && <div className="text-xs text-text-muted">{note}</div>}
    </div>
  )
}

function DisruptionImpactSummary({
  sickActive,
  blizzardActive,
  sickPeople,
  snowRedeployed,
  totalPeople,
  usablePeople,
  peoplePerCrew,
  jobsPerCrew,
  deployableCrews,
  dailyJobCapacity,
}) {
  if (!sickActive && !blizzardActive) {
    return (
      <div className="rounded-md border border-border bg-panel px-4 py-3 text-xs text-text-muted">
        No active disruptions — full simulated workforce available.
      </div>
    )
  }

  const normalCrews = peoplePerCrew > 0 ? Math.floor(totalPeople / peoplePerCrew) : 0
  const normalJobs = normalCrews * jobsPerCrew
  const jobsDeferred = Math.max(0, normalJobs - dailyJobCapacity)

  const title =
    sickActive && blizzardActive
      ? 'Current disruption impact'
      : sickActive
        ? 'Sick Call impact'
        : 'Blizzard impact'

  return (
    <div className="rounded-md border border-border bg-white px-4 py-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-text">{title}</div>
      <ul className="mt-2 space-y-1 text-sm text-text">
        {sickActive && (
          <li>
            <span className="font-medium">{num(sickPeople)}</span> sick
          </li>
        )}
        {blizzardActive && (
          <li>
            <span className="font-medium">{num(snowRedeployed)}</span> redeployed to snow
          </li>
        )}
        <li>
          {num(totalPeople)} → <span className="font-medium">{num(usablePeople)}</span> usable personnel
        </li>
        <li>
          {num(normalCrews)} → <span className="font-medium">{num(deployableCrews)}</span> deployable crews
        </li>
        <li>
          {num(normalJobs)} → <span className="font-medium">{num(dailyJobCapacity)}</span> scheduled jobs
        </li>
        <li>
          <span className="font-medium">{num(jobsDeferred)}</span> jobs deferred vs undisrupted capacity
        </li>
      </ul>
    </div>
  )
}

function WorkforcePanel() {
  const {
    workforce,
    rules,
    source,
    note,
    deferredCount,
    sickActive,
    blizzardActive,
    sickPeople,
    snowRedeployed,
    sickWorkerIds,
    snowRedeployedWorkerIds,
    dispatch,
  } = useSimulation()

  const [gridView, setGridView] = useState('disruption')

  if (!workforce) return null

  const totalPeople = workforce.total_people ?? 100
  const peoplePerCrew = workforce.people_per_crew ?? 5
  const jobsPerCrew = workforce.jobs_per_crew ?? 5

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
          label="Deployable Crews"
          value={num(workforce.plan_capacity)}
          note={`${num(workforce.people_per_crew)} people per crew`}
        />
        <Card
          label="Daily Job Capacity"
          value={num(workforce.daily_job_capacity)}
          note={`${num(jobsPerCrew)} jobs per crew`}
        />
        <Card label="Sick" value={num(workforce.sick_people)} />
        <Card label="Snow Redeployed" value={num(workforce.snow_redeployed)} />
        <Card label="People Per Crew" value={num(workforce.people_per_crew)} />
        <Card label="Jobs deferred" value={num(deferredCount)} note="below daily capacity" />
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-auto px-5 py-4">
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Workforce visualization">
          <button
            type="button"
            aria-pressed={gridView === 'disruption'}
            onClick={() => setGridView('disruption')}
            className={gridView === 'disruption' ? ACTIVE_BUTTON_CLASS : BUTTON_CLASS}
          >
            Disruption impact
          </button>
          <button
            type="button"
            aria-pressed={gridView === 'reorganized'}
            onClick={() => setGridView('reorganized')}
            className={gridView === 'reorganized' ? ACTIVE_BUTTON_CLASS : BUTTON_CLASS}
          >
            Reorganized crews
          </button>
        </div>

        {gridView === 'disruption' && (
          <>
            <DisruptionImpactSummary
              sickActive={sickActive}
              blizzardActive={blizzardActive}
              sickPeople={sickPeople}
              snowRedeployed={snowRedeployed}
              totalPeople={totalPeople}
              usablePeople={workforce.usable_people}
              peoplePerCrew={peoplePerCrew}
              jobsPerCrew={jobsPerCrew}
              deployableCrews={workforce.plan_capacity}
              dailyJobCapacity={workforce.daily_job_capacity}
            />
            <WorkforceGrid
              totalPeople={totalPeople}
              peoplePerCrew={peoplePerCrew}
              sickWorkerIds={sickWorkerIds}
              snowRedeployedWorkerIds={snowRedeployedWorkerIds}
            />
          </>
        )}

        {gridView === 'reorganized' && (
          <ReorganizedCrewsGrid
            totalPeople={totalPeople}
            peoplePerCrew={peoplePerCrew}
            jobsPerCrew={jobsPerCrew}
            sickPeople={sickPeople}
            snowRedeployed={snowRedeployed}
            sickWorkerIds={sickWorkerIds}
            snowRedeployedWorkerIds={snowRedeployedWorkerIds}
            usablePeople={workforce.usable_people}
            deployableCrews={workforce.plan_capacity}
            dailyJobCapacity={workforce.daily_job_capacity}
            dispatch={dispatch}
          />
        )}

        <ul className="list-disc space-y-1 pl-5 text-xs text-text-muted">
          {(rules ?? []).map((rule) => (
            <li key={rule}>{rule}</li>
          ))}
          <li>
            Sick Call picks a random 0–10 people when turned on; Blizzard picks a random 20–35. The same worker
            slots stay marked until the toggle is turned off.
          </li>
          <li>
            Disruption impact shows the original 100 slots. Reorganized crews regroup only available people into
            complete {peoplePerCrew}-person crews used by Dispatch.
          </li>
        </ul>
      </div>
    </div>
  )
}

export default WorkforcePanel
