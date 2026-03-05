import { useEffect, useMemo } from 'react'
import {
  Button,
  HStack,
  Skeleton,
  SkeletonText,
  Text,
  VStack,
} from '@chakra-ui/react'
import { useSearchParams } from 'react-router-dom'
import { useAppStore } from '../store/useAppStore'
import { api } from '../lib/api'
import SectionCard from '../components/cases/SectionCard'
import DataPairs from '../components/cases/DataPairs'
import { liquidationFields, pass2Fields, proposalFields } from '../components/cases/fieldSets'
import TradeFormCard from '../components/cases/TradeFormCard'
import ChartsGrid from '../components/cases/ChartsGrid'

function isGenerating(state) {
  return state === 'queued' || state === 'running'
}

function LoadingStripesCard({ title, includeImage = false }) {
  return (
    <SectionCard title={title}>
      <VStack align="stretch" spacing={3}>
        {includeImage && <Skeleton height="180px" startColor="gray.700" endColor="gray.600" />}
        <SkeletonText noOfLines={6} spacing="2" skeletonHeight="2" startColor="gray.700" endColor="gray.600" />
      </VStack>
    </SectionCard>
  )
}

export default function CasesPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const caseParam = searchParams.get('case')

  const selectedCaseId = useAppStore((s) => s.selectedCaseId)
  const selectCase = useAppStore((s) => s.selectCase)
  const loadCase = useAppStore((s) => s.loadCase)
  const deleteCase = useAppStore((s) => s.deleteCase)
  const resizeWindowsDismissTVBanner = useAppStore((s) => s.resizeWindowsDismissTVBanner)
  const resizingWindowsDismissTVBanner = useAppStore((s) => s.resizingWindowsDismissTVBanner)
  const caseDetail = useAppStore((s) => s.caseDetail)
  const caseDetailsById = useAppStore((s) => s.caseDetailsById)
  const caseDetailInFlightById = useAppStore((s) => s.caseDetailInFlightById)
  const caseDetailLoading = useAppStore((s) => s.caseDetailLoading)
  const lastError = useAppStore((s) => s.lastError)
  const settings = useAppStore((s) => s.settings)
  const caseGroups = useAppStore((s) => s.caseGroups)

  const activeCaseId = caseParam || selectedCaseId

  useEffect(() => {
    if (!activeCaseId) {
      return
    }
    if (activeCaseId !== selectedCaseId) {
      selectCase(activeCaseId)
    }
    loadCase(activeCaseId)
  }, [activeCaseId, loadCase, selectCase, selectedCaseId])

  const currentCaseDetail =
    (caseDetail?.case_id === activeCaseId ? caseDetail : null) ||
    (activeCaseId ? caseDetailsById?.[activeCaseId] || null : null)
  const proposal = currentCaseDetail?.proposal_validated || null
  const pass2 = currentCaseDetail?.llm_raw_pass2 || null
  const liquidation = currentCaseDetail?.liquidation_heatmap_observations || null
  const pass1 = currentCaseDetail?.pass1_observations || null
  const trade = currentCaseDetail?.trade || null
  const enabledTimeframes = settings?.chartsEnabled?.timeframes || []
  const selectedCaseSummary = useMemo(() => {
    for (const group of caseGroups || []) {
      const found = (group.items || []).find((item) => item.case_id === activeCaseId)
      if (found) {
        return found
      }
    }
    return null
  }, [activeCaseId, caseGroups])
  const generationState = currentCaseDetail?.generation_state || selectedCaseSummary?.generation_state || null
  const generationInProgress = isGenerating(generationState)
  const lowerCardsLoading = caseDetailLoading && Boolean(proposal)
  const deleteEnabled = Boolean(settings?.enableCaseDelete)
  const failedOnly = Boolean(settings?.deleteOnlyFailedCases)
  const canDeleteByState = !failedOnly || generationState === 'failed'
  const canDeleteCase = deleteEnabled && Boolean(activeCaseId) && canDeleteByState
  const activeSymbol = currentCaseDetail?.request?.symbol || selectedCaseSummary?.symbol || null
  const canResizeWindowsDismissTVBanner = Boolean(activeCaseId && activeSymbol)

  useEffect(() => {
    if (!activeCaseId || !generationInProgress) {
      return
    }

    const stream = new EventSource(api.streamUrl())
    const handle = (event) => {
      try {
        const payload = JSON.parse(event.data)
        if (payload?.case_id !== activeCaseId) {
          return
        }
        loadCase(activeCaseId, { force: true })
      } catch {
        // ignore malformed SSE payloads
      }
    }

    const eventTypes = [
      'generate_requested',
      'generation_started',
      'generation_triggered',
      'uploaded',
      'analyzed',
      'generation_failed',
      'created',
    ]
    eventTypes.forEach((type) => stream.addEventListener(type, handle))

    const backupPoll = window.setInterval(() => {
      loadCase(activeCaseId, { force: true })
    }, 10000)

    return () => {
      window.clearInterval(backupPoll)
      stream.close()
    }
  }, [activeCaseId, generationInProgress, loadCase])

  const hasAnyData = useMemo(() => {
    return Boolean(proposal || pass2 || liquidation || pass1)
  }, [proposal, pass2, liquidation, pass1])
  const hasCachedDetailForActiveCase = Boolean(activeCaseId && caseDetailsById?.[activeCaseId])
  const hasInFlightDetailForActiveCase = Boolean(activeCaseId && caseDetailInFlightById?.[activeCaseId])
  const activeCaseLoading =
    hasInFlightDetailForActiveCase ||
    (caseDetailLoading && !hasCachedDetailForActiveCase) ||
    (!currentCaseDetail && generationInProgress)
  const showFullSkeletonLayout = !hasAnyData && (caseDetailLoading || generationInProgress)

  if (!activeCaseId) {
    return (
      <VStack align="stretch" spacing={3}>
        <Text color="gray.300">No case selected. Pick a case on the left or create one with +.</Text>
      </VStack>
    )
  }

  return (
    <VStack align="stretch" spacing={3}>
      <HStack justify="space-between" wrap="wrap">
        <Text fontSize="md" fontWeight="400" pl="42px" color="gray.300">
          {activeCaseId}
        </Text>
        <HStack>
          {generationInProgress && (
            <Text fontSize="sm" color="green.300">
              {generationState}...
            </Text>
          )}
          <Button
            variant="ghostline"
            title="resizeWindowsDismissTVBanner"
            aria-label="resizeWindowsDismissTVBanner"
            isDisabled={!canResizeWindowsDismissTVBanner}
            isLoading={resizingWindowsDismissTVBanner}
            onClick={async () => {
              await resizeWindowsDismissTVBanner(activeCaseId, {
                symbol: activeSymbol,
                tv_resize_and_dismiss_banner: settings?.tvResizeAndDismissBanner,
                tv_calibrate_window_size: settings?.tvCalibrateWindowSize,
                show_tv_window_on_calibration: settings?.showTvWindowOnCalibration,
                dismiss_tv_banner: settings?.dismissTvBanner,
              })
            }}
            bg="#111"
            borderColor="brand.border"
            color="gray.200"
          >
            ⤢
          </Button>
          {deleteEnabled && (
            <Button
              variant="ghostline"
              isDisabled={!canDeleteCase}
              onClick={async () => {
                const ok = window.confirm('cases are stored for analytics by user and keeping cases benefits analytics')
                if (!ok) {
                  return
                }
                setSearchParams({})
                const nextCaseId = await deleteCase(activeCaseId)
                if (nextCaseId) {
                  setSearchParams({ case: nextCaseId })
                }
              }}
              bg="#111"
              borderColor="brand.border"
              color="gray.200"
              _hover={{
                bg: 'red.500',
                borderColor: 'red.500',
                color: 'white',
              }}
            >
              Delete
            </Button>
          )}
          {/* <Button
            variant="ghostline"
            onClick={() => {
              setSearchParams({ case: activeCaseId })
              loadCase(activeCaseId, { force: true })
            }}
          >
            refresh
          </Button> */}
        </HStack>
      </HStack>

      {/* {caseDetailLoading && hasAnyData && (
        <HStack color="gray.300">
          <Spinner size="sm" />
          <Text>Awaiting case data...</Text>
        </HStack>
      )} */}

      {lastError && <Text color="red.300">{lastError}</Text>}

      {showFullSkeletonLayout ? (
        <>
          <div className="case-grid">
            <LoadingStripesCard title="proposal_validated.json" />
            <LoadingStripesCard title="Trade Form" />
          </div>

          <div className="case-grid">
            <LoadingStripesCard title="Liquidation Heatmap" includeImage />
            <LoadingStripesCard title="llm_raw_pass2.json" />
          </div>

          <ChartsGrid
            chartUrls={{}}
            pass1={null}
            enabledTimeframes={enabledTimeframes}
            loading
          />
        </>
      ) : hasAnyData ? (
        <>
          <div className="case-grid">
            <SectionCard title="proposal_validated.json">
              <DataPairs fields={proposalFields} source={proposal || {}} />
            </SectionCard>
            <TradeFormCard caseId={activeCaseId} proposal={proposal || {}} existingTrade={trade} />
          </div>

          <div className="case-grid">
            {settings.chartsEnabled.liquidation_heatmap ? (
              liquidation || currentCaseDetail?.liquidation_heatmap_url ? (
                <SectionCard title="Liquidation Heatmap">
                  <VStack align="stretch" spacing={3}>
                    {currentCaseDetail?.liquidation_heatmap_url ? (
                      <img
                        src={currentCaseDetail.liquidation_heatmap_url}
                        alt="liquidation heatmap"
                        style={{ borderRadius: 8, border: '1px solid #262626', width: '100%' }}
                      />
                    ) : (
                      <Text color="gray.500" fontSize="sm">
                        Heatmap not available.
                      </Text>
                    )}
                    <DataPairs fields={liquidationFields} source={liquidation || {}} />
                  </VStack>
                </SectionCard>
              ) : lowerCardsLoading ? (
                <LoadingStripesCard title="Liquidation Heatmap" includeImage />
              ) : (
                <SectionCard title="Liquidation Heatmap">
                  <Text color="gray.500" fontSize="sm">
                    Heatmap not available.
                  </Text>
                </SectionCard>
              )
            ) : (
              <SectionCard title="Liquidation Heatmap">
                <Text color="gray.500" fontSize="sm">
                  Hidden in settings.
                </Text>
              </SectionCard>
            )}

            {pass2 ? (
              <SectionCard title="llm_raw_pass2.json">
                <DataPairs fields={pass2Fields} source={pass2 || {}} />
              </SectionCard>
            ) : lowerCardsLoading ? (
              <LoadingStripesCard title="llm_raw_pass2.json" />
            ) : (
              <SectionCard title="llm_raw_pass2.json">
                <Text color="gray.500" fontSize="sm">
                  Data not available yet.
                </Text>
              </SectionCard>
            )}
          </div>

          <ChartsGrid
            chartUrls={currentCaseDetail?.chart_urls || {}}
            pass1={pass1}
            enabledTimeframes={enabledTimeframes}
            loading={lowerCardsLoading && !pass1}
          />
        </>
      ) : activeCaseLoading ? (
        <SectionCard>
          <Text color="gray.300">Loading case data ...</Text>
        </SectionCard>
      ) : (
        <SectionCard title="Case">
          <Text color="gray.300">Data not available for this case.</Text>
        </SectionCard>
      )}
    </VStack>
  )
}
