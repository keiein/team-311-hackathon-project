/**
 * Anonymous simulated workforce slots (Worker 1..N).
 * Visual only — capacity still comes from shared sick/snow counts in SimulationContext.
 */

export const WORKFORCE_SLOT_COLORS = {
  available: '#404040',
  sick: '#d4d4d4',
  snow: '#5b8def',
}

function WorkforceGrid({
  totalPeople = 100,
  peoplePerCrew = 5,
  sickWorkerIds = [],
  snowRedeployedWorkerIds = [],
}) {
  const sickSet = new Set(sickWorkerIds)
  const snowSet = new Set(snowRedeployedWorkerIds)
  const groupSize = Math.max(1, peoplePerCrew)
  const groupCount = Math.ceil(totalPeople / groupSize)

  const statusFor = (id) => {
    if (sickSet.has(id)) return 'sick'
    if (snowSet.has(id)) return 'snow'
    return 'available'
  }

  const colorFor = (status) => WORKFORCE_SLOT_COLORS[status]

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-text">Simulated workforce</h3>
          <p className="text-xs text-text-muted">
            {totalPeople} anonymous worker slots · shown in groups of {groupSize} (people per crew).
            Deployable crews = FLOOR(usable ÷ {groupSize}).
          </p>
        </div>
        <ul className="flex flex-wrap items-center gap-3 text-xs text-text-muted">
          <li className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ backgroundColor: WORKFORCE_SLOT_COLORS.available }}
              aria-hidden="true"
            />
            Available
          </li>
          <li className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ backgroundColor: WORKFORCE_SLOT_COLORS.sick }}
              aria-hidden="true"
            />
            Sick
          </li>
          <li className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ backgroundColor: WORKFORCE_SLOT_COLORS.snow }}
              aria-hidden="true"
            />
            Snow redeployed
          </li>
        </ul>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-5 xl:grid-cols-5">
        {Array.from({ length: groupCount }, (_, groupIndex) => {
          const start = groupIndex * groupSize + 1
          const ids = []
          for (let id = start; id < start + groupSize && id <= totalPeople; id += 1) {
            ids.push(id)
          }
          return (
            <div key={groupIndex} className="rounded-md border border-border bg-white px-2 py-1.5">
              <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-text-muted">
                Group {groupIndex + 1}
              </div>
              <div className="flex gap-1">
                {ids.map((id) => {
                  const status = statusFor(id)
                  return (
                    <span
                      key={id}
                      title={`Worker ${id} — ${status}`}
                      aria-label={`Worker ${id}, ${status}`}
                      className="inline-block h-3.5 w-3.5 rounded-sm border border-black/10"
                      style={{ backgroundColor: colorFor(status) }}
                    />
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default WorkforceGrid
