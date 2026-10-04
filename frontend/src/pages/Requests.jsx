import { useEffect, useState } from 'react'
import DisruptionControls from '../components/DisruptionControls'
import NeedsReviewTable from '../components/NeedsReviewTable'
import RequestsTable from '../components/RequestsTable'
import { loadNeedsReview } from '../data/loadNeedsReview'
import { loadRequestsMeta } from '../data/loadRequests'
import { useSimulation } from '../simulation/SimulationContext'

const BUTTON_CLASS = 'rounded-md border border-border bg-white px-3 py-1.5 text-sm text-text shadow-sm hover:bg-panel'
const ACTIVE_BUTTON_CLASS =
  'rounded-md border border-calgary-red bg-white px-3 py-1.5 text-sm font-semibold text-calgary-red shadow-sm'

function Requests() {
  const [view, setView] = useState('queue')
  const { status, asOf, requestRows, dispatch } = useSimulation()
  const [meta, setMeta] = useState({})
  const [review, setReview] = useState({ status: 'idle', data: null })

  useEffect(() => {
    let active = true
    loadRequestsMeta()
      .then((m) => active && setMeta(m ?? {}))
      .catch(() => active && setMeta({}))
    loadNeedsReview()
      .then((data) => active && setReview({ status: 'ready', data }))
      .catch(() => active && setReview({ status: 'error', data: null }))
    return () => {
      active = false
    }
  }, [])

  const reviewCount = review.data?.count
  const loading =
    (view === 'queue' && status === 'loading') ||
    (view === 'review' && review.status !== 'ready' && review.status !== 'error')
  const failed = (view === 'queue' && status === 'error') || (view === 'review' && review.status === 'error')
  const assignedCount = dispatch?.summary?.plannedJobs

  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border bg-white px-5 py-3">
        <div>
          <h2 className="text-lg font-semibold text-text">Requests</h2>
          <p className="text-sm text-text-muted">
            {view === 'queue'
              ? 'Open crew jobs. Plan status follows shared workforce capacity (highest priority first).'
              : 'Crew jobs open over 60 days. Most dangerous type first, then oldest.'}
            {asOf ? ` Data as of ${asOf}.` : ''}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {view === 'queue' && <DisruptionControls />}
          <div className="flex items-center gap-2" role="group" aria-label="Which list to show">
            <button
              type="button"
              aria-pressed={view === 'queue'}
              onClick={() => setView('queue')}
              className={view === 'queue' ? ACTIVE_BUTTON_CLASS : BUTTON_CLASS}
            >
              Today&apos;s queue
              {status === 'ready'
                ? ` (${requestRows.length.toLocaleString()}${typeof assignedCount === 'number' ? `, ${assignedCount} assigned` : ''})`
                : ''}
            </button>
            <button
              type="button"
              aria-pressed={view === 'review'}
              onClick={() => setView('review')}
              className={view === 'review' ? ACTIVE_BUTTON_CLASS : BUTTON_CLASS}
            >
              Needs review{typeof reviewCount === 'number' ? ` (${reviewCount.toLocaleString()})` : ''}
            </button>
          </div>
        </div>
      </header>

      <div className="min-h-0 flex-1">
        {loading && (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-text-muted">Loading requests...</p>
          </div>
        )}
        {failed && (
          <div className="flex h-full items-center justify-center px-5">
            <p className="text-sm text-text-muted">Could not load requests. Run backend/export_team_scores.py.</p>
          </div>
        )}
        {view === 'queue' && status === 'ready' && (
          <RequestsTable rows={requestRows} weights={meta?.weights ?? {}} />
        )}
        {view === 'review' && review.status === 'ready' && <NeedsReviewTable data={review.data} />}
      </div>
    </div>
  )
}

export default Requests
