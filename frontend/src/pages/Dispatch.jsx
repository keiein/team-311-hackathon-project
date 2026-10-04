import DispatchTable from '../components/DispatchTable'
import DisruptionControls from '../components/DisruptionControls'
import { useSimulation } from '../simulation/SimulationContext'

function Dispatch() {
  const { status, asOf, dispatch } = useSimulation()

  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border bg-white px-5 py-3">
        <div>
          <h2 className="text-lg font-semibold text-text">Dispatch</h2>
          <p className="text-sm text-text-muted">
            Capacity plan: highest-priority tickets first, one crew per ticket.
            {asOf ? ` Data as of ${asOf}.` : ''}
          </p>
        </div>
        <DisruptionControls />
      </header>

      <div className="min-h-0 flex-1">
        {status === 'loading' && (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-text-muted">Loading the plan...</p>
          </div>
        )}
        {status === 'error' && (
          <div className="flex h-full items-center justify-center px-5">
            <p className="text-sm text-text-muted">Could not load the plan. Run the export scripts.</p>
          </div>
        )}
        {status === 'ready' && dispatch && <DispatchTable data={dispatch} />}
      </div>
    </div>
  )
}

export default Dispatch
