// Loads the crew jobs that have been open over 60 days (public/data/needs_review.json).
// The team scorer leaves these out of today's queue on purpose: many were fixed but never closed,
// so a supervisor checks them before sending a crew.
// Shape: { asOf, count, note, rows: [ { id, serviceType, community, daysWaiting, severityTier,
//          severityName, crew } ] }   rows are already sorted: most dangerous type first, then oldest.

const URL = `${import.meta.env.BASE_URL}data/needs_review.json`

let cached = null

export function loadNeedsReview() {
  if (!cached) {
    cached = fetch(URL)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.json()
      })
      .then((data) => ({ ...data, rows: data.rows ?? [] }))
      .catch((error) => {
        cached = null
        throw error
      })
  }
  return cached
}
