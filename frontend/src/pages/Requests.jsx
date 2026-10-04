import { useEffect, useState } from 'react'
import RequestsTable from '../components/RequestsTable'
import { loadRequests } from '../data/loadRequests'

function Requests() {
  const [state, setState] = useState({ status: 'loading', rows: [] })

  useEffect(() => {
    let active = true
    loadRequests()
      .then((rows) => active && setState({ status: 'ready', rows }))
      .catch(() => active && setState({ status: 'error', rows: [] }))
    return () => {
      active = false
    }
  }, [])

  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      <header className="flex shrink-0 items-center justify-between border-b border-border bg-white px-5 py-3">
        <div>
          <h2 className="text-lg font-semibold text-text">Requests</h2>
          <p className="text-sm text-text-muted">
            Open crew jobs waiting 60 days or less. Highest priority first.
          </p>
        </div>
      </header>

      <div className="min-h-0 flex-1">
        {state.status === 'loading' && (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-text-muted">Loading requests...</p>
          </div>
        )}
        {state.status === 'error' && (
          <div className="flex h-full items-center justify-center px-5">
            <p className="text-sm text-text-muted">
              Could not load requests. Run backend/export_map_data.py.
            </p>
          </div>
        )}
        {state.status === 'ready' && <RequestsTable rows={state.rows} />}
      </div>
    </div>
  )
}

export default Requests
