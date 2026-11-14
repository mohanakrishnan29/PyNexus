import React from 'react'

function SourceStatusIcon({ status }) {
  if (status === 'done') return (
    <span className="src-icon src-icon--done">
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
        <polyline points="20 6 9 17 4 12" />
      </svg>
    </span>
  )
  if (status === 'running') return (
    <span className="src-icon src-icon--running">
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="spin-slow">
        <path d="M21 12a9 9 0 1 1-6.219-8.56" />
      </svg>
    </span>
  )
  if (status === 'failed') return (
    <span className="src-icon src-icon--failed">
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
        <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
      </svg>
    </span>
  )
  return (
    <span className="src-icon src-icon--pending">
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="9" />
      </svg>
    </span>
  )
}

export default function KBPanel({ open, initState, onClose }) {
  if (!open) return null

  const total = initState?.total ?? 0
  const completed = initState?.completed ?? 0
  const progress = total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0
  const running = initState?.running
  const pending = total - completed

  return (
    <div className="kb-panel-overlay" onClick={onClose}>
      <div className="kb-panel" onClick={(e) => e.stopPropagation()}>
        <div className="kb-panel-header">
          <div>
            <p className="kb-panel-title">Knowledge Base Progress</p>
            <p className="kb-panel-info">
              {running
                ? `Indexing in progress - ${completed} / ${total} sources completed.`
                : pending > 0
                ? `${completed} / ${total} sources indexed. ${pending} new source${pending === 1 ? '' : 's'} waiting to be indexed.`
                : total > 0
                ? 'Indexing finished. Review the latest source statuses below.'
                : 'No indexing run has started yet.'}
            </p>
          </div>
          <button className="kb-panel-close" onClick={onClose} aria-label="Close knowledge base panel">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div className="kb-panel-progress">
          <div className="kb-panel-progress-fill" style={{ width: `${progress}%` }} />
        </div>

        {initState?.sources?.length > 0 ? (
          <ul className="kb-panel-list">
            {initState.sources.map((source, index) => (
              <li key={index} className="kb-panel-item">
                <div className="kb-panel-item-name">
                  {source.name}
                </div>
                <div className="kb-panel-item-meta">
                  <SourceStatusIcon status={source.status} />
                  <span>{source.status}</span>
                  {source.pages_crawled != null && <span>{source.pages_crawled} pages</span>}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <div className="kb-panel-empty">
            No source progress available yet.
          </div>
        )}
      </div>
    </div>
  )
}
