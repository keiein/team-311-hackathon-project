// Shared operational workforce (public/data/workforce.json).
// Written by backend/export_team_scores.py and updated by make_dispatch_standin.py.
// Values come from MySQL workforce when available, else scoring/schema.sql placeholders.
// React must NOT recalculate available_people / available_crews.

const URL = `${import.meta.env.BASE_URL}data/workforce.json`

let cached = null

export function loadWorkforce() {
  if (!cached) {
    cached = fetch(URL)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.json()
      })
      .then((data) => {
        if (!data?.workforce) throw new Error('workforce.json is missing workforce')
        return {
          workforce: data.workforce,
          scenarios: data.scenarios ?? {},
          afterNoon: data.afterNoon ?? null,
          rules: data.rules ?? [],
        }
      })
      .catch((error) => {
        cached = null
        throw error
      })
  }
  return cached
}
