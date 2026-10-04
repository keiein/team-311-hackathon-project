/**
 * Build a dispatch plan from ranked tickets and shared workforce capacity.
 * One deployable crew takes exactly one ticket (highest priority_rank first).
 */

export function usablePeople(totalPeople, sickPeople, snowRedeployed) {
  return Math.max(0, totalPeople - sickPeople - snowRedeployed)
}

export function planCapacity(totalPeople, sickPeople, snowRedeployed, peoplePerCrew) {
  if (peoplePerCrew <= 0) return 0
  return Math.floor(usablePeople(totalPeople, sickPeople, snowRedeployed) / peoplePerCrew)
}

export function buildCapacityPlan(tickets, { totalPeople, sickPeople, snowRedeployed, peoplePerCrew, asOf }) {
  const capacity = planCapacity(totalPeople, sickPeople, snowRedeployed, peoplePerCrew)
  const usable = usablePeople(totalPeople, sickPeople, snowRedeployed)
  const ranked = [...tickets].sort((a, b) => (a.priorityRank ?? 1e9) - (b.priorityRank ?? 1e9))
  const assigned = ranked.slice(0, capacity)
  const deferredCount = Math.max(0, ranked.length - assigned.length)
  const busyPeople = assigned.length * peoplePerCrew

  const morning = assigned.map((ticket, index) => ({
    crew: `Crew ${index + 1}`,
    crewKind: 'Shared',
    crewPool: ticket.crewPool ?? 'Shared Operational Workforce',
    stop: 1,
    id: ticket.id,
    serviceType: ticket.serviceType,
    community: ticket.community,
    priorityScore: ticket.priorityScore,
    priorityBand: ticket.priorityBand,
    daysWaiting: ticket.daysWaiting,
    assignment: 'Planned',
    movedFrom: null,
    why: `Priority rank ${ticket.priorityRank} (shared workforce)`,
  }))

  const crews = morning.map((row) => row.crew)
  const highPlanned = morning.filter((row) => row.priorityBand === 'High').length

  const crewSummary = morning.map((row) => ({
    crew: row.crew,
    crewKind: 'Shared',
    crewPool: 'Shared Operational Workforce',
    jobsPlanned: 1,
    highPlanned: row.priorityBand === 'High' ? 1 : 0,
    communities: row.community ? [row.community] : [],
    noon: {
      status: 'Active',
      doneBeforeNoon: 0,
      stillToDo: 1,
      movedIn: 0,
      pushedToTomorrow: 0,
    },
  }))

  const assignedIds = new Set(assigned.map((ticket) => ticket.id))

  return {
    workforce: {
      workforce_id: 1,
      total_people: totalPeople,
      busy_people: busyPeople,
      sick_people: sickPeople,
      snow_redeployed: snowRedeployed,
      people_per_crew: peoplePerCrew,
      available_people: usable,
      available_crews: capacity,
      usable_people: usable,
      plan_capacity: capacity,
      isSimulatedPlaceholder: true,
    },
    assignedIds,
    deferredCount,
    dispatch: {
      summary: {
        asOf: asOf ?? null,
        crewCount: capacity,
        jobsPerCrew: 1,
        peoplePerCrew,
        plannedJobs: assigned.length,
        poolSize: ranked.length,
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
      crews,
      crewSummary,
      morning,
      // Live capacity plan has no separate noon replan; keep shape for DispatchTable.
      noon: morning,
    },
  }
}
