import { useMemo } from 'react'
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
  const navigate = useNavigate()
  const location = useLocation()

  const isCasesRoute = location.pathname.startsWith('/cases')
  const isCasesPage = location.pathname === '/cases'

  const width = sidebarCollapsed ? '58px' : '296px'

  const grouped = useMemo(() => caseGroups || [], [caseGroups])

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
        {!isCasesRoute ? (
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
