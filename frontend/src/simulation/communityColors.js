/**
 * Soft, deterministic community polygon fills.
 * Distinct from strong crew marker colors — translucent pastel palette.
 */

export const COMMUNITY_COLOR_PALETTE = [
  '#93c5fd', // soft blue
  '#86efac', // soft green
  '#fcd34d', // soft amber
  '#f9a8d4', // soft pink
  '#c4b5fd', // soft violet
  '#67e8f9', // soft cyan
  '#fdba74', // soft orange
  '#a5b4fc', // soft indigo
  '#bef264', // soft lime
  '#fca5a5', // soft red
  '#5eead4', // soft teal
  '#d8b4fe', // soft purple
  '#fde68a', // soft yellow
  '#7dd3fc', // sky
  '#bbf7d0', // mint
  '#fecdd3', // rose
  '#ddd6fe', // lavender
  '#a7f3d0', // emerald tint
  '#fed7aa', // peach
  '#bae6fd', // light sky
  '#e9d5ff', // light purple
  '#fef08a', // light yellow
  '#99f6e4', // aqua
  '#fecaca', // light coral
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
