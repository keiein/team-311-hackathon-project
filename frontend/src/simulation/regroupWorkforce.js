/**
 * Visual regrouping of the SAME anonymous worker slots after disruptions.
 * Does not change capacity math — deployable crew count still comes from
 * FLOOR(usable_people / people_per_crew) in buildCapacityPlan.
 */

export function listAvailableWorkerIds(totalPeople, sickWorkerIds = [], snowRedeployedWorkerIds = []) {
  const sick = new Set(sickWorkerIds)
  const snow = new Set(snowRedeployedWorkerIds)
  const available = []
  for (let id = 1; id <= totalPeople; id += 1) {
    if (!sick.has(id) && !snow.has(id)) available.push(id)
  }
  return available
}

/**
 * Chunk available workers into complete crews of peoplePerCrew.
 * Leftover people become reserve (not a partial crew).
 *
 * Crew names match Dispatch: "Crew 1" .. "Crew N".
 */
export function regroupAvailableWorkers(availableWorkerIds, peoplePerCrew = 5) {
  const size = Math.max(1, peoplePerCrew)
  const crews = []
  let offset = 0
  while (offset + size <= availableWorkerIds.length) {
    const workerIds = availableWorkerIds.slice(offset, offset + size)
    crews.push({
      name: `Crew ${crews.length + 1}`,
      workerIds,
    })
    offset += size
  }
  return {
    crews,
    reserveWorkerIds: availableWorkerIds.slice(offset),
    deployableCrews: crews.length,
    reservePeople: availableWorkerIds.length - offset,
  }
}
