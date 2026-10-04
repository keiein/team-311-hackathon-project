// The ONE place that loads today's dispatch plan.
//
// The file is public/data/dispatch.json. It has this shape:
//   summary  asOf, crewCount, jobsPerCrew, plannedJobs, poolSize,
//            morning { highPriorityPlanned },
//            noon { missingCrew, moved, pushed, urgentStillCovered },
//            isStandIn (true while the plan is a preview, not the final algorithm output)
//   crews    the crew names, in display order
//   morning  one row per assignment: the 8 a.m. plan
//   noon     one row per assignment: the plan after the missing crew's jobs are re-planned
//
// Each row: crew, crewKind, stop, id, serviceType, community, priorityScore, priorityBand,
//           daysWaiting, assignment, movedFrom, why
//
// This page only shows what is in the file. It never works out a score or a plan itself.

const DISPATCH_URL = `${import.meta.env.BASE_URL}data/dispatch.json`

let cached = null

export function loadDispatch() {
  if (!cached) {
    cached = fetch(DISPATCH_URL)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.json()
      })
      .then((data) => {
        if (!data.summary || !Array.isArray(data.morning) || !Array.isArray(data.noon)) {
          throw new Error('dispatch.json is missing summary, morning or noon')
        }
        return { ...data, crews: data.crews ?? [] }
      })
      .catch((error) => {
        cached = null // allow a retry after a failure
        throw error
      })
  }
  return cached
}
