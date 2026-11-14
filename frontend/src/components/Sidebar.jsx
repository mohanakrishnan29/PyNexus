import React, { useState } from 'react'
import { startInitialize, pauseCrawl, resumeCrawl } from '../api.js'
import BrandIcon from './BrandIcon.jsx'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function groupByDate(conversations) {
  const now = Date.now()
  const DAY = 86400000
  const groups = { Today: [], Yesterday: [], 'Last 7 days': [], Older: [] }
  for (const c of conversations) {
    const age = now - c.createdAt
    if (age < DAY)          groups['Today'].push(c)
    else if (age < 2 * DAY) groups['Yesterday'].push(c)
    else if (age < 7 * DAY) groups['Last 7 days'].push(c)
    else                    groups['Older'].push(c)
  }
  return groups
}

// ---------------------------------------------------------------------------
// Source status icon
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------------
export default function Sidebar({
  conversations,
  activeId,
  health,
  initState,
  sidebarOpen,
  onNewChat,
  onSelectConvo,
  onDeleteConvo,
  onClearAll,
  onInitStart,
  onToggleSidebar,
  onToggleKBPanel,
}) {
  const [initError, setInitError]   = useState(null)
  const [hoveredId, setHoveredId]   = useState(null)
  const [actionBusy, setActionBusy] = useState(false)

  const isRunning  = initState?.running
  const isPaused   = initState?.paused && !initState?.running
  const isDone     = initState?.done
  const indexReady = health?.index_loaded
  const totalSources = initState?.total ?? 0
  const completedSources = initState?.completed ?? 0
  const hasPendingSources = totalSources > completedSources

  // ---- handlers -----------------------------------------------------------

  const handleInitialize = async () => {
    setInitError(null)
    setActionBusy(true)
    try {
      await startInitialize()
      onInitStart?.()
    } catch (e) {
      setInitError(e?.response?.data?.detail || e.message || 'Failed to start initialization.')
    } finally {
      setActionBusy(false)
    }
  }

  const handlePause = async () => {
    setInitError(null)
    setActionBusy(true)
    try {
      await pauseCrawl()
    } catch (e) {
      setInitError(e?.response?.data?.detail || e.message || 'Failed to pause.')
    } finally {
      setActionBusy(false)
    }
  }

  const handleResume = async () => {
    setInitError(null)
    setActionBusy(true)
    try {
      await resumeCrawl()
      onInitStart?.()
    } catch (e) {
      setInitError(e?.response?.data?.detail || e.message || 'Failed to resume.')
    } finally {
      setActionBusy(false)
    }
  }

  // ---- collapsed sidebar --------------------------------------------------

  const groups = groupByDate(conversations)

  if (!sidebarOpen) {
    return (
      <aside className="sidebar sidebar--collapsed">
        <button className="icon-btn sidebar-toggle-btn" onClick={onToggleSidebar} title="Open sidebar">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>
        <button className="icon-btn" onClick={onNewChat} title="New chat">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </button>
      </aside>
    )
  }

  // ---- full sidebar -------------------------------------------------------

  return (
    <aside className="sidebar">
      {/* Header */}
      <div className="sidebar-header">
        <div className="sidebar-brand">
          <BrandIcon size={20} />
          <span className="sidebar-brand-name">PyNexus</span>
        </div>
        <div className="sidebar-header-actions">
          <button className="icon-btn" onClick={onNewChat} title="New conversation" aria-label="New conversation">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 5v14M5 12h14" />
            </svg>
          </button>
          <button className="icon-btn" onClick={onToggleSidebar} title="Close sidebar" aria-label="Close sidebar">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
        </div>
      </div>

      {/* Conversation list */}
      <div className="sidebar-convos">
        {conversations.length === 0 ? (
          <p className="sidebar-empty">No conversations yet. Start chatting!</p>
        ) : (
          Object.entries(groups).map(([label, items]) =>
            items.length === 0 ? null : (
              <div key={label} className="convo-group">
                <p className="convo-group-label">{label}</p>
                {items.map((c) => (
                  <div
                    key={c.id}
                    className={`convo-item ${c.id === activeId ? 'convo-item--active' : ''}`}
                    onClick={() => onSelectConvo(c.id)}
                    onMouseEnter={() => setHoveredId(c.id)}
                    onMouseLeave={() => setHoveredId(null)}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="convo-item-icon">
                      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                    </svg>
                    <span className="convo-item-title">{c.title}</span>
                    {(hoveredId === c.id || c.id === activeId) && (
                      <button
                        className="convo-delete-btn"
                        onClick={(e) => { e.stopPropagation(); onDeleteConvo(c.id) }}
                        title="Delete"
                      >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                          <polyline points="3 6 5 6 21 6" />
                          <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                          <path d="M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
                        </svg>
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )
          )
        )}
      </div>

      {/* Knowledge Base panel */}
      <div className="sidebar-kb">
        <div className="kb-header">
          <span className="kb-title">Knowledge Base</span>

          {/* Status badge — only one shows at a time */}
          {indexReady && hasPendingSources && !isRunning && !isPaused && (
            <span className="kb-badge kb-badge--empty">Update Available</span>
          )}
          {indexReady && !hasPendingSources && !isRunning && !isPaused && (
            <span className="kb-badge kb-badge--ready">Ready</span>
          )}
          {!indexReady && !isRunning && !isPaused && (
            <span className="kb-badge kb-badge--empty">Not Built</span>
          )}
          {isRunning && (
            <span className="kb-badge kb-badge--building">
              <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="spin-slow" style={{ marginRight: 4 }}>
                <path d="M21 12a9 9 0 1 1-6.219-8.56" />
              </svg>
              Building
            </span>
          )}
          {isPaused && (
            <span className="kb-badge kb-badge--paused">Paused</span>
          )}
        </div>

        {/* Progress bar — shown while running or paused mid-run */}
        {totalSources > 0 && (isRunning || isPaused || hasPendingSources) && (
          <div className="kb-progress-bar">
            <div
              className="kb-progress-fill"
              style={{ width: `${(completedSources / totalSources) * 100}%` }}
            />
          </div>
        )}

        {/* Summary text + View progress link */}
        <div className="kb-summary">
          <p className="kb-summary-text">
            {isRunning
              ? `Indexing ${initState.completed} / ${initState.total} sources…`
              : isPaused
              ? `Paused — ${initState.completed} / ${initState.total} sources done.`
              : hasPendingSources
              ? `${completedSources} / ${totalSources} sources indexed — ${totalSources - completedSources} new source${totalSources - completedSources === 1 ? '' : 's'} ready.`
              : indexReady
              ? 'Knowledge base is ready.'
              : 'Knowledge base not built yet.'}
          </p>
          <button className="kb-details-btn" onClick={onToggleKBPanel}>
            View Indexing Progress
          </button>
        </div>

        {/* Errors */}
        {initState?.error && <p className="kb-error">{initState.error}</p>}
        {initError         && <p className="kb-error">{initError}</p>}

        {/* Action buttons */}
        <div className="kb-actions">

          {/* Primary action: Initialize / Re-index / Indexing (disabled) */}
          <button
            className={`kb-init-btn ${isRunning ? 'kb-init-btn--running' : ''}`}
            onClick={handleInitialize}
            disabled={isRunning || isPaused || actionBusy || (!hasPendingSources && (isDone || indexReady))}
            title={isPaused ? 'Use Resume to continue the paused run' : undefined}
          >
            {isRunning ? (
              <>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="spin-slow">
                  <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                </svg>
                Indexing Python Docs…
              </>
            ) : hasPendingSources ? (
              <>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                  <polyline points="22 4 12 14.01 9 11.01" />
                </svg>
                Index New Sources
              </>
            ) : isDone || indexReady ? (
              <>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <polyline points="1 4 1 10 7 10" />
                  <path d="M3.51 15a9 9 0 1 0 .49-4.15" />
                </svg>
                Sources Up to Date
              </>
            ) : (
              <>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                  <polyline points="22 4 12 14.01 9 11.01" />
                </svg>
                Initialize Knowledge Base
              </>
            )}
          </button>

          {/* Pause button — only while running */}
          {isRunning && (
            <button
              className="kb-pause-btn"
              onClick={handlePause}
              disabled={actionBusy}
              title="Pause after current source finishes"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
                <rect x="6" y="4" width="4" height="16" rx="1" />
                <rect x="14" y="4" width="4" height="16" rx="1" />
              </svg>
              Pause
            </button>
          )}

          {/* Resume button — only when paused */}
          {isPaused && (
            <button
              className="kb-resume-btn"
              onClick={handleResume}
              disabled={actionBusy}
              title="Continue from where indexing left off"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
                <polygon points="5 3 19 12 5 21 5 3" />
              </svg>
              Resume
            </button>
          )}
        </div>

        <p className="kb-hint">Crawls official Python docs</p>
      </div>
    </aside>
  )
}
