/**
 * Join the live dispatch plan to request coordinates for the Today's Jobs map layer.
 */

import { colorForCrew, parseCrewNumber } from './crewColors.js'

const EMPTY = { type: 'FeatureCollection', features: [] }

export function buildTodaysJobsGeoJSON(dispatch, requestsCollection) {
  if (!dispatch?.morning?.length || !requestsCollection?.features?.length) return EMPTY

  const byId = new Map()
  for (const feature of requestsCollection.features) {
    const id = feature?.properties?.id
    if (id != null) byId.set(String(id), feature)
  }

  // Jobs per crew (for stop "of N" in popups)
  const stopsPerCrew = new Map()
  for (const row of dispatch.morning) {
    stopsPerCrew.set(row.crew, (stopsPerCrew.get(row.crew) ?? 0) + 1)
  }

  const features = []
  for (const row of dispatch.morning) {
    const source = byId.get(String(row.id))
    if (!source?.geometry?.coordinates) continue

    const crewNumber = parseCrewNumber(row.crew)
    const stopTotal = stopsPerCrew.get(row.crew) ?? row.stop
    features.push({
      type: 'Feature',
      geometry: source.geometry,
      properties: {
        service_request_id: row.id,
        id: row.id,
        crew_id: row.crew,
        crew: row.crew,
        crewNumber,
        crew_number: crewNumber,
        stop_number: row.stop,
        stopNumber: row.stop,
        stopTotal,
        crewColor: colorForCrew(crewNumber),
        priority_rank: source.properties.priorityRank ?? null,
        priorityRank: source.properties.priorityRank ?? null,
        priority: source.properties.priorityScore ?? row.priorityScore,
        priorityScore: source.properties.priorityScore ?? row.priorityScore,
        priorityBand: row.priorityBand ?? source.properties.priorityBand,
        service_name: row.serviceType ?? source.properties.serviceType,
        serviceType: row.serviceType ?? source.properties.serviceType,
        community: row.community ?? source.properties.community,
        daysWaiting: row.daysWaiting ?? source.properties.daysWaiting,
        severityName: source.properties.severityName,
      },
    })
  }

  return { type: 'FeatureCollection', features }
}

/** Legend rows from the current plan: [{ crew, crewNumber, color, jobs }] */
export function crewLegendFromDispatch(dispatch) {
  if (!dispatch?.crewSummary?.length && !dispatch?.morning?.length) return []

  if (dispatch.crewSummary?.length) {
    return dispatch.crewSummary.map((row) => {
      const crewNumber = parseCrewNumber(row.crew)
      return {
        crew: row.crew,
        crewNumber,
        color: colorForCrew(crewNumber),
        jobs: row.jobsPlanned ?? 0,
      }
    })
  }

  const counts = new Map()
  for (const row of dispatch.morning) {
    counts.set(row.crew, (counts.get(row.crew) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([crew, jobs]) => {
      const crewNumber = parseCrewNumber(crew)
      return { crew, crewNumber, color: colorForCrew(crewNumber), jobs }
    })
    .sort((a, b) => (a.crewNumber ?? 0) - (b.crewNumber ?? 0))
}
