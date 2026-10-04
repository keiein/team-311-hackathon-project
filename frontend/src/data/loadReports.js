// The ONE place that loads the Reports data.
//
// The file is public/data/reports.json. It has this shape:
//   summary     asOf, isStandIn, crewCount, jobsPerCrew, plannedJobs, poolSize
//   headline    3 items: { label, ourPlan, oldestFirst, note }
//   comparison  rows: { label, oldestFirst, ourPlan, betterIs ("higher" | "lower"), winner }
//   loop        { setting, qualityFormula, stoppedBecause, tries: [ { try, setting, highPlanned,
//                 avgPriority, kmPerCrew, quality, note } ] }
//   noon        { missingCrew, moved, pushed, urgentStillCovered }
//   limits      plain sentences
//
// This page only shows what is in the file. It never works out a number itself.

const REPORTS_URL = `${import.meta.env.BASE_URL}data/reports.json`

let cached = null

export function loadReports() {
  if (!cached) {
    cached = fetch(REPORTS_URL)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.json()
      })
      .then((data) => {
        if (!data.summary || !Array.isArray(data.comparison) || !data.loop || !Array.isArray(data.loop.tries)) {
          throw new Error('reports.json is missing summary, comparison or loop')
        }
        return {
          ...data,
          headline: data.headline ?? [],
          limits: data.limits ?? [],
          noon: data.noon ?? {},
        }
      })
      .catch((error) => {
        cached = null // allow a retry after a failure
        throw error
      })
  }
  return cached
}
