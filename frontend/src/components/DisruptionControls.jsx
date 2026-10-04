import { useSimulation } from '../simulation/SimulationContext'

const BUTTON_CLASS = 'rounded-md border border-border bg-white px-3 py-1.5 text-sm text-text shadow-sm hover:bg-panel'
const ACTIVE_BUTTON_CLASS =
  'rounded-md border border-calgary-red bg-white px-3 py-1.5 text-sm font-semibold text-calgary-red shadow-sm'

/**
 * Shared Sick Call / Blizzard toggles. Same state on Crews, Dispatch, and Requests.
 */
function DisruptionControls({ className = '' }) {
  const { status, sickActive, blizzardActive, sickLabel, blizzardLabel, toggleSick, toggleBlizzard, workforce } =
    useSimulation()

  if (status !== 'ready' || !workforce) return null

  return (
    <div className={`flex flex-wrap items-center gap-2 ${className}`} role="group" aria-label="Workforce disruptions">
      <button
        type="button"
        aria-pressed={sickActive}
        onClick={toggleSick}
        className={sickActive ? ACTIVE_BUTTON_CLASS : BUTTON_CLASS}
      >
        {sickLabel}
      </button>
      <button
        type="button"
        aria-pressed={blizzardActive}
        onClick={toggleBlizzard}
        className={blizzardActive ? ACTIVE_BUTTON_CLASS : BUTTON_CLASS}
      >
        {blizzardLabel}
      </button>
      <span className="text-xs text-text-muted">
        Usable {workforce.usable_people.toLocaleString()} · Plan capacity {workforce.plan_capacity} crews
      </span>
    </div>
  )
}

export default DisruptionControls
