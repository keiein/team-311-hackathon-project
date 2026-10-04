import { useEffect, useState } from 'react'
import CrewPoolsTable from '../components/CrewPoolsTable'
import CrewsTable from '../components/CrewsTable'
import { loadCrewPools } from '../data/loadCrewPools'
import { loadDispatch } from '../data/loadDispatch'

// Same look as the scenario buttons on the Dispatch page
const BUTTON_CLASS = 'rounded-md border border-border bg-white px-3 py-1.5 text-sm text-text shadow-sm hover:bg-panel'
const ACTIVE_BUTTON_CLASS =
  'rounded-md border border-calgary-red bg-white px-3 py-1.5 text-sm font-semibold text-calgary-red shadow-sm'

function Crews() {
  const [view, setView] = useState('crews') // 'crews' = today's crews, 'pools' = crew pools (placeholder)
  const [crews, setCrews] = useState({ status: 'loading', data: null })
  const [pools, setPools] = useState({ status: 'loading', data: null })

  useEffect(() => {
    let active = true
    loadDispatch()
      .then((data) => {
        if (!active) return
        // The crew list lives in dispatch.json as "crewSummary"
        setCrews(Array.isArray(data.crewSummary) ? { status: 'ready', data } : { status: 'error', data: null })
      })
      .catch(() => active && setCrews({ status: 'error', data: null }))
    loadCrewPools()
      .then((data) => active && setPools({ status: 'ready', data }))
      .catch(() => active && setPools({ status: 'error', data: null }))
    return () => {
      active = false
    }
  }, [])

  const current = view === 'crews' ? crews : pools
  const asOf = crews.data?.summary?.asOf

  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border bg-white px-5 py-3">
        <div>
          <h2 className="text-lg font-semibold text-text">Crews</h2>
          <p className="text-sm text-text-muted">
            {view === 'crews'
              ? 'Who is working today, and how the plan changes at noon.'
              : 'How many people each department has, next to its jobs today.'}
            {asOf ? ` Data as of ${asOf}.` : ''}
          </p>
        </div>
        <div className="flex items-center gap-2" role="group" aria-label="Which list to show">
          <button
            type="button"
            aria-pressed={view === 'crews'}
            onClick={() => setView('crews')}
            className={view === 'crews' ? ACTIVE_BUTTON_CLASS : BUTTON_CLASS}
          >
            Today&apos;s crews
          </button>
          <button
            type="button"
            aria-pressed={view === 'pools'}
            onClick={() => setView('pools')}
            className={view === 'pools' ? ACTIVE_BUTTON_CLASS : BUTTON_CLASS}
          >
            Crew pools (placeholder)
          </button>
        </div>
      </header>

      <div className="min-h-0 flex-1">
        {current.status === 'loading' && (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-text-muted">Loading the crews...</p>
          </div>
        )}
        {current.status === 'error' && (
          <div className="flex h-full items-center justify-center px-5">
            <p className="text-sm text-text-muted">Could not load the crews. Run the dispatch export.</p>
          </div>
        )}
        {current.status === 'ready' && view === 'crews' && <CrewsTable data={crews.data} />}
        {current.status === 'ready' && view === 'pools' && <CrewPoolsTable data={pools.data} />}
      </div>
    </div>
  )
}

export default Crews
