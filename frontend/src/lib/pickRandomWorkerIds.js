/**
 * Pick `count` unique worker slot ids from 1..totalPeople, excluding any in `excludeIds`.
 * Used once when a disruption is activated so the selection stays stable across renders.
 */
export function pickRandomWorkerIds(totalPeople, count, excludeIds = []) {
  const exclude = new Set(excludeIds)
  const pool = []
  for (let id = 1; id <= totalPeople; id += 1) {
    if (!exclude.has(id)) pool.push(id)
  }

  const n = Math.max(0, Math.min(count, pool.length))
  for (let i = 0; i < n; i += 1) {
    const j = i + Math.floor(Math.random() * (pool.length - i))
    const tmp = pool[i]
    pool[i] = pool[j]
    pool[j] = tmp
  }
  return pool.slice(0, n).sort((a, b) => a - b)
}
