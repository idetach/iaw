import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Box,
  Button,
  Flex,
  HStack,
  Spinner,
  Text,
  VStack,
} from '@chakra-ui/react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAppStore } from '../../store/useAppStore'
import { api } from '../../lib/api'

// Group conductor case items by tick — same group shape as the store's
// caseGroups ({date, items}) so the rendering below stays identical.
function tickLabel(tickId, fallbackDate) {
  // tick-20260726T120000Z-abc123 -> "2026-07-26 12:00Z"
  const m = /^tick-(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})/.exec(tickId || '')
  if (!m) return fallbackDate || tickId || 'unknown'
  return `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}Z`
}

function groupByTick(items) {
  const byTick = new Map()
  for (const item of items || []) {
    const key = item?.tick_id || 'unknown'
    if (!byTick.has(key)) byTick.set(key, [])
    byTick.get(key).push(item)
  }
  return [...byTick.entries()]
    .sort(([a], [b]) => b.localeCompare(a)) // tick ids embed the timestamp
    .map(([tickId, groupItems]) => ({
      date: tickLabel(tickId, groupItems[0]?.date),
      items: groupItems,
    }))
}

export default function Sidebar() {
  const sidebarCollapsed = useAppStore((s) => s.sidebarCollapsed)
  const toggleSidebar = useAppStore((s) => s.toggleSidebar)
  const caseGroups = useAppStore((s) => s.caseGroups)
  const casesPagination = useAppStore((s) => s.casesPagination)
  const selectedCaseId = useAppStore((s) => s.selectedCaseId)
  const newlyCreatedCaseId = useAppStore((s) => s.newlyCreatedCaseId)
  const selectCase = useAppStore((s) => s.selectCase)
  const casesLoading = useAppStore((s) => s.casesLoading)
  const casesLoadingMore = useAppStore((s) => s.casesLoadingMore)
  const loadMoreCases = useAppStore((s) => s.loadMoreCases)
  const caseDetailsById = useAppStore((s) => s.caseDetailsById)
  const navigate = useNavigate()
  const location = useLocation()

  const isCasesRoute = location.pathname.startsWith('/cases')
  const isCasesPage = location.pathname === '/cases'
  const isConductorRoute = location.pathname.startsWith('/conductor')
  const selectedConductorCase = isConductorRoute
    ? new URLSearchParams(location.search).get('case')
    : null

  const width = sidebarCollapsed ? '58px' : '296px'

  const grouped = useMemo(() => caseGroups || [], [caseGroups])

  // --- conductor cases (cases-auto prefix, served by the conductor svc) ----
  const [conductorCases, setConductorCases] = useState([])
  const [conductorLoading, setConductorLoading] = useState(false)
  const [conductorHasMore, setConductorHasMore] = useState(false)

  const loadConductorCases = useCallback(async (offset = 0) => {
    setConductorLoading(offset === 0)
    try {
      const data = await api.listConductorCases({ limit: 30, offset })
      setConductorCases((prev) =>
        offset === 0 ? data.items || [] : [...prev, ...(data.items || [])],
      )
      setConductorHasMore(Boolean(data.hasMore))
    } catch {
      if (offset === 0) setConductorCases([])
    } finally {
      setConductorLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!isConductorRoute) return undefined
    loadConductorCases(0)
    const onTickDone = () => loadConductorCases(0)
    window.addEventListener('conductor-tick-done', onTickDone)
    return () => window.removeEventListener('conductor-tick-done', onTickDone)
  }, [isConductorRoute, loadConductorCases])

  const conductorGrouped = useMemo(() => groupByTick(conductorCases), [conductorCases])

  function tradeStateDot(item) {
    const detail = caseDetailsById?.[item.case_id]
    // conductor items carry `executed` directly; manual cases use trade_execution
    const hasExecution =
      item.executed !== undefined ? Boolean(item.executed) : Boolean(detail?.trade_execution)
    const direction = item.direction || detail?.proposal_validated?.long_short_none
    if (!direction || direction === 'NONE') return null
    const color = direction === 'LONG' ? '#48BB78' : '#FC8181'
    const opacity = hasExecution ? 1 : 0.35
    return (
      <Box
        as="span"
        display="inline-block"
        w="7px"
        h="7px"
        borderRadius="full"
        bg={color}
        opacity={opacity}
        flexShrink={0}
        title={hasExecution ? `${direction} (executed)` : `${direction} (proposal)`}
      />
    )
  }

  return (
    <Box
      w={width}
      minW={width}
      borderRight="1px solid"
      borderColor="brand.border"
      bg="#070707"
      transition="width 160ms ease"
      display="flex"
      flexDirection="column"
    >
      <Flex p={2} gap={isCasesPage ? 7 : 2} borderBottom="1px solid" borderColor="brand.border">
        <Button
          variant="ghostline"
          onClick={toggleSidebar}
          minW="40px"
          h="30px"
          px={0}
        >
          {sidebarCollapsed ? '>' : '<'}
        </Button>
        {isCasesPage && (
          <Button
            variant="action"
            minW="30px"
            h="30px"
            px={0}
            fontSize="24px"
            fontWeight="320"
            lineHeight="1"
            display="inline-flex"
            alignItems="center"
            justifyContent="center"
            pb="2px"
            onClick={() => navigate('/cases/new')}
          >
            +
          </Button>
        )}
      </Flex>

      <Box p={2} overflowY="auto" flex="1">
        {isConductorRoute ? (
          conductorLoading ? (
            <HStack px={2} py={3} color="gray.300">
              <Spinner size="sm" />
              {!sidebarCollapsed && <Text fontSize="sm">Loading cases...</Text>}
            </HStack>
          ) : !conductorGrouped.length ? (
            <Text fontSize="sm" color="gray.500" px={2}>
              No conductor cases yet — run a tick.
            </Text>
          ) : (
            <VStack align="stretch" spacing={3}>
              {conductorGrouped.map((group) => (
                <Box key={group.date}>
                  {!sidebarCollapsed && (
                    <Text fontSize="11px" color="gray.500" px={2} py={1}>
                      {group.date}
                    </Text>
                  )}
                  <VStack align="stretch" spacing={1}>
                    {(group.items || []).map((item) => {
                      const active = selectedConductorCase === item.case_id
                      return (
                        <Button
                          key={item.case_id}
                          variant="ghostline"
                          justifyContent={sidebarCollapsed ? 'center' : 'space-between'}
                          onClick={() =>
                            navigate(`/conductor?case=${encodeURIComponent(item.case_id)}`)
                          }
                          borderColor={active ? 'brand.yellow' : 'brand.border'}
                          color={active ? 'brand.yellow' : 'brand.white'}
                          px={sidebarCollapsed ? 0 : 2}
                        >
                          {sidebarCollapsed ? (
                            item.symbol?.slice(0, 1) || '•'
                          ) : (
                            <HStack w="full" justify="space-between">
                              <HStack spacing={2} minW={0} flex="1">
                                {tradeStateDot(item)}
                                <Text fontSize="xs" noOfLines={1} fontWeight="600">
                                  {item.symbol || item.case_id.slice(0, 8)}
                                </Text>
                                <Text fontSize="10px" color="gray.500" noOfLines={1}>
                                  {item.model || '-'}
                                </Text>
                              </HStack>
                              <Text fontSize="10px" color="gray.500" textTransform="lowercase">
                                {item.status}
                              </Text>
                            </HStack>
                          )}
                        </Button>
                      )
                    })}
                  </VStack>
                </Box>
              ))}
              {conductorHasMore && !sidebarCollapsed && (
                <Button
                  variant="ghostline"
                  size="sm"
                  onClick={() => loadConductorCases(conductorCases.length)}
                >
                  load next 30
                </Button>
              )}
            </VStack>
          )
        ) : !isCasesRoute ? (
          <Text fontSize="sm" color="gray.500" px={2}>
            Open cases page to browse cases.
          </Text>
        ) : casesLoading ? (
          <HStack px={2} py={3} color="gray.300">
            <Spinner size="sm" />
            {!sidebarCollapsed && <Text fontSize="sm">Loading cases...</Text>}
          </HStack>
        ) : (
          <VStack align="stretch" spacing={3}>
            {grouped.map((group) => (
              <Box key={group.date}>
                {!sidebarCollapsed && (
                  <Text fontSize="11px" color="gray.500" px={2} py={1}>
                    {group.date}
                  </Text>
                )}
                <VStack align="stretch" spacing={1}>
                  {(group.items || []).map((item) => {
                    const active = selectedCaseId === item.case_id
                    const itemState = item.generation_state || item.status
                    const isNewRunning = item.case_id === newlyCreatedCaseId && (itemState === 'queued' || itemState === 'running')
                    return (
                      <Button
                        key={item.case_id}
                        variant="ghostline"
                        justifyContent={sidebarCollapsed ? 'center' : 'space-between'}
                        onClick={() => {
                          selectCase(item.case_id)
                          navigate(`/cases?case=${item.case_id}`)
                        }}
                        borderColor={isNewRunning ? 'green.300' : active ? 'brand.yellow' : 'brand.border'}
                        color={isNewRunning ? 'green.300' : active ? 'brand.yellow' : 'brand.white'}
                        bg={isNewRunning ? 'rgba(154, 230, 180, 0.08)' : 'transparent'}
                        px={sidebarCollapsed ? 0 : 2}
                      >
                        {sidebarCollapsed ? (
                          item.symbol?.slice(0, 1) || '•'
                        ) : (
                          <HStack w="full" justify="space-between">
                            <HStack spacing={2} minW={0} flex="1">
                              {tradeStateDot(item)}
                              <Text fontSize="xs" noOfLines={1} fontWeight="600">
                                {item.symbol || item.case_id.slice(0, 8)}
                              </Text>
                              <Text fontSize="10px" color="gray.500" noOfLines={1}>
                                {item.model || '-'}
                              </Text>
                            </HStack>
                            <Text fontSize="10px" color="gray.500" textTransform="lowercase">
                              {item.status}
                            </Text>
                          </HStack>
                        )}
                      </Button>
                    )
                  })}
                </VStack>
              </Box>
            ))}

            {casesPagination?.hasMore && !sidebarCollapsed && (
              <Button
                variant="ghostline"
                size="sm"
                onClick={loadMoreCases}
                isLoading={casesLoadingMore}
              >
                load next 30
              </Button>
            )}
          </VStack>
        )}
      </Box>
    </Box>
  )
}
