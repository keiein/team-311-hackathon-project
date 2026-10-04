import { useEffect, useState } from 'react'
import NeedsReviewTable from '../components/NeedsReviewTable'
import RequestsTable from '../components/RequestsTable'
import { loadNeedsReview } from '../data/loadNeedsReview'
import { loadRequests, loadRequestsMeta } from '../data/loadRequests'

// Same look as the scenario buttons on the Dispatch page
const BUTTON_CLASS = 'rounded-md border border-border bg-white px-3 py-1.5 text-sm text-text shadow-sm hover:bg-panel'
const ACTIVE_BUTTON_CLASS =
  'rounded-md border border-calgary-red bg-white px-3 py-1.5 text-sm font-semibold text-calgary-red shadow-sm'

function Requests() {
  const [view, setView] = useState('queue') // 'queue' = today's queue, 'review' = needs review
  const [queue, setQueue] = useState({ status: 'loading', rows: [], meta: {} })
  const [review, setReview] = useState({ status: 'idle', data: null })

  useEffect(() => {
    let active = true
    Promise.all([loadRequests(), loadRequestsMeta()])
      .then(([rows, meta]) => active && setQueue({ status: 'ready', rows, meta }))
      .catch(() => active && setQueue({ status: 'error', rows: [], meta: {} }))
    // The needs-review count is shown on its button, so load it too (3 MB, in the background)
    loadNeedsReview()
      .then((data) => active && setReview({ status: 'ready', data }))
      .catch(() => active && setReview({ status: 'error', data: null }))
    return () => {
      active = false
    }
  }, [])

  const reviewCount = review.data?.count
  const loading = (view === 'queue' && queue.status === 'loading') || (view === 'review' && review.status !== 'ready' && review.status !== 'error')
  const failed = (view === 'queue' && queue.status === 'error') || (view === 'review' && review.status === 'error')

  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border bg-white px-5 py-3">
        <div>
          <h2 className="text-lg font-semibold text-text">Requests</h2>
          <p className="text-sm text-text-muted">
            {view === 'queue'
              ? 'Open crew jobs waiting 60 days or less. Highest priority first (team score).'
              : 'Crew jobs open over 60 days. Most dangerous type first, then oldest.'}
            {queue.meta?.asOf ? ` Data as of ${queue.meta.asOf}.` : ''}
          </p>
        </div>
        <div className="flex items-center gap-2" role="group" aria-label="Which list to show">
          <button
            type="button"
            aria-pressed={view === 'queue'}
            onClick={() => setView('queue')}
            className={view === 'queue' ? ACTIVE_BUTTON_CLASS : BUTTON_CLASS}
          >
            Today&apos;s queue{queue.status === 'ready' ? ` (${queue.rows.length.toLocaleString()})` : ''}
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
        {view === 'queue' && queue.status === 'ready' && (
          <RequestsTable rows={queue.rows} weights={queue.meta?.weights ?? {}} />
        )}
        {view === 'review' && review.status === 'ready' && <NeedsReviewTable data={review.data} />}
      </div>
    </div>
  )
}

export default Requests
