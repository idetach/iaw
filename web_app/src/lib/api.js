const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8080'
const AGENT_TRADING_URL = import.meta.env.VITE_AGENT_TRADING_URL || 'http://127.0.0.1:8082'

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
}
