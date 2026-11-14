import axios from 'axios'

// In dev, Vite proxies /api -> http://localhost:8000 (see vite.config.js).
// In production builds, set VITE_API_BASE in a .env file.
const baseURL = import.meta.env.VITE_API_BASE || '/api'

export const api = axios.create({
  baseURL,
  timeout: 600000, // crawls can be slow
})

export const fetchHealth      = () => api.get('/health').then((r) => r.data)
export const fetchStats       = () => api.get('/stats').then((r) => r.data)
export const fetchSources     = () => api.get('/sources').then((r) => r.data)
export const fetchInitStatus  = () => api.get('/init-status').then((r) => r.data)
export const startInitialize  = () => api.post('/initialize').then((r) => r.data)
export const pauseCrawl       = () => api.post('/pause').then((r) => r.data)
export const resumeCrawl      = () => api.post('/resume').then((r) => r.data)

export const startCrawl = (payload) =>
  api.post('/crawl', payload).then((r) => r.data)

export const startIngest = () => api.post('/ingest').then((r) => r.data)

/**
 * Send a query with optional conversation history.
 * @param {string} query
 * @param {{ role: string, content: string }[]} history
 * @param {number|null} top_k
 */
export const sendQuery = (query, history = [], top_k = null) =>
  api.post('/query', { query, history, top_k }).then((r) => r.data)