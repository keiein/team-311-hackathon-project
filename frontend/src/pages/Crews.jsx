import CrewsTable from '../components/CrewsTable'
import WorkforcePanel from '../components/WorkforcePanel'
import { useState } from 'react'
import { useSimulation } from '../simulation/SimulationContext'

const BUTTON_CLASS = 'rounded-md border border-border bg-white px-3 py-1.5 text-sm text-text shadow-sm hover:bg-panel'
const ACTIVE_BUTTON_CLASS =
  'rounded-md border border-calgary-red bg-white px-3 py-1.5 text-sm font-semibold text-calgary-red shadow-sm'

function Crews() {
  const [view, setView] = useState('workforce')
  const { status, asOf, dispatch } = useSimulation()

  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border bg-white px-5 py-3">
        <div>
          <h2 className="text-lg font-semibold text-text">Crews</h2>
          <p className="text-sm text-text-muted">
            {view === 'workforce'
              ? 'Shared operational workforce: usable people and plan capacity under disruptions.'
              : 'Deployable crews for the current capacity plan.'}
            {asOf ? ` Data as of ${asOf}.` : ''}
          </p>
        </div>
        <div className="flex items-center gap-2" role="group" aria-label="Which list to show">
          <button
            type="button"
            aria-pressed={view === 'workforce'}
            onClick={() => setView('workforce')}
            className={view === 'workforce' ? ACTIVE_BUTTON_CLASS : BUTTON_CLASS}
          >
            Workforce
          </button>
          <button
            type="button"
            aria-pressed={view === 'crews'}
            onClick={() => setView('crews')}
            className={view === 'crews' ? ACTIVE_BUTTON_CLASS : BUTTON_CLASS}
          >
            Today&apos;s crews
          </button>
        </div>
      </header>

      <div className="min-h-0 flex-1">
        {status === 'loading' && (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-text-muted">Loading the crews...</p>
          </div>
        )}
        {status === 'error' && (
          <div className="flex h-full items-center justify-center px-5">
            <p className="text-sm text-text-muted">
              Could not load workforce data. Run export_team_scores.py then make_dispatch_standin.py.
            </p>
          </div>
        )}
        {status === 'ready' && view === 'workforce' && <WorkforcePanel />}
        {status === 'ready' && view === 'crews' && dispatch && <CrewsTable data={dispatch} />}
      </div>
    </div>
  )
}

export default Crews
