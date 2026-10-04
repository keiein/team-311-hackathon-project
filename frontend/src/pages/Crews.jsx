import { useEffect, useState } from 'react'
import CrewsTable from '../components/CrewsTable'
import { loadDispatch } from '../data/loadDispatch'

function Crews() {
  const [state, setState] = useState({ status: 'loading', data: null })

  useEffect(() => {
    let active = true
    loadDispatch()
      .then((data) => {
        if (!active) return
        // The crew list lives in dispatch.json as "crewSummary"
        setState(Array.isArray(data.crewSummary) ? { status: 'ready', data } : { status: 'error', data: null })
      })
      .catch(() => active && setState({ status: 'error', data: null }))
    return () => {
      active = false
    }
  }, [])

  const asOf = state.data?.summary?.asOf

  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      <header className="flex shrink-0 items-center justify-between border-b border-border bg-white px-5 py-3">
        <div>
          <h2 className="text-lg font-semibold text-text">Crews</h2>
          <p className="text-sm text-text-muted">
            Who is working today, and how the plan changes at noon.
            {asOf ? ` Data as of ${asOf}.` : ''}
          </p>
        </div>
      </header>

      <div className="min-h-0 flex-1">
        {state.status === 'loading' && (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-text-muted">Loading the crews...</p>
          </div>
        )}
        {state.status === 'error' && (
          <div className="flex h-full items-center justify-center px-5">
            <p className="text-sm text-text-muted">Could not load the crews. Run the dispatch export.</p>
          </div>
        )}
        {state.status === 'ready' && <CrewsTable data={state.data} />}
      </div>
    </div>
  )
}

export default Crews
