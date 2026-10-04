import { useEffect, useState } from 'react'
import ReportsView from '../components/ReportsView'
import { loadReports } from '../data/loadReports'

function Reports() {
  const [state, setState] = useState({ status: 'loading', data: null })

  useEffect(() => {
    let active = true
    loadReports()
      .then((data) => active && setState({ status: 'ready', data }))
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
          <h2 className="text-lg font-semibold text-text">Reports</h2>
          <p className="text-sm text-text-muted">
            Did our plan beat oldest-first, and how did the planner improve?
            {asOf ? ` Data as of ${asOf}.` : ''}
          </p>
        </div>
      </header>

      <div className="min-h-0 flex-1">
        {state.status === 'loading' && (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-text-muted">Loading the report...</p>
          </div>
        )}
        {state.status === 'error' && (
          <div className="flex h-full items-center justify-center px-5">
            <p className="text-sm text-text-muted">Could not load the report. Run the dispatch export.</p>
          </div>
        )}
        {state.status === 'ready' && <ReportsView data={state.data} />}
      </div>
    </div>
  )
}

export default Reports
