/**
 * Soft, deterministic community polygon fills.
 * Distinct from strong crew marker colors — muted pastel palette (readable on the map).
 */

export const COMMUNITY_COLOR_PALETTE = [
  '#60a5fa', // blue
  '#4ade80', // green
  '#fbbf24', // amber
  '#f472b6', // pink
  '#a78bfa', // violet
  '#22d3ee', // cyan
  '#fb923c', // orange
  '#818cf8', // indigo
  '#a3e635', // lime
  '#f87171', // red
  '#2dd4bf', // teal
  '#c084fc', // purple
  '#facc15', // yellow
  '#38bdf8', // sky
  '#86efac', // mint
  '#fb7185', // rose
  '#c4b5fd', // lavender
  '#34d399', // emerald
  '#fdba74', // peach
  '#7dd3fc', // light sky
  '#d8b4fe', // light purple
  '#fde047', // light yellow
  '#5eead4', // aqua
  '#fca5a5', // coral
]

function hashString(value) {
  const s = String(value ?? '')
  let h = 2166136261
  for (let i = 0; i < s.length; i += 1) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

/** Prefer stable community code; fall back to name. */
export function colorForCommunity({ code, name }) {
  const key = String(code || name || '').trim().toUpperCase()
  if (!key) return '#d4d4d4'
  return COMMUNITY_COLOR_PALETTE[hashString(key) % COMMUNITY_COLOR_PALETTE.length]
}

export function normalizeCommunityName(name) {
  return String(name ?? '')
    .trim()
    .toUpperCase()
    .replace(/\s+/g, ' ')
}
