import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { api } from '../lib/api'

const CASES_PAGE_SIZE = 30
const RUNNING_STATES = new Set(['queued', 'running'])
const CASE_DETAIL_IN_FLIGHT = new Map()

function caseTimestamp(item) {
  return item?.timestamp_utc || `${item?.date || ''}T00:00:00Z`
}

function sortCaseItems(items) {
  return [...(items || [])].sort((a, b) => {
    const aTs = caseTimestamp(a)
    const bTs = caseTimestamp(b)
    if (aTs !== bTs) {
      return bTs.localeCompare(aTs)
    }
    return (b?.case_id || '').localeCompare(a?.case_id || '')
  })
}

function flattenCaseGroups(groups) {
  return (groups || []).flatMap((group) => group.items || [])
}

function groupCaseItems(items) {
  const byDate = new Map()
  for (const item of sortCaseItems(items)) {
    const date = item?.date || String(item?.timestamp_utc || '').slice(0, 10) || 'unknown'
    if (!byDate.has(date)) {
      byDate.set(date, [])
    }
    byDate.get(date).push(item)
  }

  return [...byDate.entries()]
    .sort(([a], [b]) => b.localeCompare(a))
    .map(([date, groupItems]) => ({ date, items: sortCaseItems(groupItems) }))
}

function mergeCaseGroups(existingGroups, incomingGroups) {
  const map = new Map()
  for (const item of flattenCaseGroups(existingGroups)) {
    map.set(item.case_id, item)
  }
  for (const item of flattenCaseGroups(incomingGroups)) {
    map.set(item.case_id, { ...(map.get(item.case_id) || {}), ...item })
  }
  return groupCaseItems([...map.values()])
}

function pinRunningCaseToTop(groups, caseId) {
  if (!caseId) {
    return groups
  }
  const flat = flattenCaseGroups(groups)
  const idx = flat.findIndex((item) => item.case_id === caseId)
  if (idx < 0) {
    return groups
  }
  const target = flat[idx]
  const state = target?.generation_state || target?.status
  if (!RUNNING_STATES.has(state)) {
    return groupCaseItems(flat)
  }
  flat.splice(idx, 1)
  flat.unshift(target)
  return groupCaseItems(flat)
}

function defaultSettings(meta) {
  const defaultProvider = meta?.default_provider || 'claude'
  const timeframes = meta?.timeframes || ['1m', '5m', '15m', '30m', '1h', '4h']
  return {
    providerDefaults: {
      claude: {
        pass1: meta?.providers?.claude?.pass1_default || '',
        pass2: meta?.providers?.claude?.pass2_default || '',
      },
      openai: {
        pass1: meta?.providers?.openai?.pass1_default || '',
        pass2: meta?.providers?.openai?.pass2_default || '',
      },
      gemini: {
        pass1: meta?.providers?.gemini?.pass1_default || '',
        pass2: meta?.providers?.gemini?.pass2_default || '',
      },
    },
    chartsEnabled: {
      liquidation_heatmap: true,
      timeframes,
    },
    appWindow: 'auto',
    tvResizeAndDismissBanner: false,
    tvCalibrateWindowSize: true,
    showTvWindowOnCalibration: true,
    dismissTvBanner: true,
    chartScreensHorizontalVisibility: 'right',
    chartScreensVerticalVisibility: 'top',
    chartScreensResizeOnArrange: true,
    chartScreensOneStack: false,
    chartScreensShowWindowOnResize: true,
    liquidationHeatmapWindowOwner: 'Safari',
    timezone: 'local',
    enableCaseDelete: false,
    deleteOnlyFailedCases: true,
    defaultProvider,
  }
}

export const useAppStore = create(
  persist(
    (set, get) => ({
      auth: {
        user: null,
        loading: true,
      },
      sidebarCollapsed: false,
      caseGroups: [],
      selectedCaseId: null,
      caseDetail: null,
      caseDetailsById: {},
      caseDetailInFlightById: {},
      caseDetailLoading: false,
      casesLoading: false,
      casesLoadingMore: false,
      casesPagination: {
        limit: CASES_PAGE_SIZE,
        offset: 0,
        nextOffset: 0,
        hasMore: false,
        total: 0,
      },
      newlyCreatedCaseId: null,
      loadingMeta: false,
      savingTrade: false,
      generatingCase: false,
      resizingWindowsDismissTVBanner: false,
      lastError: null,
      meta: null,
      settings: {
        providerDefaults: {
          claude: { pass1: '', pass2: '' },
          openai: { pass1: '', pass2: '' },
          gemini: { pass1: '', pass2: '' },
        },
        chartsEnabled: {
          liquidation_heatmap: true,
          timeframes: ['1m', '5m', '15m', '30m', '1h', '4h'],
        },
        appWindow: 'auto',
        tvCalibrateWindowSize: true,
        showTvWindowOnCalibration: false,
        chartScreensHorizontalVisibility: 'right',
        chartScreensVerticalVisibility: 'top',
        chartScreensResizeOnArrange: true,
        chartScreensOneStack: false,
        chartScreensShowWindowOnResize: false,
        liquidationHeatmapWindowOwner: 'Safari',
        timezone: 'local',
        enableCaseDelete: false,
        deleteOnlyFailedCases: true,
        defaultProvider: 'claude',
      },
      setAuthUser(user) {
        set((state) => ({ auth: { ...state.auth, user, loading: false } }))
      },
      setAuthLoading(loading) {
        set((state) => ({ auth: { ...state.auth, loading } }))
      },
      toggleSidebar() {
        set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed }))
      },
      selectCase(caseId) {
        set({ selectedCaseId: caseId })
      },
      async loadMeta() {
        set({ loadingMeta: true, lastError: null })
        try {
          const meta = await api.getFrontendMeta()
          const defaults = defaultSettings(meta)
          set((state) => ({
            meta,
            loadingMeta: false,
            settings: {
              ...defaults,
              ...state.settings,
              providerDefaults: {
                ...defaults.providerDefaults,
                ...state.settings.providerDefaults,
              },
              chartsEnabled: {
                ...defaults.chartsEnabled,
                ...state.settings.chartsEnabled,
              },
            },
          }))
        } catch (error) {
          set({ loadingMeta: false, lastError: error.message })
        }
      },
      async loadCases(options = {}) {
        const reset = options?.reset !== false
        const stateBefore = get()
        const limit = Number.isFinite(options?.limit)
          ? options.limit
          : stateBefore.casesPagination?.limit || CASES_PAGE_SIZE
        const offset = reset ? 0 : stateBefore.casesPagination?.nextOffset || 0

        set({
          casesLoading: reset,
          casesLoadingMore: !reset,
          lastError: null,
        })
        try {
          const data = await api.listCases({ limit, offset })
          const incomingGroups = data?.groups || []
          const pagination = data?.pagination || {}
          set((state) => ({
            caseGroups: pinRunningCaseToTop(
              reset ? incomingGroups : mergeCaseGroups(state.caseGroups, incomingGroups),
              state.newlyCreatedCaseId,
            ),
            casesLoading: false,
            casesLoadingMore: false,
            casesPagination: {
              limit,
              offset: Number.isFinite(pagination.offset) ? pagination.offset : offset,
              nextOffset: Number.isFinite(pagination.next_offset)
                ? pagination.next_offset
                : offset + flattenCaseGroups(incomingGroups).length,
              hasMore: Boolean(pagination.has_more),
              total: Number.isFinite(pagination.total) ? pagination.total : state.casesPagination.total,
            },
            selectedCaseId: state.selectedCaseId || incomingGroups[0]?.items?.[0]?.case_id || null,
          }))
        } catch (error) {
          set({
            casesLoading: false,
            casesLoadingMore: false,
            lastError: error.message,
          })
        }
      },
      async loadMoreCases() {
        const state = get()
        if (state.casesLoadingMore || !state.casesPagination?.hasMore) {
          return
        }
        await get().loadCases({ reset: false })
      },
      async loadCase(caseId, options = {}) {
        if (!caseId) {
          set({ caseDetail: null })
          return
        }

        const inFlight = CASE_DETAIL_IN_FLIGHT.get(caseId)
        if (inFlight) {
          set((state) => ({
            caseDetailInFlightById: {
              ...(state.caseDetailInFlightById || {}),
              [caseId]: true,
            },
          }))
          await inFlight
          const refreshed = get().caseDetailsById?.[caseId]
          if (refreshed) {
            set({ caseDetail: refreshed, caseDetailLoading: false, lastError: null })
          }
          return
        }

        const force = options?.force === true
        const cachedDetail = get().caseDetailsById?.[caseId]
        const cachedState = cachedDetail?.generation_state
        const cachedIsGenerating = cachedState === 'queued' || cachedState === 'running'

        if (cachedDetail && !force && !cachedIsGenerating) {
          set({ caseDetail: cachedDetail, caseDetailLoading: false, lastError: null })
          return
        }

        set((state) => ({
          caseDetailLoading: true,
          lastError: null,
          caseDetailInFlightById: {
            ...(state.caseDetailInFlightById || {}),
            [caseId]: true,
          },
        }))
        let requestPromise
        requestPromise = (async () => {
          try {
            const detail = await api.getCase(caseId)
            set((state) => {
              const groups = (state.caseGroups || []).map((group) => {
                const items = (group.items || []).map((item) => {
                  if (item.case_id !== caseId) {
                    return item
                  }
                  const nextState = detail?.generation_state || item.generation_state || item.status
                  return {
                    ...item,
                    symbol: detail?.request?.symbol || item.symbol,
                    timestamp_utc: detail?.request?.timestamp_utc || item.timestamp_utc,
                    generation_state: nextState,
                    status: nextState,
                    direction: detail?.proposal_validated?.long_short_none || item.direction,
                    confidence: detail?.proposal_validated?.confidence ?? item.confidence,
                  }
                })
                return { ...group, items }
              })
              return {
                caseDetail: detail,
                caseDetailLoading: false,
                caseGroups: pinRunningCaseToTop(groups, state.newlyCreatedCaseId),
                newlyCreatedCaseId: RUNNING_STATES.has(detail?.generation_state)
                  ? state.newlyCreatedCaseId
                  : state.newlyCreatedCaseId === caseId
                    ? null
                    : state.newlyCreatedCaseId,
                caseDetailsById: {
                  ...(state.caseDetailsById || {}),
                  [caseId]: detail,
                },
              }
            })
          } catch (error) {
            set({ caseDetailLoading: false, lastError: error.message })
          } finally {
            set((state) => {
              const nextInFlight = { ...(state.caseDetailInFlightById || {}) }
              delete nextInFlight[caseId]
              return { caseDetailInFlightById: nextInFlight }
            })
            if (CASE_DETAIL_IN_FLIGHT.get(caseId) === requestPromise) {
              CASE_DETAIL_IN_FLIGHT.delete(caseId)
            }
          }
        })()

        CASE_DETAIL_IN_FLIGHT.set(caseId, requestPromise)
        await requestPromise
      },
      async saveTrade(caseId, tradePayload) {
        set({ savingTrade: true, lastError: null })
        try {
          await api.saveTrade(caseId, tradePayload)
          await get().loadCase(caseId, { force: true })
          set({ savingTrade: false })
        } catch (error) {
          set({ savingTrade: false, lastError: error.message })
          throw error
        }
      },
      async deleteCase(caseId) {
        if (!caseId) {
          return
        }
        set({ lastError: null })
        try {
          await api.deleteCase(caseId)
          let nextSelectedFromDelete = null
          set((state) => {
            const itemsBeforeDelete = flattenCaseGroups(state.caseGroups)
            const deletedIndex = itemsBeforeDelete.findIndex((item) => item.case_id === caseId)
            const remainingItems = itemsBeforeDelete.filter((item) => item.case_id !== caseId)
            const remainingGroups = groupCaseItems(remainingItems)
            const previousCaseId = deletedIndex > 0 ? itemsBeforeDelete[deletedIndex - 1]?.case_id : null
            const nextCaseId = deletedIndex >= 0 ? itemsBeforeDelete[deletedIndex + 1]?.case_id : null
            const fallbackSelected = nextCaseId || previousCaseId || null
            const nextSelected = state.selectedCaseId === caseId
              ? fallbackSelected
              : state.selectedCaseId
            nextSelectedFromDelete = nextSelected
            const nextDetails = { ...(state.caseDetailsById || {}) }
            delete nextDetails[caseId]
            return {
              caseGroups: remainingGroups,
              selectedCaseId: nextSelected,
              caseDetail: state.caseDetail?.case_id === caseId ? null : state.caseDetail,
              caseDetailsById: nextDetails,
              newlyCreatedCaseId: state.newlyCreatedCaseId === caseId ? null : state.newlyCreatedCaseId,
              casesPagination: {
                ...state.casesPagination,
                total: Math.max(0, (state.casesPagination?.total || 0) - 1),
              },
            }
          })
          return nextSelectedFromDelete
        } catch (error) {
          set({ lastError: error.message })
          throw error
        }
      },
      async resizeWindowsDismissTVBanner(caseId, payload = {}) {
        if (!caseId) {
          return null
        }
        set({ resizingWindowsDismissTVBanner: true, lastError: null })
        try {
          const response = await api.resizeWindowsDismissTVBanner(caseId, payload)
          set({ resizingWindowsDismissTVBanner: false })
          return response
        } catch (error) {
          set({ resizingWindowsDismissTVBanner: false, lastError: error.message })
          throw error
        }
      },
      async createCaseForGeneration(payload) {
        set({ generatingCase: true, lastError: null })
        try {
          const created = await api.createCase()
          await api.triggerCaseGeneration(created.case_id, payload)
          const now = new Date().toISOString()
          set((state) => {
            const preview = {
              case_id: created.case_id,
              date: now.slice(0, 10),
              symbol: payload?.symbol || null,
              model: payload?.vision_model_pass2 || null,
              timestamp_utc: now,
              status: 'running',
              generation_state: 'running',
              direction: null,
              confidence: null,
            }
            const merged = mergeCaseGroups(state.caseGroups, groupCaseItems([preview]))
            return {
              generatingCase: false,
              selectedCaseId: created.case_id,
              newlyCreatedCaseId: created.case_id,
              caseGroups: pinRunningCaseToTop(merged, created.case_id),
            }
          })
          return {
            ...created,
            generation_request: payload,
          }
        } catch (error) {
          set({ generatingCase: false, lastError: error.message })
          throw error
        }
      },
      setSettings(partial) {
        set((state) => ({ settings: { ...state.settings, ...partial } }))
      },
      updateProviderModel(provider, phase, model) {
        set((state) => ({
          settings: {
            ...state.settings,
            providerDefaults: {
              ...state.settings.providerDefaults,
              [provider]: {
                ...state.settings.providerDefaults[provider],
                [phase]: model,
              },
            },
          },
        }))
      },
      toggleChart(chartTf) {
        set((state) => {
          const current = state.settings.chartsEnabled.timeframes
          const exists = current.includes(chartTf)
          const next = exists ? current.filter((tf) => tf !== chartTf) : [...current, chartTf]
          return {
            settings: {
              ...state.settings,
              chartsEnabled: {
                ...state.settings.chartsEnabled,
                timeframes: next,
              },
            },
          }
        })
      },
      toggleLiquidationChart() {
        set((state) => ({
          settings: {
            ...state.settings,
            chartsEnabled: {
              ...state.settings.chartsEnabled,
              liquidation_heatmap: !state.settings.chartsEnabled.liquidation_heatmap,
            },
          },
        }))
      },
    }),
    {
      name: 'iawwai-ui-store',
      partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
        settings: state.settings,
      }),
    },
  ),
)
