import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { loadRequests, loadRequestsMeta } from '../data/loadRequests'
import { loadWorkforce } from '../data/loadWorkforce'
import { pickRandomWorkerIds } from '../lib/pickRandomWorkerIds'
import { randomIntInclusive } from '../lib/randomIntInclusive'
import { buildCapacityPlan } from './buildCapacityPlan.js'
import { DEFAULT_JOBS_PER_CREW } from './dispatchConfig.js'

const SimulationContext = createContext(null)

const SICK_MIN = 0
const SICK_MAX = 10
const SNOW_MIN = 20
const SNOW_MAX = 35

const EMPTY_DISRUPTION = { active: false, people: 0, workerIds: [] }
const EMPTY_WORKER_IDS = []

function baselineFromWorkforceFile(data) {
  const normal = data?.scenarios?.normal
  const row = normal ?? data?.workforce
  return {
    totalPeople: Number(row?.total_people ?? 100),
    peoplePerCrew: Number(row?.people_per_crew ?? 5),
    jobsPerCrew: Number(row?.jobs_per_crew ?? DEFAULT_JOBS_PER_CREW),
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

  // Disruption toggles: counts + worker slot ids stay fixed until the toggle is turned off.
  const [sick, setSick] = useState(EMPTY_DISRUPTION)
  const [blizzard, setBlizzard] = useState(EMPTY_DISRUPTION)

  const sickRef = useRef(sick)
  const blizzardRef = useRef(blizzard)
  sickRef.current = sick
  blizzardRef.current = blizzard

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

  const totalPeople = baseline?.totalPeople ?? 100

  const toggleSick = useCallback(() => {
    setSick((current) => {
      if (current.active) return EMPTY_DISRUPTION
      const people = randomIntInclusive(SICK_MIN, SICK_MAX)
      const exclude = blizzardRef.current.active ? blizzardRef.current.workerIds : []
      return {
        active: true,
        people,
        workerIds: pickRandomWorkerIds(totalPeople, people, exclude),
      }
    })
  }, [totalPeople])

  const toggleBlizzard = useCallback(() => {
    setBlizzard((current) => {
      if (current.active) return EMPTY_DISRUPTION
      const people = randomIntInclusive(SNOW_MIN, SNOW_MAX)
      const exclude = sickRef.current.active ? sickRef.current.workerIds : []
      return {
        active: true,
        people,
        workerIds: pickRandomWorkerIds(totalPeople, people, exclude),
      }
    })
  }, [totalPeople])

  const sickActive = sick.active
  const sickPeople = sick.active ? sick.people : 0
  const sickWorkerIds = sick.active ? sick.workerIds : EMPTY_WORKER_IDS
  const blizzardActive = blizzard.active
  const snowRedeployed = blizzard.active ? blizzard.people : 0
  const snowRedeployedWorkerIds = blizzard.active ? blizzard.workerIds : EMPTY_WORKER_IDS

  const planBundle = useMemo(() => {
    if (status !== 'ready' || !baseline) return null
    return buildCapacityPlan(tickets, {
      totalPeople: baseline.totalPeople,
      sickPeople,
      snowRedeployed,
      peoplePerCrew: baseline.peoplePerCrew,
      jobsPerCrew: baseline.jobsPerCrew ?? DEFAULT_JOBS_PER_CREW,
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
    const sickCount = sickActive ? sickPeople : 0
    const snowCount = blizzardActive ? snowRedeployed : 0
    return {
      status,
      error,
      baseline,
      asOf,
      sickActive,
      sickPeople: sickCount,
      sickWorkerIds,
      blizzardActive,
      snowRedeployed: snowCount,
      snowRedeployedWorkerIds,
      sickLabel: sickActive ? `Sick Call (${sickCount})` : 'Sick Call',
      blizzardLabel: blizzardActive ? `Blizzard (+${snowCount} snow)` : 'Blizzard',
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
    sickWorkerIds,
    blizzardActive,
    snowRedeployed,
    snowRedeployedWorkerIds,
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
