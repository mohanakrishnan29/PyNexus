import React, { useCallback, useEffect, useRef, useState } from 'react'
import ChatUI from './components/ChatUI.jsx'
import Sidebar from './components/Sidebar.jsx'
import KBPanel from './components/KBPanel.jsx'
import { fetchHealth, fetchInitStatus } from './api.js'

// ---------------------------------------------------------------------------
// Conversation persistence helpers (localStorage)
// ---------------------------------------------------------------------------

const STORAGE_KEY = 'PyNexus_conversations'
const MAX_CONVOS = 30

function loadConversations() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveConversations(convos) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(convos.slice(0, MAX_CONVOS)))
  } catch {
    /* ignore quota errors */
  }
}

function newConversation() {
  return {
    id: Date.now().toString(),
    title: 'New conversation',
    createdAt: Date.now(),
    messages: [],
  }
}

function titleFromMessage(text) {
  return text.length > 48 ? text.slice(0, 48) + 'ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦' : text
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export default function App() {
  const [conversations, setConversations] = useState(() => loadConversations())
  const [activeId, setActiveId] = useState(null)
  const [health, setHealth] = useState(null)
  const [initState, setInitState] = useState(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [kbPanelOpen, setKbPanelOpen] = useState(false)
  const pollRef = useRef(null)

  // ---- derive active conversation ----
  const activeConvo = conversations.find((c) => c.id === activeId) ?? null

  // ---- persist whenever conversations change ----
  useEffect(() => {
    saveConversations(conversations)
  }, [conversations])

  // ---- health check ----
  useEffect(() => {
    fetchHealth().then(setHealth).catch(() => setHealth(null))
  }, [])

  // ---- poll init-status while running ----
  const pollInitStatus = useCallback(() => {
    fetchInitStatus()
      .then((s) => {
        setInitState(s)
        if (s.running) {
          pollRef.current = setTimeout(pollInitStatus, 1500)
        } else {
          // Refresh health after init completes
          fetchHealth().then(setHealth).catch(() => {})
        }
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    // Fetch init state on mount so UI reflects previous runs
    pollInitStatus()
    return () => clearTimeout(pollRef.current)
  }, [pollInitStatus])

  // ---- conversation management ----
  const createConversation = useCallback(() => {
    const convo = newConversation()
    setConversations((prev) => [convo, ...prev])
    setActiveId(convo.id)
    return convo
  }, [])

  const selectConversation = useCallback((id) => setActiveId(id), [])

  const deleteConversation = useCallback((id) => {
    setConversations((prev) => prev.filter((c) => c.id !== id))
    setActiveId((prev) => (prev === id ? null : prev))
  }, [])

  const clearAll = useCallback(() => {
    setConversations([])
    setActiveId(null)
  }, [])

  // ---- message handling ----
  const addMessage = useCallback(
    (convoId, message) => {
      setConversations((prev) =>
        prev.map((c) => {
          if (c.id !== convoId) return c
          const updated = { ...c, messages: [...c.messages, message] }
          // Set title from first user message
          if (c.messages.length === 0 && message.role === 'user') {
            updated.title = titleFromMessage(message.content)
          }
          return updated
        }),
      )
    },
    [],
  )

  // Ensure there's always an active conversation when user wants to chat
  const ensureActiveConvo = useCallback(() => {
    if (activeId && conversations.find((c) => c.id === activeId)) {
      return activeId
    }
    const convo = newConversation()
    setConversations((prev) => [convo, ...prev])
    setActiveId(convo.id)
    return convo.id
  }, [activeId, conversations])

  const indexReady = health?.index_loaded === true
  const apiOnline = health?.status === 'ok'

  return (
    <div className="app-shell">
      {/* ---- Sidebar ---- */}
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        health={health}
        initState={initState}
        sidebarOpen={sidebarOpen}
        onNewChat={createConversation}
        onToggleSidebar={() => setSidebarOpen((v) => !v)}
        onSelectConvo={selectConversation}
        onDeleteConvo={deleteConversation}
        onClearAll={clearAll}
        onInitStart={pollInitStatus}
        onToggleKBPanel={() => setKbPanelOpen((v) => !v)}
      />

      {/* ---- Main chat area ---- */}
      <main className="chat-main">
        <ChatUI
          conversation={activeConvo}
          indexReady={indexReady}
          apiOnline={apiOnline}
          initState={initState}
          onAddMessage={addMessage}
          onEnsureConvo={ensureActiveConvo}
          sidebarOpen={sidebarOpen}
        />
      </main>

      <KBPanel
        open={kbPanelOpen}
        initState={initState}
        onClose={() => setKbPanelOpen(false)}
      />
    </div>
  )
}
