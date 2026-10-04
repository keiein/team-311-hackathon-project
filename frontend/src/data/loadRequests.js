// The ONE place that loads today's open crew jobs.
// The Requests table uses it now; the Dashboard map can use it later, so both always show
// the same numbers.
//
// The file is public/data/requests.geojson, made by backend/export_map_data.py.
// Each feature's `properties` holds one job:
//   id, serviceType, priorityScore (0-100), priorityBand (High | Medium | Low),
//   severityName (Critical | Major | Moderate | Minor), crew, community, status,
//   daysWaiting, locationNote

const REQUESTS_URL = `${import.meta.env.BASE_URL}data/requests.geojson`

// Keep the download so the table and the map do not each fetch a 3 MB file.
let cached = null

export function loadRequests() {
  if (!cached) {
    cached = fetch(REQUESTS_URL)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.json()
      })
      .then((collection) => collection.features.map((feature) => ({ ...feature.properties })))
      .catch((error) => {
        cached = null // allow a retry after a failure
        throw error
      })
  }
  return cached
}
