/**
 * MAP-ONLY visual priority colors for 311 request markers.
 *
 * These thresholds do NOT affect priorityScore, priority_rank, dispatch,
 * crew assignment, or Today's Jobs crew colors.
 *
 * Display buckets (user-specified):
 *   Standard (green)  — priorityScore < 78
 *   Elevated (orange) — 78 ≤ score < 91  (i.e. 78–90)
 *   High (red)        — score ≥ 91
 */

export const REQUEST_PRIORITY_COLORS = {
  high: '#c8102e', // Calgary red
  elevated: '#f59e0b', // amber
  standard: '#22c55e', // green
}

/** Inclusive lower bounds for elevated / high visual buckets. */
export const REQUEST_PRIORITY_VISUAL_THRESHOLDS = {
  elevatedMin: 78,
  highMin: 91,
}

export const REQUEST_PRIORITY_LEGEND = [
  { id: 'high', label: 'High', color: REQUEST_PRIORITY_COLORS.high },
  { id: 'elevated', label: 'Elevated', color: REQUEST_PRIORITY_COLORS.elevated },
  { id: 'standard', label: 'Standard', color: REQUEST_PRIORITY_COLORS.standard },
]

/** Filter dropdown values (visual categories, not scoring bands). */
export const REQUEST_PRIORITY_FILTER_OPTIONS = ['High', 'Elevated', 'Standard']

export function visualPriorityCategory(priorityScore) {
  const score = Number(priorityScore)
  if (!Number.isFinite(score)) return 'Standard'
  if (score >= REQUEST_PRIORITY_VISUAL_THRESHOLDS.highMin) return 'High'
  if (score >= REQUEST_PRIORITY_VISUAL_THRESHOLDS.elevatedMin) return 'Elevated'
  return 'Standard'
}

/** Mapbox step expression for requests-circle fill. */
export function mapboxRequestPriorityColorExpression(scoreProperty = 'priorityScore') {
  const { elevatedMin, highMin } = REQUEST_PRIORITY_VISUAL_THRESHOLDS
  const { standard, elevated, high } = REQUEST_PRIORITY_COLORS
  return [
    'step',
    ['coalesce', ['get', scoreProperty], 0],
    standard,
    elevatedMin,
    elevated,
    highMin,
    high,
  ]
}
