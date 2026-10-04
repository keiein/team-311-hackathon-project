import CalgaryMap from '../components/CalgaryMap'

function Dashboard() {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 items-center justify-between border-b border-border bg-white px-5 py-3">
        <div>
          <h2 className="text-lg font-semibold text-text">Dashboard</h2>
          <p className="text-sm text-text-muted">
            Operational map view — City of Calgary
          </p>
        </div>
      </header>

      <div className="min-h-0 flex-1 p-3">
        <CalgaryMap />
      </div>
    </div>
  )
}

export default Dashboard
