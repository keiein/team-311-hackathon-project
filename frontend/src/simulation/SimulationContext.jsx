import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { loadRequests, loadRequestsMeta } from '../data/loadRequests'
import { loadWorkforce } from '../data/loadWorkforce'
import { randomIntInclusive } from '../lib/randomIntInclusive'
import { buildCapacityPlan } from './buildCapacityPlan'

const SimulationContext = createContext(null)

const SICK_MIN = 0
const SICK_MAX = 10
const SNOW_MIN = 20
const SNOW_MAX = 35

function baselineFromWorkforceFile(data) {
  const normal = data?.scenarios?.normal
  const row = normal ?? data?.workforce
  return {
    totalPeople: Number(row?.total_people ?? 100),
    peoplePerCrew: Number(row?.people_per_crew ?? 5),
    source: row?.source ?? 'workforce.json',
    note: row?.note ?? '',
    rules: data?.rules ?? [],
  }
}

export function SimulationProvider({ children }) {
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)
  const [baseline, setBaseline] = useState(null)
  const [tickets, setTickets] = useState([])
  const [asOf, setAsOf] = useState(null)

  // Disruption toggles: values are stable while active; regenerated only on re-activation.
  const [sick, setSick] = useState({ active: false, people: 0 })
  const [blizzard, setBlizzard] = useState({ active: false, people: 0 })

  useEffect(() => {
    let active = true
    Promise.all([loadWorkforce(), loadRequests(), loadRequestsMeta()])
      .then(([workforceFile, rows, meta]) => {
        if (!active) return
        setBaseline(baselineFromWorkforceFile(workforceFile))
        setTickets(rows)
        setAsOf(meta?.asOf ?? null)
        setStatus('ready')
      })
      .catch((err) => {
        if (!active) return
        setError(err)
        setStatus('error')
      })
    return () => {
      active = false
    }
  }, [])

  const toggleSick = useCallback(() => {
    setSick((current) =>
      current.active
        ? { active: false, people: 0 }
        : { active: true, people: randomIntInclusive(SICK_MIN, SICK_MAX) },
    )
  }, [])

  const toggleBlizzard = useCallback(() => {
    setBlizzard((current) =>
      current.active
        ? { active: false, people: 0 }
        : { active: true, people: randomIntInclusive(SNOW_MIN, SNOW_MAX) },
    )
  }, [])

  const sickActive = sick.active
  const sickPeople = sick.active ? sick.people : 0
  const blizzardActive = blizzard.active
  const snowRedeployed = blizzard.active ? blizzard.people : 0

  const planBundle = useMemo(() => {
    if (status !== 'ready' || !baseline) return null
    return buildCapacityPlan(tickets, {
      totalPeople: baseline.totalPeople,
      sickPeople,
      snowRedeployed,
      peoplePerCrew: baseline.peoplePerCrew,
      asOf,
    })
  }, [status, baseline, tickets, sickPeople, snowRedeployed, asOf])

  const requestRows = useMemo(() => {
    if (!planBundle) return tickets
    const crewById = new Map(planBundle.dispatch.morning.map((job) => [job.id, job.crew]))
    return tickets.map((row) => ({
      ...row,
      planStatus: planBundle.assignedIds.has(row.id) ? 'Assigned' : 'Waiting',
      assignedCrew: crewById.get(row.id) ?? null,
    }))
  }, [tickets, planBundle])

  const value = useMemo(() => {
    const sick = sickActive ? sickPeople : 0
    const snow = blizzardActive ? snowRedeployed : 0
    return {
      status,
      error,
      baseline,
      asOf,
      sickActive,
      sickPeople: sick,
      blizzardActive,
      snowRedeployed: snow,
      sickLabel: sickActive ? `Sick Call (${sick})` : 'Sick Call',
      blizzardLabel: blizzardActive ? `Blizzard (+${snow} snow)` : 'Blizzard',
      toggleSick,
      toggleBlizzard,
      workforce: planBundle?.workforce ?? null,
      dispatch: planBundle?.dispatch ?? null,
      deferredCount: planBundle?.deferredCount ?? 0,
      requestRows,
      rules: baseline?.rules ?? [],
      source: baseline?.source ?? '',
      note: baseline?.note ?? '',
    }
  }, [
    status,
    error,
    baseline,
    asOf,
    sickActive,
    sickPeople,
    blizzardActive,
    snowRedeployed,
    toggleSick,
    toggleBlizzard,
    planBundle,
    requestRows,
  ])

  return <SimulationContext.Provider value={value}>{children}</SimulationContext.Provider>
}

export function useSimulation() {
  const ctx = useContext(SimulationContext)
  if (!ctx) throw new Error('useSimulation must be used within SimulationProvider')
  return ctx
}
