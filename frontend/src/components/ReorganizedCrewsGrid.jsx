import { WORKFORCE_SLOT_COLORS } from './WorkforceGrid'
import { listAvailableWorkerIds, regroupAvailableWorkers } from '../simulation/regroupWorkforce.js'

const num = (value) => (typeof value === 'number' ? value.toLocaleString() : String(value ?? '-'))

/**
 * Reorganized operational crews: available workers only, chunked into
 * complete people_per_crew groups. Names match Dispatch (Crew 1..N).
 */
function ReorganizedCrewsGrid({
  totalPeople = 100,
  peoplePerCrew = 5,
  jobsPerCrew = 5,
  sickPeople = 0,
  snowRedeployed = 0,
  sickWorkerIds = [],
  snowRedeployedWorkerIds = [],
  usablePeople,
  deployableCrews,
  dailyJobCapacity,
  dispatch = null,
}) {
  const availableIds = listAvailableWorkerIds(totalPeople, sickWorkerIds, snowRedeployedWorkerIds)
  const { crews, reserveWorkerIds } = regroupAvailableWorkers(availableIds, peoplePerCrew)

  const jobsByCrew = new Map()
  for (const row of dispatch?.morning ?? []) {
    jobsByCrew.set(row.crew, (jobsByCrew.get(row.crew) ?? 0) + 1)
  }

  const usable = usablePeople ?? availableIds.length
  const crewsCount = deployableCrews ?? crews.length
  const jobSlots = dailyJobCapacity ?? crewsCount * jobsPerCrew

  return (
    <div className="space-y-3">
      <div className="rounded-md border border-border bg-white px-4 py-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-text">Workforce reorganized</div>
        <ul className="mt-2 space-y-1 text-sm text-text">
          <li>
            {num(totalPeople)} total personnel
            {sickPeople > 0 ? <> − {num(sickPeople)} sick</> : null}
            {snowRedeployed > 0 ? <> − {num(snowRedeployed)} snow redeployed</> : null}
            {' '}
            = <span className="font-medium">{num(usable)}</span> usable personnel
          </li>
          <li>
            {num(usable)} usable ÷ {num(peoplePerCrew)} people per crew ={' '}
            <span className="font-medium">{num(crewsCount)}</span> deployable crews
          </li>
          <li>
            {num(crewsCount)} crews × {num(jobsPerCrew)} jobs per crew ={' '}
            <span className="font-medium">{num(jobSlots)}</span> jobs scheduled today
          </li>
          {reserveWorkerIds.length > 0 && (
            <li>
              <span className="font-medium">{num(reserveWorkerIds.length)}</span> available worker
              {reserveWorkerIds.length === 1 ? '' : 's'} remain in reserve (not a partial crew)
            </li>
          )}
        </ul>
      </div>

      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-text">Operational crews</h3>
          <p className="text-xs text-text-muted">
            Same available worker slots, regrouped into complete crews of {peoplePerCrew}. These names match
            Dispatch (Crew 1–{crewsCount || 0}).
          </p>
        </div>
        <ul className="flex flex-wrap items-center gap-3 text-xs text-text-muted">
          <li className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ backgroundColor: WORKFORCE_SLOT_COLORS.available }}
              aria-hidden="true"
            />
            Available (on a crew)
          </li>
        </ul>
      </div>

      {crews.length === 0 ? (
        <p className="text-sm text-text-muted">No complete crews can be formed from the remaining workforce.</p>
      ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-5">
          {crews.map((crew) => {
            const jobsToday = jobsByCrew.get(crew.name) ?? 0
            return (
              <div key={crew.name} className="rounded-md border border-border bg-white px-2 py-1.5">
                <div className="mb-1 flex items-baseline justify-between gap-1">
                  <span className="text-[10px] font-medium uppercase tracking-wide text-text-muted">
                    {crew.name}
                  </span>
                  <span className="text-[10px] tabular-nums text-text-muted">
                    {crew.workerIds.length}p · {jobsToday}j
                  </span>
                </div>
                <div className="flex gap-1">
                  {crew.workerIds.map((id) => (
                    <span
                      key={id}
                      title={`Worker ${id} → ${crew.name}`}
                      aria-label={`Worker ${id} on ${crew.name}`}
                      className="inline-block h-3.5 w-3.5 rounded-sm border border-black/10"
                      style={{ backgroundColor: WORKFORCE_SLOT_COLORS.available }}
                    />
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {reserveWorkerIds.length > 0 && (
        <div className="rounded-md border border-dashed border-border bg-panel px-3 py-2">
          <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-text-muted">
            Unassigned / reserve
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex gap-1">
              {reserveWorkerIds.map((id) => (
                <span
                  key={id}
                  title={`Worker ${id} — reserve`}
                  aria-label={`Worker ${id}, reserve`}
                  className="inline-block h-3.5 w-3.5 rounded-sm border border-black/10"
                  style={{ backgroundColor: WORKFORCE_SLOT_COLORS.available }}
                />
              ))}
            </div>
            <span className="text-xs text-text-muted">
              {reserveWorkerIds.length} available worker{reserveWorkerIds.length === 1 ? '' : 's'} (not enough for
              another {peoplePerCrew}-person crew)
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

export default ReorganizedCrewsGrid
