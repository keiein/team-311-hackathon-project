// The ONE place that loads today's open crew jobs.
// The Requests table and the Dashboard map both use it, so they always show the same numbers
// and the 3 MB file is downloaded only once.
//
// The file is public/data/requests.geojson, made by backend/export_team_scores.py from the team
// scorer (scoring/priority_score.py). Each feature's `properties` holds one job:
//   id, serviceType, priorityScore (0-100), priorityBand (High | Medium | Low), priorityRank,
//   severityName (Critical | Major | Moderate | Minor), severityWhy, crew, crewPool, community,
//   status, daysWaiting, slaDays, overdue, sameDayTickets,
//   basicKnowledgeScore, geoScore, ageScore, ticketCountScore (the four parts, each 0 to 1)
// The file's `meta` holds asOf, formula, weights (how much each part counts) and levels.

const REQUESTS_URL = `${import.meta.env.BASE_URL}data/requests.geojson`

let cached = null

// The whole file (points with their properties): the map needs this
export function loadRequestsCollection() {
  if (!cached) {
    cached = fetch(REQUESTS_URL)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.json()
      })
      .catch((error) => {
        cached = null // allow a retry after a failure
        throw error
      })
  }
  return cached
}

// Just the rows (one plain object per job): the table needs this
export function loadRequests() {
  return loadRequestsCollection().then((collection) => collection.features.map((feature) => ({ ...feature.properties })))
}

// Information about the whole file: the formula and the weight of each part
export function loadRequestsMeta() {
  return loadRequestsCollection().then((collection) => collection.meta ?? {})
}
