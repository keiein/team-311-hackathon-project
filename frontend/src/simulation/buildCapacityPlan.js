/**
 * Build a dispatch plan from ranked tickets and shared workforce capacity.
 *
 * Two separate decisions:
 *   PRIORITY  — which jobs make today's plan (top daily_job_capacity by priority_rank)
 *   GEOGRAPHY — how those already-selected jobs are grouped into crews
 *
 * - available_crews = FLOOR(usable_people / people_per_crew)
 * - daily_job_capacity = available_crews * jobs_per_crew
 * - Take the top daily_job_capacity tickets by priority_rank
 * - Group selected tickets greedily so each crew's up-to-5 stops are close together
 * - busy_people = available_crews * people_per_crew  (same 5 people do up to 5 jobs)
 */

import { DEFAULT_JOBS_PER_CREW } from './dispatchConfig.js'

const EARTH_RADIUS_KM = 6371

export function usablePeople(totalPeople, sickPeople, snowRedeployed) {
  return Math.max(0, totalPeople - sickPeople - snowRedeployed)
}

export function availableCrews(totalPeople, sickPeople, snowRedeployed, peoplePerCrew) {
  if (peoplePerCrew <= 0) return 0
  return Math.floor(usablePeople(totalPeople, sickPeople, snowRedeployed) / peoplePerCrew)
}

/** @deprecated use availableCrews — kept name for older imports */
export function planCapacity(totalPeople, sickPeople, snowRedeployed, peoplePerCrew) {
  return availableCrews(totalPeople, sickPeople, snowRedeployed, peoplePerCrew)
}

export function dailyJobCapacity(crewCount, jobsPerCrew) {
  return Math.max(0, crewCount) * Math.max(0, jobsPerCrew)
}

export function hasCoordinates(ticket) {
  const lon = Number(ticket?.longitude)
  const lat = Number(ticket?.latitude)
  return Number.isFinite(lon) && Number.isFinite(lat)
}

/** Straight-line distance in km (Haversine). */
export function kmBetween(a, b) {
  const lon1 = Number(a?.longitude)
  const lat1 = Number(a?.latitude)
  const lon2 = Number(b?.longitude)
  const lat2 = Number(b?.latitude)
  if (![lon1, lat1, lon2, lat2].every(Number.isFinite)) return Number.POSITIVE_INFINITY

  const toRad = (deg) => (deg * Math.PI) / 180
  const dLat = toRad(lat2 - lat1)
  const dLon = toRad(lon2 - lon1)
  const rLat1 = toRad(lat1)
  const rLat2 = toRad(lat2)
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(rLat1) * Math.cos(rLat2) * Math.sin(dLon / 2) ** 2
  return EARTH_RADIUS_KM * 2 * Math.asin(Math.min(1, Math.sqrt(h)))
}

function priorityRankOf(ticket) {
  return ticket?.priorityRank ?? Number.POSITIVE_INFINITY
}

/** Stable: lower priority_rank wins; ties break on id. */
function comparePriority(a, b) {
  const rankDiff = priorityRankOf(a) - priorityRankOf(b)
  if (rankDiff !== 0) return rankDiff
  return String(a?.id ?? '').localeCompare(String(b?.id ?? ''))
}

function pickHighestPriority(tickets) {
  let best = null
  for (const ticket of tickets) {
    if (best == null || comparePriority(ticket, best) < 0) best = ticket
  }
  return best
}

/**
 * Among remaining geocoded tickets, pick the nearest to `anchor`.
 * Ties: closer first, then higher priority (lower rank), then id.
 */
function pickNearestTo(anchor, tickets) {
  let best = null
  let bestKm = Number.POSITIVE_INFINITY
  for (const ticket of tickets) {
    if (!hasCoordinates(ticket)) continue
    const km = kmBetween(anchor, ticket)
    if (
      best == null ||
      km < bestKm - 1e-9 ||
      (Math.abs(km - bestKm) <= 1e-9 && comparePriority(ticket, best) < 0)
    ) {
      best = ticket
      bestKm = km
    }
  }
  return best
}

function lastGeocodedStop(stops) {
  for (let i = stops.length - 1; i >= 0; i -= 1) {
    if (hasCoordinates(stops[i])) return stops[i]
  }
  return null
}

function removeTicket(list, ticket) {
  const index = list.indexOf(ticket)
  if (index >= 0) list.splice(index, 1)
}

/**
 * Geographic grouping for tickets that were ALREADY selected by priority.
 *
 * Algorithm (greedy, explainable):
 * 1. Start every crew with the highest-priority remaining selected ticket (seed).
 * 2. Grow that crew up to jobsPerCrew by repeatedly appending the remaining
 *    selected ticket nearest (Haversine) to the crew's latest geocoded stop.
 * 3. If the crew has no coordinate anchor yet, or no remaining geocoded tickets,
 *    fall back to the highest-priority remaining selected ticket (covers missing coords).
 * 4. Start the next crew the same way until every selected ticket is assigned.
 *
 * Geography never changes the selected set — only how it is divided among crews.
 */
export function assignTicketsToCrews(rankedTickets, crewCount, jobsPerCrew) {
  const morning = []
  const crewNames = []
  const remaining = [...rankedTickets]

  for (let crewIndex = 0; crewIndex < crewCount; crewIndex += 1) {
    if (remaining.length === 0) break

    const crewName = `Crew ${crewIndex + 1}`
    crewNames.push(crewName)

    const crewStops = []
    const stopReasons = []

    const seed = pickHighestPriority(remaining)
    removeTicket(remaining, seed)
    crewStops.push(seed)
    stopReasons.push(`Priority rank ${seed.priorityRank} seeded ${crewName}`)

    while (crewStops.length < jobsPerCrew && remaining.length > 0) {
      const anchor = lastGeocodedStop(crewStops)
      let next = null
      let whyDetail = ''

      if (anchor) {
        next = pickNearestTo(anchor, remaining)
        if (next) {
          const km = kmBetween(anchor, next)
          whyDetail = `${km.toFixed(1)} km from previous stop`
        }
      }

      // No geocoded anchor yet, or only ungeocoded tickets remain.
      if (!next) {
        next = pickHighestPriority(remaining)
        whyDetail = hasCoordinates(next)
          ? 'highest-priority remaining (no geographic anchor yet)'
          : 'highest-priority remaining (no coordinates)'
      }

      removeTicket(remaining, next)
      crewStops.push(next)
      const stop = crewStops.length
      stopReasons.push(
        `Priority rank ${next.priorityRank} → ${crewName} stop ${stop} (${whyDetail})`,
      )
    }

    crewStops.forEach((ticket, index) => {
      morning.push({
        crew: crewName,
        crewKind: 'Shared',
        crewPool: ticket.crewPool ?? 'Shared Operational Workforce',
        stop: index + 1,
        id: ticket.id,
        serviceType: ticket.serviceType,
        community: ticket.community,
        priorityScore: ticket.priorityScore,
        priorityBand: ticket.priorityBand,
        daysWaiting: ticket.daysWaiting,
        assignment: 'Planned',
        movedFrom: null,
        why: stopReasons[index],
      })
    })
  }

  // Any leftover selected tickets (should only happen if crewCount * jobsPerCrew
  // was smaller than rankedTickets.length) stay unassigned by design.
  return { morning, crewNames }
}

export function buildCapacityPlan(
  tickets,
  {
    totalPeople,
    sickPeople,
    snowRedeployed,
    peoplePerCrew,
    jobsPerCrew = DEFAULT_JOBS_PER_CREW,
    asOf,
  },
) {
  const crews = availableCrews(totalPeople, sickPeople, snowRedeployed, peoplePerCrew)
  const usable = usablePeople(totalPeople, sickPeople, snowRedeployed)
  const jobSlots = dailyJobCapacity(crews, jobsPerCrew)
  const ranked = [...tickets].sort((a, b) => (a.priorityRank ?? 1e9) - (b.priorityRank ?? 1e9))
  const selected = ranked.slice(0, jobSlots)
  const deferredCount = Math.max(0, ranked.length - selected.length)

  // Same 5 people do up to jobs_per_crew jobs sequentially — count PEOPLE, not jobs.
  const busyPeople = crews * peoplePerCrew

  const { morning, crewNames } = assignTicketsToCrews(selected, crews, jobsPerCrew)
  const highPlanned = morning.filter((row) => row.priorityBand === 'High').length

  const crewSummary = crewNames.map((name) => {
    const mine = morning.filter((row) => row.crew === name)
    const communities = []
    mine.forEach((row) => {
      if (row.community && !communities.includes(row.community)) communities.push(row.community)
    })
    return {
      crew: name,
      crewKind: 'Shared',
      crewPool: 'Shared Operational Workforce',
      jobsPlanned: mine.length,
      highPlanned: mine.filter((row) => row.priorityBand === 'High').length,
      communities,
      noon: {
        status: 'Active',
        doneBeforeNoon: 0,
        stillToDo: mine.length,
        movedIn: 0,
        pushedToTomorrow: 0,
      },
    }
  })

  const assignedIds = new Set(selected.map((ticket) => ticket.id))

  return {
    workforce: {
      workforce_id: 1,
      total_people: totalPeople,
      busy_people: busyPeople,
      sick_people: sickPeople,
      snow_redeployed: snowRedeployed,
      people_per_crew: peoplePerCrew,
      jobs_per_crew: jobsPerCrew,
      available_people: usable,
      available_crews: crews,
      usable_people: usable,
      plan_capacity: crews,
      daily_job_capacity: jobSlots,
      isSimulatedPlaceholder: true,
    },
    assignedIds,
    deferredCount,
    dispatch: {
      summary: {
        asOf: asOf ?? null,
        crewCount: crews,
        jobsPerCrew,
        peoplePerCrew,
        dailyJobCapacity: jobSlots,
        plannedJobs: morning.length,
        poolSize: ranked.length,
        waitingJobs: deferredCount,
        morning: { highPriorityPlanned: highPlanned },
        noon: {
          missingCrew: null,
          moved: 0,
          pushed: deferredCount,
          urgentStillCovered: highPlanned,
        },
        isStandIn: true,
        livePlan: true,
        workforceModel: 'shared',
        disruptions: { sickPeople, snowRedeployed },
      },
      crews: crewNames,
      crewSummary,
      morning,
      noon: morning,
    },
  }
}
