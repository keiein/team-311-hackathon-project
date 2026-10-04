// Loads Alvin's crew_pool table (public/data/crew_pools.json), next to today's jobs per pool.
// Shape: { isPlaceholder, source, note, pools: [ { pool, crew, people, openJobs, highPriorityJobs } ] }
// The headcounts are PLACEHOLDERS (scoring/schema.sql draws them at random), not real staffing.

const URL = `${import.meta.env.BASE_URL}data/crew_pools.json`

let cached = null

export function loadCrewPools() {
  if (!cached) {
    cached = fetch(URL)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.json()
      })
      .then((data) => ({ ...data, pools: data.pools ?? [] }))
      .catch((error) => {
        cached = null
        throw error
      })
  }
  return cached
}
