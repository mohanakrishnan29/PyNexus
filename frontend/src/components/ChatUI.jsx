import React, { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { sendQuery } from '../api.js'
import BrandIcon from './BrandIcon.jsx'

// ---------------------------------------------------------------------------
// Suggestion chips shown on the welcome screen
// ---------------------------------------------------------------------------
const SUGGESTIONS = [
  'What are Python list comprehensions?',
  'Explain Python decorators with examples',
  'How does async/await work in Python?',
  'What is the difference between a list and a tuple?',
  'How do I handle exceptions in Python?',
  'Explain Python generators and yield',
  'What are Python dataclasses?',
  'How does Python\'s GIL work?',
]

// ---------------------------------------------------------------------------
// Markdown code rendering
//
// `react-markdown` does not reliably provide the historical `inline` prop.
// Rendering <code> as inline by default and handling only <pre> as a block
// keeps identifiers such as `async` and `asyncio.run()` in their sentence.
// ---------------------------------------------------------------------------
function InlineCode({ children, ...props }) {
  return (
    <code className="inline-code" {...props}>
      {children}
    </code>
  )
}

function CodeBlock({ children }) {
  const [copied, setCopied] = useState(false)
  const codeElement = React.Children.toArray(children)[0]
  const code = String(codeElement?.props?.children ?? children).replace(/\n$/, '')
  const className = codeElement?.props?.className || ''
  const lang = className.replace('language-', '') || 'code'

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // The code remains selectable if the browser blocks clipboard access.
    }
  }

  return (
    <div className="code-block-wrapper">
      <div className="code-block-header">
        <span className="code-lang">{lang}</span>
        <button className="copy-btn" onClick={handleCopy} type="button" aria-label="Copy code">
          {copied ? (
            <>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <polyline points="20 6 9 17 4 12" />
              </svg>
              Copied
            </>
          ) : (
            <>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                <path d="M5 15H4a2 2 0 1 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
              </svg>
              Copy
            </>
          )}
        </button>
      </div>
      <pre className="code-block-pre"><code className={className}>{code}</code></pre>
    </div>
  )
}

const mdComponents = {
  code: InlineCode,
  pre: CodeBlock,
}
// ---------------------------------------------------------------------------
// Single message bubble
// ---------------------------------------------------------------------------
function Message({ msg }) {
  const [sourcesOpen, setSourcesOpen] = useState(false)
  const isUser = msg.role === 'user'

  return (
    <div className={`msg-row ${isUser ? 'msg-row--user' : 'msg-row--assistant'}`}>
      {!isUser && (
        <div className="msg-avatar"><BrandIcon size={22} /></div>
      )}
      <div className={`msg-bubble ${isUser ? 'msg-bubble--user' : 'msg-bubble--assistant'} ${msg.isError ? 'msg-bubble--error' : ''}`}>
        {isUser ? (
          <p className="msg-user-text">{msg.content}</p>
        ) : (
          <div className="markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
              {msg.content}
            </ReactMarkdown>
          </div>
        )}

        {/* Sources */}
        {msg.sources && msg.sources.length > 0 && (
          <div className="sources-section">
            <button
              className="sources-toggle"
              onClick={() => setSourcesOpen((v) => !v)}
            >
              <svg
                width="12" height="12" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth="2"
                style={{ transform: sourcesOpen ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s' }}
              >
                <polyline points="9 18 15 12 9 6" />
              </svg>
              {msg.sources.length} source{msg.sources.length !== 1 ? 's' : ''}
              {msg.provider && msg.provider !== 'local' && (
                <span className="provider-badge">{msg.provider}</span>
              )}
            </button>
            {sourcesOpen && (
              <ul className="sources-list">
                {msg.sources.map((s, i) => (
                  <li key={i} className="source-item">
                    <a href={s.url} target="_blank" rel="noopener noreferrer" className="source-link">
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                        <polyline points="15 3 21 3 21 9" />
                        <line x1="10" y1="14" x2="21" y2="3" />
                      </svg>
                      {s.title || s.url}
                    </a>
                    {s.snippet && <p className="source-snippet">{s.snippet}</p>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
      {isUser && (
        <div className="msg-avatar msg-avatar--user">
          <span>U</span>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Thinking indicator
// ---------------------------------------------------------------------------
function ThinkingBubble() {
  return (
    <div className="msg-row msg-row--assistant">
      <div className="msg-avatar"><BrandIcon size={22} /></div>
      <div className="msg-bubble msg-bubble--assistant thinking-bubble">
        <span className="dot" />
        <span className="dot" />
        <span className="dot" />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Welcome / empty state
// ---------------------------------------------------------------------------
function WelcomeScreen({ onSuggest, indexReady, initState }) {
  const isInitializing = initState?.running
  const isReady = indexReady

  return (
    <div className="welcome-screen">
      <div className="welcome-logo"><BrandIcon size={64} /></div>
      <h1 className="welcome-title">PyNexus</h1>
      <p className="welcome-subtitle">Your intelligent Python programming assistant</p>

      {!isReady && !isInitializing && (
        <div className="welcome-notice">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          Initialize the knowledge base from the sidebar to unlock full AI answers.
          You can still ask questions â€” the bot will use its best effort.
        </div>
      )}

      {isInitializing && (
        <div className="welcome-notice welcome-notice--info">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="spin-slow">
            <path d="M21 12a9 9 0 1 1-6.219-8.56" />
          </svg>
          Building Python knowledge base... {initState.completed}/{initState.total} sources indexed.
          You can chat while this runs.
        </div>
      )}

      <div className="suggestions-grid">
        {SUGGESTIONS.slice(0, 6).map((s) => (
          <button key={s} className="suggestion-chip" onClick={() => onSuggest(s)}>
            {s}
          </button>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main ChatUI
// ---------------------------------------------------------------------------
export default function ChatUI({
  conversation,
  indexReady,
  apiOnline,
  initState,
  onAddMessage,
  onEnsureConvo,
  sidebarOpen,
}) {
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const scrollerRef = useRef(null)
  const textareaRef = useRef(null)

  const messages = conversation?.messages ?? []

  useEffect(() => {
    const el = scrollerRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, sending])

  // Auto-resize textarea
  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px'
  }, [input])

  const submit = async (text) => {
    const q = (text ?? input).trim()
    if (!q || sending || !apiOnline) return

    const convoId = onEnsureConvo()
    setInput('')

    const userMsg = { role: 'user', content: q }
    onAddMessage(convoId, userMsg)
    setSending(true)

    // Build history from current conversation (exclude just-added user msg)
    const history = messages.map((m) => ({ role: m.role, content: m.content }))

    try {
      const res = await sendQuery(q, history)
      onAddMessage(convoId, {
        role: 'assistant',
        content: res.answer,
        sources: res.sources || [],
        provider: res.used_provider,
      })
    } catch (e) {
      onAddMessage(convoId, {
        role: 'assistant',
        content:
          '**Error:** ' +
          (e?.response?.data?.detail || e.message || 'Unknown error.') +
          (!indexReady
            ? '\n\n_Tip: Initialize the knowledge base from the sidebar for best results._'
            : ''),
        isError: true,
      })
    } finally {
      setSending(false)
      textareaRef.current?.focus()
    }
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const isEmpty = messages.length === 0

  return (
    <div className="chat-container">
      {/* Top bar */}
      <div className="chat-topbar">
        <span className="chat-topbar-title">
          {conversation?.title || 'PyNexus'}
        </span>
      </div>

      {/* Messages */}
      <div className="chat-scroller" ref={scrollerRef}>
        {isEmpty ? (
          <WelcomeScreen
            onSuggest={submit}
            indexReady={indexReady}
            initState={initState}

          />
        ) : (
          <div className="messages-list">
            {messages.map((m, i) => (
              <Message key={i} msg={m} />
            ))}
            {sending && <ThinkingBubble />}
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="chat-input-area">
        {!apiOnline && (
          <div className="api-offline-banner">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            Backend offline â€” start the FastAPI server
          </div>
        )}
        <div className="input-wrapper">
          <textarea
            ref={textareaRef}
            className="chat-textarea"
            placeholder="Ask anything about Python..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            disabled={sending || !apiOnline}
          />
          <button
            className={`send-btn ${input.trim() && apiOnline ? 'send-btn--active' : ''}`}
            onClick={() => submit()}
            disabled={!input.trim() || sending || !apiOnline}
            title="Send (Enter)"
          >
            {sending ? (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="spin-slow">
                <path d="M21 12a9 9 0 1 1-6.219-8.56" />
              </svg>
            ) : (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            )}
          </button>
        </div>
        <p className="input-hint">Enter to send Â· Shift+Enter for new line</p>
      </div>
    </div>
  )
}


