import { useEffect, useRef, useState } from 'react'
import {
  Box,
  Button,
  Checkbox,
  FormControl,
  FormLabel,
  Heading,
  HStack,
  Select,
  SimpleGrid,
  Text,
  useToast,
  VStack,
} from '@chakra-ui/react'
import { api } from '../lib/api'
import { useAppStore } from '../store/useAppStore'
import { resolveTimeZone } from '../lib/datetime'

const providers = ['claude', 'openai', 'gemini']
const browserOwners = ['Firefox', 'Safari', 'Google Chrome', 'Arc', 'Brave Browser']
const timezoneOptions = [
  'UTC',
  'Europe/Tallinn',
  'Europe/London',
  'America/New_York',
  'America/Chicago',
  'Asia/Dubai',
  'Asia/Singapore',
  'Asia/Tokyo',
]
const DELETE_WARNING_MESSAGE = 'cases are stored for analytics by user and keeping cases benefits analytics'
const GRID_MIN_ROWS = 1
const GRID_MAX_ROWS = 3
const GRID_MIN_COLS = 2
const GRID_MAX_COLS = 3
const TILE_W = 180
const TILE_H = 90
const TILE_MOVE_TRANSITION_MS = 800
const ARRANGE_STEP_X = 1138
const ARRANGE_STEP_Y = 594

function windowKey(item) {
  return `${item.owner_name}::${item.window_name}::${item.window_id}`
}

function clamp(n, min, max) {
  return Math.min(max, Math.max(min, n))
}

export default function SettingsPage() {
  const toast = useToast()
  const settings = useAppStore((s) => s.settings)
  const meta = useAppStore((s) => s.meta)
  const setSettings = useAppStore((s) => s.setSettings)
  const updateProviderModel = useAppStore((s) => s.updateProviderModel)
  const toggleChart = useAppStore((s) => s.toggleChart)
  const toggleLiquidationChart = useAppStore((s) => s.toggleLiquidationChart)
  const [chartScreensOpen, setChartScreensOpen] = useState(false)
  const [loadingChartScreens, setLoadingChartScreens] = useState(false)
  const [arrangingChartScreens, setArrangingChartScreens] = useState(false)
  const [chartWindows, setChartWindows] = useState([])
  const [gridPositions, setGridPositions] = useState({})
  const [dragState, setDragState] = useState(null)
  const [gridRows, setGridRows] = useState(2)
  const [gridCols, setGridCols] = useState(2)
  const gridRef = useRef(null)

  const providerModels = meta?.providers || {}
  const allCharts = meta?.timeframes || ['1m', '5m', '15m', '30m', '1h', '4h']
  const localTimezone = resolveTimeZone('local')
  const gridPixelWidth = gridCols * TILE_W
  const gridPixelHeight = gridRows * TILE_H

  const onToggleSettingWithWarning = (key) => {
    const ok = window.confirm(DELETE_WARNING_MESSAGE)
    if (!ok) {
      return
    }
    setSettings({ [key]: !settings[key] })
  }

  const openChartScreens = async () => {
    setLoadingChartScreens(true)
    try {
      const result = await api.listTradingViewWindows()
      const windows = (result?.windows || []).slice().sort((a, b) => {
        const ay = Number(a?.bounds?.Y || 0)
        const by = Number(b?.bounds?.Y || 0)
        if (ay !== by) {
          return ay - by
        }
        const ax = Number(a?.bounds?.X || 0)
        const bx = Number(b?.bounds?.X || 0)
        if (ax !== bx) {
          return ax - bx
        }
        return String(a.window_name || '').localeCompare(String(b.window_name || ''))
      })
      const nextPositions = {}
      windows.forEach((item, idx) => {
        nextPositions[windowKey(item)] = {
          col: idx % gridCols,
          row: Math.floor(idx / gridCols) % gridRows,
        }
      })
      setChartWindows(windows)
      setGridPositions(nextPositions)
      setChartScreensOpen(true)
    } catch (error) {
      toast({
        status: 'error',
        title: 'Failed to load TradingView windows',
        description: error.message,
      })
    } finally {
      setLoadingChartScreens(false)
    }
  }

  const onDragStart = (e, key) => {
    const current = gridPositions[key]
    if (!current) {
      return
    }
    const tileLeft = current.col * TILE_W
    const tileTop = current.row * TILE_H
    const gridRect = gridRef.current?.getBoundingClientRect()
    if (!gridRect) {
      return
    }
    setDragState({
      key,
      startCol: current.col,
      startRow: current.row,
      offsetX: e.clientX - (gridRect.left + tileLeft),
      offsetY: e.clientY - (gridRect.top + tileTop),
      x: tileLeft,
      y: tileTop,
    })
  }

  useEffect(() => {
    if (!dragState) {
      return undefined
    }
    const onMove = (e) => {
      const gridRect = gridRef.current?.getBoundingClientRect()
      if (!gridRect) {
        return
      }
      const maxX = gridPixelWidth - TILE_W
      const maxY = gridPixelHeight - TILE_H
      const x = clamp(e.clientX - gridRect.left - dragState.offsetX, 0, maxX)
      const y = clamp(e.clientY - gridRect.top - dragState.offsetY, 0, maxY)
      setDragState((prev) => (prev ? { ...prev, x, y } : prev))
    }
    const onUp = () => {
      setGridPositions((prev) => {
        const next = { ...prev }
        const col = clamp(Math.round(dragState.x / TILE_W), 0, gridCols - 1)
        const row = clamp(Math.round(dragState.y / TILE_H), 0, gridRows - 1)
        const dragKey = dragState.key
        const sourceCol = dragState.startCol
        const sourceRow = dragState.startRow

        let occupantKey = null
        for (const [key, pos] of Object.entries(next)) {
          if (key === dragKey) {
            continue
          }
          if (Number(pos?.col) === col && Number(pos?.row) === row) {
            occupantKey = key
            break
          }
        }

        if (occupantKey) {
          next[occupantKey] = { col: sourceCol, row: sourceRow }
        }
        next[dragKey] = { col, row }
        return next
      })
      setDragState(null)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [dragState, gridCols, gridRows, gridPixelHeight, gridPixelWidth])

  useEffect(() => {
    setGridPositions((prev) => {
      const next = {}
      for (const [key, pos] of Object.entries(prev)) {
        next[key] = {
          col: clamp(Number(pos?.col || 0), 0, gridCols - 1),
          row: clamp(Number(pos?.row || 0), 0, gridRows - 1),
        }
      }
      return next
    })
  }, [gridCols, gridRows])

  const confirmChartScreenArrangement = async () => {
    setArrangingChartScreens(true)
    try {
      const placements = chartWindows.map((item) => {
        const key = windowKey(item)
        const pos = gridPositions[key] || { col: 0, row: 0 }
        return {
          window_id: item.window_id,
          owner_name: item.owner_name,
          window_name: item.window_name,
          col: pos.col,
          row: pos.row,
        }
      })
      const result = await api.arrangeTradingViewWindows({
        step_x: ARRANGE_STEP_X,
        step_y: ARRANGE_STEP_Y,
        horizontal_visibility: settings.chartScreensHorizontalVisibility || 'right',
        vertical_visibility: settings.chartScreensVerticalVisibility || 'top',
        resize_windows: settings.chartScreensResizeOnArrange !== false,
        one_stack: settings.chartScreensOneStack === true,
        show_window_on_arrange: settings.chartScreensShowWindowOnResize === true,
        app_window: settings.appWindow || 'auto',
        placements,
      })
      toast({
        status: 'success',
        title: 'Chart screens arranged',
        description: `Moved ${result.arranged || 0} of ${result.requested || placements.length} windows`,
      })
      setChartScreensOpen(false)
    } catch (error) {
      toast({
        status: 'error',
        title: 'Failed to arrange chart screens',
        description: error.message,
      })
    } finally {
      setArrangingChartScreens(false)
    }
  }

  return (
    <VStack align="stretch" spacing={4}>
      <Heading size="md">Settings</Heading>

      <SimpleGrid columns={{ base: 1, md: 4 }} spacing={3}>

        <Box bg="brand.card" border="1px solid" borderColor="brand.border" borderRadius="12px" p={4}>
          <Text textTransform="none" color="brand.yellow" mb={3}>
            Vision Setup
          </Text>
          <VStack align="stretch" spacing={3}>
            <FormControl maxW="320px">
              <FormLabel color="gray.400">Default model provider</FormLabel>
              <Select
                value={settings.defaultProvider}
                bg="#111"
                borderColor="brand.border"
                onChange={(e) => setSettings({ defaultProvider: e.target.value })}
              >
                {providers.map((provider) => (
                  <option key={provider} value={provider}>
                    {provider}
                  </option>
                ))}
              </Select>
            </FormControl>
            
          </VStack>
        </Box>

        {providers.map((provider) => {
          const options = providerModels[provider]?.available_models || []
          return (
            <Box
              key={provider}
              bg="brand.card"
              border="1px solid"
              borderColor="brand.border"
              borderRadius="12px"
              p={4}
            >
              <Text textTransform="capitalize" color="brand.yellow" mb={3}>
                {provider}
              </Text>
              <VStack align="stretch" spacing={3}>
                <FormControl>
                  <FormLabel color="gray.400" fontSize="sm">
                    Model pass 1
                  </FormLabel>
                  <Select
                    value={settings.providerDefaults[provider]?.pass1 || ''}
                    bg="#111"
                    borderColor="brand.border"
                    onChange={(e) => updateProviderModel(provider, 'pass1', e.target.value)}
                  >
                    {options.map((model) => (
                      <option key={model} value={model}>
                        {model}
                      </option>
                    ))}
                  </Select>
                </FormControl>

                <FormControl>
                  <FormLabel color="gray.400" fontSize="sm">
                    Model pass 2
                  </FormLabel>
                  <Select
                    value={settings.providerDefaults[provider]?.pass2 || ''}
                    bg="#111"
                    borderColor="brand.border"
                    onChange={(e) => updateProviderModel(provider, 'pass2', e.target.value)}
                  >
                    {options.map((model) => (
                      <option key={model} value={model}>
                        {model}
                      </option>
                    ))}
                  </Select>
                </FormControl>
              </VStack>
            </Box>
          )
        })}
      </SimpleGrid>

      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={3}>
        <Box bg="brand.card" border="1px solid" borderColor="brand.border" borderRadius="12px" p={4}>
          <VStack align="stretch" spacing={4}>
            <HStack justify="space-between" align="center">
              <Text textTransform="none" color="brand.yellow" mb={3}>
                Chart Views
              </Text>
              <HStack spacing={10}>

                <Checkbox
                  isChecked={settings.chartScreensResizeOnArrange !== false}
                  onChange={(e) => setSettings({ chartScreensResizeOnArrange: e.target.checked })}
                  size="sm"
                >
                  Resize
                </Checkbox>

                {/* TODO: Remove this checkbox when decide not to show, difficult to resize windows in background */}
                {/* <Checkbox
                  isChecked={settings.chartScreensShowWindowOnResize === true}
                  onChange={(e) => setSettings({ chartScreensShowWindowOnResize: e.target.checked })}
                  size="sm"
                >
                  Show window on arrange
                </Checkbox> */}

                <Checkbox
                  isChecked={settings.chartScreensOneStack === true}
                  onChange={(e) => setSettings({ chartScreensOneStack: e.target.checked })}
                  size="sm"
                >
                  One Stack
                </Checkbox>

                <Button variant="action" size="sm" onClick={openChartScreens} isLoading={loadingChartScreens}>
                  Arrange
                </Button>
              </HStack>
            </HStack>

            {chartScreensOpen ? (
              <VStack align="stretch" spacing={3}>
                <Text color="gray.400" fontSize="sm">
                  {settings.chartScreensOneStack === true
                    ? 'All filtered TradingView windows will be stacked to the same top-left anchor on one desktop.'
                    : `Drag previews to arrange on a ${gridCols}x${gridRows} snap grid, then confirm to place actual TradingView windows.`}
                </Text>
                
                <HStack align="stretch" justify="space-between" spacing={10}>
                  <VStack align="flex-end" spacing={10}>
                    <HStack spacing={4}>
                      <Text color="gray.400" fontSize="s">
                        Grid
                      </Text>
                      <HStack spacing={1}>
                        <Text color="gray.400" fontSize="xs">
                          W
                        </Text>
                        <Select
                          size="sm"
                          w="74px"
                          value={String(gridCols)}
                          onChange={(e) => setGridCols(Number(e.target.value))}
                          isDisabled={settings.chartScreensOneStack === true}
                          borderColor="brand.border"
                          bg="#111"
                        >
                          {Array.from({ length: GRID_MAX_COLS - GRID_MIN_COLS + 1 }, (_, idx) => GRID_MIN_COLS + idx).map((n) => (
                            <option key={`cols-${n}`} value={String(n)}>
                              {n}
                            </option>
                          ))}
                        </Select>
                      </HStack>
                      <HStack spacing={1}>
                        <Text color="gray.400" fontSize="xs">
                          H
                        </Text>
                        <Select
                          size="sm"
                          w="74px"
                          value={String(gridRows)}
                          onChange={(e) => setGridRows(Number(e.target.value))}
                          isDisabled={settings.chartScreensOneStack === true}
                          borderColor="brand.border"
                          bg="#111"
                        >
                          {Array.from({ length: GRID_MAX_ROWS - GRID_MIN_ROWS + 1 }, (_, idx) => GRID_MIN_ROWS + idx).map((n) => (
                            <option key={`rows-${n}`} value={String(n)}>
                              {n}
                            </option>
                          ))}
                        </Select>
                      </HStack>
                    </HStack>

                    <HStack spacing={4}>
                      <Text color="gray.400" fontSize="s">
                        Visibility
                      </Text>
                      <HStack spacing={1}>
                        <Text color="gray.400" fontSize="xs">
                          X
                        </Text>
                        <Select
                          size="sm"
                          w="74px"
                          value={settings.chartScreensHorizontalVisibility || 'right'}
                          onChange={(e) => setSettings({ chartScreensHorizontalVisibility: e.target.value })}
                          isDisabled={settings.chartScreensOneStack === true}
                          borderColor="brand.border"
                          bg="#111"
                        >
                          <option value="right">→</option>
                          <option value="left">←</option>
                        </Select>
                      </HStack>

                      <HStack spacing={1}>
                        <Text color="gray.400" fontSize="xs">
                          Y
                        </Text>
                        <Select
                          size="sm"
                          w="74px"
                          value={settings.chartScreensVerticalVisibility || 'top'}
                          onChange={(e) => setSettings({ chartScreensVerticalVisibility: e.target.value })}
                          isDisabled={settings.chartScreensOneStack === true}
                          borderColor="brand.border"
                          bg="#111"
                        >
                          <option value="top">↑</option>
                          <option value="bottom">↓</option>
                        </Select>
                      </HStack>
                    </HStack>
                  </VStack>
                  
                  <Box overflowX="auto" border="1px solid" borderColor="brand.border" borderRadius="10px" p={2}>
                    <Box
                      ref={gridRef}
                      position="relative"
                      width={`${gridPixelWidth}px`}
                      height={`${gridPixelHeight}px`}
                      bg="#0d0d0d"
                      backgroundImage={`
                        linear-gradient(to right, rgba(255,255,255,0.08) 1px, transparent 1px),
                        linear-gradient(to bottom, rgba(255,255,255,0.08) 1px, transparent 1px)
                      `}
                      backgroundSize={`${TILE_W}px ${TILE_H}px`}
                    >
                      {chartWindows.map((item) => {
                        const key = windowKey(item)
                        const pos = gridPositions[key] || { col: 0, row: 0 }
                        const isDragging = dragState?.key === key
                        const left = isDragging ? dragState.x : pos.col * TILE_W
                        const top = isDragging ? dragState.y : pos.row * TILE_H
                        return (
                          <Box
                            key={key}
                            position="absolute"
                            left={`${left}px`}
                            top={`${top}px`}
                            width={`${TILE_W}px`}
                            height={`${TILE_H}px`}
                            border="1px solid"
                            borderColor={isDragging ? 'brand.yellow' : 'brand.border'}
                            borderRadius="8px"
                            overflow="hidden"
                            cursor={isDragging ? 'grabbing' : 'grab'}
                            pointerEvents={settings.chartScreensOneStack === true ? 'none' : 'auto'}
                            userSelect="none"
                            onMouseDown={settings.chartScreensOneStack === true ? undefined : (e) => onDragStart(e, key)}
                            zIndex={isDragging ? 20 : 10}
                            boxShadow={isDragging ? '0 0 0 1px #f6e05e' : 'none'}
                            transition={isDragging ? 'none' : `left ${TILE_MOVE_TRANSITION_MS}ms ease, top ${TILE_MOVE_TRANSITION_MS}ms ease`}
                          >
                            <Box
                              as="img"
                              src={`data:image/png;base64,${item.preview_png_base64}`}
                              alt={item.window_name}
                              width="100%"
                              height="100%"
                              objectFit="cover"
                              draggable={false}
                            />
                            <Box
                              position="absolute"
                              left="0"
                              top="0"
                              width="100%"
                              bg="rgba(0,0,0,0.58)"
                              px={1}
                              py={0.5}
                            >
                              <Text color="brand.yellow" fontWeight="700" fontSize="11px" noOfLines={1}>
                                {item.window_name}
                              </Text>
                            </Box>
                          </Box>
                        )
                      })}
                    </Box>
                  </Box>
                </HStack>

                <HStack justify="flex-end">
                  <Button variant="outline" size="sm" onClick={() => setChartScreensOpen(false)}>
                    Cancel
                  </Button>
                  <Button
                    variant="action"
                    size="sm"
                    onClick={confirmChartScreenArrangement}
                    isLoading={arrangingChartScreens}
                  >
                    Confirm
                  </Button>
                </HStack>
              </VStack>
            ) : null}
          </VStack>
        </Box>

          <Box bg="brand.card" border="1px solid" borderColor="brand.border" borderRadius="12px" p={4}>

            <Text textTransform="none" color="brand.yellow" mb={3}>
              Charts Apps & Browsers
            </Text>

            <HStack align="flex-start" justify="space-between" spacing={10}>

              <VStack align="stretch" spacing={2} pt={4}>
                <Checkbox isChecked={settings.chartsEnabled.liquidation_heatmap} onChange={toggleLiquidationChart}>
                  Liquidation Heatmap
                </Checkbox>
                {allCharts.map((tf) => (
                  <Checkbox
                    key={tf}
                    isChecked={settings.chartsEnabled.timeframes.includes(tf)}
                    onChange={() => toggleChart(tf)}
                  >
                    {tf}
                  </Checkbox>
                ))}


                <VStack align="stretch" spacing={2} pt={5}>
                  
                  <Checkbox
                    isChecked={Boolean(settings.tvResizeAndDismissBanner)}
                    onChange={() => setSettings({ tvResizeAndDismissBanner: !settings.tvResizeAndDismissBanner })}
                  >
                    Resize TradingView and Dismiss banner
                  </Checkbox>

                  {/* <Checkbox
                    isChecked={Boolean(settings.tvCalibrateWindowSize)}
                    onChange={() => setSettings({ tvCalibrateWindowSize: !settings.tvCalibrateWindowSize })}
                  >
                    Resize TradingView
                  </Checkbox>

                  <Checkbox
                    isChecked={settings.dismissTvBanner !== false}
                    onChange={(e) => setSettings({ dismissTvBanner: e.target.checked })}
                  >
                    Dismiss TradingView banner
                  </Checkbox> */}

                  {/* TODO: Remove this checkbox when decide not to show, difficult to resize windows in background */}
                  {/* <Checkbox
                    isChecked={Boolean(settings.showTvWindowOnCalibration)}
                    onChange={() => setSettings({ showTvWindowOnCalibration: !settings.showTvWindowOnCalibration })}
                    isDisabled={!settings.tvCalibrateWindowSize}
                  >
                    Show TradingView on resize
                  </Checkbox> */}

                </VStack>
              </VStack>

              <VStack align="flex-start" pt={4}>

                <FormControl maxW="320px">
                  <FormLabel color="gray.400">Liquidation Heatmap browser</FormLabel>
                  <Select
                    value={settings.liquidationHeatmapWindowOwner || 'Safari'}
                    bg="#111"
                    borderColor="brand.border"
                    onChange={(e) => setSettings({ liquidationHeatmapWindowOwner: e.target.value })}
                  >
                    {browserOwners.map((owner) => (
                      <option key={owner} value={owner}>
                        {owner}
                      </option>
                    ))}
                  </Select>
                </FormControl>

                <FormControl maxW="320px">
                  <FormLabel color="gray.400">iaWwai app browser after image capture</FormLabel>
                  <Select
                    value={settings.appWindow || 'auto'}
                    bg="#111"
                    borderColor="brand.border"
                    onChange={(e) => setSettings({ appWindow: e.target.value })}
                  >
                    <option value="auto">Auto-detect current browser</option>
                    {browserOwners.map((owner) => (
                      <option key={owner} value={owner}>
                        {owner}
                      </option>
                    ))}
                  </Select>
                </FormControl>

                <FormControl maxW="320px">
                  <FormLabel color="gray.400">Timezone</FormLabel>
                  <Select
                    value={settings.timezone || 'local'}
                    bg="#111"
                    borderColor="brand.border"
                    onChange={(e) => setSettings({ timezone: e.target.value })}
                  >
                    <option value="local">Local ({localTimezone})</option>
                    {timezoneOptions.map((tz) => (
                      <option key={tz} value={tz}>
                        {tz}
                      </option>
                    ))}
                  </Select>
                </FormControl>

              </VStack>

          </HStack>

          </Box>
      </SimpleGrid>

      <Box bg="brand.card" border="1px solid" borderColor="brand.border" borderRadius="12px" p={4}>
        <Text textTransform="none" color="red.500" mb={3}>
          Case Delete
        </Text>
        <Text color="orange.200" fontSize="xs" mb={3}>
          {DELETE_WARNING_MESSAGE}
        </Text>
        <VStack align="stretch" spacing={2}>
          <Checkbox
            isChecked={Boolean(settings.enableCaseDelete)}
            onChange={() => onToggleSettingWithWarning('enableCaseDelete')}
          >
            enable case delete
          </Checkbox>
          <Checkbox
            isChecked={Boolean(settings.deleteOnlyFailedCases)}
            onChange={() => onToggleSettingWithWarning('deleteOnlyFailedCases')}
          >
            delete only failed cases
          </Checkbox>
        </VStack>
      </Box>
    </VStack>
  )
}
