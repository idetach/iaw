import { auth as firebaseAuth } from './firebase'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8080'
const AGENT_TRADING_URL = import.meta.env.VITE_AGENT_TRADING_URL || 'http://127.0.0.1:8082'
const CONDUCTOR_URL = import.meta.env.VITE_CONDUCTOR_URL || 'http://127.0.0.1:8084'

// The conductor sits behind the iaw-web reverse proxy (ADR-0008): the browser
// sends the Firebase ID token, the proxy verifies it and swaps in a Google
// identity token for the private Cloud Run service.
async function firebaseIdToken() {
  const user = firebaseAuth?.currentUser
  if (!user) return ''
  try {
    return await user.getIdToken()
  } catch {
    return ''
  }
}

async function request(path, options = {}) {
  const { timeoutMs: rawTimeoutMs, ...fetchOptions } = options
  const timeoutMs = Number.isFinite(rawTimeoutMs) ? rawTimeoutMs : 0
  const controller = timeoutMs > 0 ? new AbortController() : null
  const timeoutId = controller ? setTimeout(() => controller.abort(), timeoutMs) : null
  const mergedHeaders = {
    'Content-Type': 'application/json',
    ...(fetchOptions.headers || {}),
  }

  let res
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      ...fetchOptions,
      headers: mergedHeaders,
      signal: controller?.signal,
    })
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)}s: ${path}`)
    }
    throw error
  } finally {
    if (timeoutId) {
      clearTimeout(timeoutId)
    }
  }

  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `Request failed: ${res.status}`)
  }

  if (res.status === 204) {
    return null
  }
  return res.json()
}

async function traderRequest(path, options = {}) {
  const mergedHeaders = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  const res = await fetch(`${AGENT_TRADING_URL}${path}`, { ...options, headers: mergedHeaders })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `agent_trading request failed: ${res.status}`)
  }
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  baseUrl: API_BASE_URL,
  agentTradingUrl: AGENT_TRADING_URL,
  streamUrl() {
    return `${API_BASE_URL}/v1/cases/stream`
  },
  getFrontendMeta() {
    return request('/v1/frontend/meta')
  },
  listTradingViewWindows() {
    return request('/v1/worker/tradingview/windows', { timeoutMs: 60000 })
  },
  arrangeTradingViewWindows(payload) {
    return request('/v1/worker/tradingview/windows/arrange', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  listCases({ limit, offset } = {}) {
    const qs = new URLSearchParams()
    if (Number.isFinite(limit)) {
      qs.set('limit', String(limit))
    }
    if (Number.isFinite(offset)) {
      qs.set('offset', String(offset))
    }
    const query = qs.toString()
    return request(`/v1/cases${query ? `?${query}` : ''}`)
  },
  getCase(caseId) {
    return request(`/v1/cases/${caseId}`)
  },
  deleteCase(caseId) {
    return request(`/v1/cases/${caseId}`, {
      method: 'DELETE',
    })
  },
  resizeWindowsDismissTVBanner(caseId, payload) {
    return request(`/v1/cases/${caseId}/resize-windows-dismiss-tv-banner`, {
      method: 'POST',
      body: JSON.stringify(payload || {}),
    })
  },
  saveTrade(caseId, payload) {
    return request(`/v1/cases/${caseId}/trade`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  createCase() {
    return request('/v1/cases/create', { method: 'POST' })
  },
  triggerCaseGeneration(caseId, payload) {
    return request(`/v1/cases/${caseId}/generate`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  analyzeCase(caseId, payload) {
    return request(`/v1/cases/${caseId}/analyze`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  executeTrade(caseId, params = {}) {
    return traderRequest(`/v1/trader/cases/${caseId}/execute`, {
      method: 'POST',
      body: JSON.stringify(params),
    })
  },
  executeManualTrade(caseId, payload) {
    return traderRequest(`/v1/trader/cases/${caseId}/manual`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  getTradeExecution(caseId) {
    return traderRequest(`/v1/trader/cases/${caseId}/trade`)
  },

  // --- conductor (autonomous loop) ---------------------------------------
  conductorUrl: CONDUCTOR_URL,
  getConductorConfig() {
    return conductorRequest('/v1/config')
  },
  getConductorStatus() {
    return conductorRequest('/v1/loop/status')
  },
  setConductorEnabled(enabled) {
    return conductorRequest('/v1/loop/enabled', {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    })
  },
  runConductorTick() {
    return conductorRequest('/v1/loop/tick', { method: 'POST', timeoutMs: 300000 })
  },
  async conductorTickStreamUrl() {
    // EventSource cannot set headers; the proxy accepts the user token as a
    // query param for SSE (ADR-0008).
    const token = await firebaseIdToken()
    const base = `${CONDUCTOR_URL}/v1/loop/tick/stream`
    return token ? `${base}?access_token=${encodeURIComponent(token)}` : base
  },
  getConductorSettings() {
    return conductorRequest('/v1/settings')
  },
  updateConductorSettings(body) {
    return conductorRequest('/v1/settings', { method: 'PUT', body: JSON.stringify(body) })
  },
  listConductorCases({ limit = 30, offset = 0 } = {}) {
    return conductorRequest(`/v1/cases?limit=${limit}&offset=${offset}`)
  },
  getConductorCase(caseId) {
    // caseId is path-shaped: {date}/{tick_id}/{SYMBOL}
    return conductorRequest(`/v1/cases/${caseId}`)
  },
}

async function conductorRequest(path, options = {}) {
  const { timeoutMs: rawTimeoutMs, ...fetchOptions } = options
  const timeoutMs = Number.isFinite(rawTimeoutMs) ? rawTimeoutMs : 15000
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)
  const token = await firebaseIdToken()
  const mergedHeaders = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(fetchOptions.headers || {}),
  }
  let res
  try {
    res = await fetch(`${CONDUCTOR_URL}${path}`, {
      ...fetchOptions,
      headers: mergedHeaders,
      signal: controller.signal,
    })
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw new Error(`Conductor request timed out: ${path}`)
    }
    throw error
  } finally {
    clearTimeout(timeoutId)
  }
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `conductor request failed: ${res.status}`)
  }
  if (res.status === 204) return null
  return res.json()
}
