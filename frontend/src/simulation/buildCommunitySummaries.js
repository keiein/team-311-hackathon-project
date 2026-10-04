/**
 * Community today's-work summaries from the CURRENT dispatch plan only.
 * Join: ticket/assignment community name ↔ polygon properties.name (normalized).
 */

import { colorForCrew, parseCrewNumber } from './crewColors.js'
import { colorForCommunity, normalizeCommunityName } from './communityColors.js'

/**
 * @returns {Map<string, {
 *   key: string,
 *   name: string,
 *   totalJobs: number,
 *   activeCrews: number,
 *   jobsByCrew: Array<{ crew: string, crewNumber: number|null, jobs: number, color: string }>,
 *   highestPriority: null | { id, serviceType, priorityRank, priorityScore },
 *   color: string,
 * }>}
 */
export function buildCommunitySummaries(dispatch, requestsCollection) {
  const byId = new Map()
  for (const feature of requestsCollection?.features ?? []) {
    const id = feature?.properties?.id
    if (id != null) byId.set(String(id), feature.properties)
  }

  const buckets = new Map()

  for (const row of dispatch?.morning ?? []) {
    const props = byId.get(String(row.id))
    const name = row.community || props?.community
    const key = normalizeCommunityName(name)
    if (!key) continue

    if (!buckets.has(key)) {
      buckets.set(key, {
        key,
        name: String(name).trim(),
        jobs: [],
        byCrew: new Map(),
      })
    }
    const bucket = buckets.get(key)
    const priorityRank = props?.priorityRank ?? null
    const priorityScore = props?.priorityScore ?? row.priorityScore ?? null
    bucket.jobs.push({
      id: row.id,
      crew: row.crew,
      serviceType: row.serviceType || props?.serviceType,
      priorityRank,
      priorityScore,
    })
    bucket.byCrew.set(row.crew, (bucket.byCrew.get(row.crew) ?? 0) + 1)
  }

  const summaries = new Map()
  for (const bucket of buckets.values()) {
    const jobsByCrew = [...bucket.byCrew.entries()]
      .map(([crew, jobs]) => {
        const crewNumber = parseCrewNumber(crew)
        return { crew, crewNumber, jobs, color: colorForCrew(crewNumber) }
      })
      .sort((a, b) => (a.crewNumber ?? 99) - (b.crewNumber ?? 99))

    let highestPriority = null
    for (const job of bucket.jobs) {
      if (job.priorityRank == null) continue
      if (!highestPriority || job.priorityRank < highestPriority.priorityRank) {
        highestPriority = {
          id: job.id,
          serviceType: job.serviceType,
          priorityRank: job.priorityRank,
          priorityScore: job.priorityScore,
        }
      }
    }

    summaries.set(bucket.key, {
      key: bucket.key,
      name: bucket.name,
      totalJobs: bucket.jobs.length,
      activeCrews: jobsByCrew.length,
      jobsByCrew,
      highestPriority,
      color: colorForCommunity({ name: bucket.name }),
      ticketIds: bucket.jobs.map((j) => String(j.id)),
    })
  }

  return summaries
}

/** Legend rows: communities that currently have today's assigned jobs. */
export function communityLegendFromSummaries(summaries) {
  return [...summaries.values()]
    .sort((a, b) => b.totalJobs - a.totalJobs || a.name.localeCompare(b.name))
    .map((s) => ({
      key: s.key,
      name: s.name,
      color: s.color,
      jobs: s.totalJobs,
      crews: s.activeCrews,
    }))
}

/** Attach soft fill colors (and optional today's counts) onto community polygons. */
export function enrichCommunitiesGeoJSON(communitiesCollection, summaries) {
  if (!communitiesCollection?.features) {
    return { type: 'FeatureCollection', features: [] }
  }
  return {
    type: 'FeatureCollection',
    features: communitiesCollection.features.map((feature) => {
      const name = feature.properties?.name
      const code = feature.properties?.code
      const key = normalizeCommunityName(name)
      const summary = summaries?.get(key)
      return {
        ...feature,
        id: code || key,
        properties: {
          ...feature.properties,
          communityColor: colorForCommunity({ code, name }),
          todaysJobs: summary?.totalJobs ?? 0,
          todaysCrews: summary?.activeCrews ?? 0,
        },
      }
    }),
  }
}
