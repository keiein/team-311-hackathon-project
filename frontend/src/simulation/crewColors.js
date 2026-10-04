/**
 * Deterministic crew colors for Today's Jobs map markers.
 * Index 0 unused; crew numbers 1..20 map to fixed palette entries.
 * Same crew number → same color across renders, navigation, and replans.
 */

export const CREW_COLOR_PALETTE = [
  '#2563eb', // 1 blue
  '#dc2626', // 2 red
  '#16a34a', // 3 green
  '#ca8a04', // 4 gold
  '#9333ea', // 5 purple
  '#0891b2', // 6 cyan
  '#ea580c', // 7 orange
  '#db2777', // 8 pink
  '#4f46e5', // 9 indigo
  '#0d9488', // 10 teal
  '#b45309', // 11 amber-brown
  '#65a30d', // 12 lime
  '#e11d48', // 13 rose
  '#0284c7', // 14 sky
  '#7c3aed', // 15 violet
  '#c2410c', // 16 deep orange
  '#15803d', // 17 forest
  '#be123c', // 18 crimson
  '#1d4ed8', // 19 royal
  '#a16207', // 20 olive-gold
]

const FALLBACK = '#525252'

/** @param {number} crewNumber 1-based */
export function colorForCrew(crewNumber) {
  const n = Number(crewNumber)
  if (!Number.isFinite(n) || n < 1) return FALLBACK
  return CREW_COLOR_PALETTE[(n - 1) % CREW_COLOR_PALETTE.length]
}

/** Parse "Crew 12" → 12 */
export function parseCrewNumber(crewName) {
  const match = String(crewName ?? '').match(/(\d+)\s*$/)
  return match ? Number(match[1]) : null
}

/**
 * Mapbox match expression: property crewNumber → color.
 * Built from the fixed palette so styling stays data-driven in one layer.
 */
export function mapboxCrewColorExpression(property = 'crewNumber') {
  const expr = ['match', ['coalesce', ['get', property], 0]]
  CREW_COLOR_PALETTE.forEach((color, index) => {
    expr.push(index + 1, color)
  })
  expr.push(FALLBACK)
  return expr
}
