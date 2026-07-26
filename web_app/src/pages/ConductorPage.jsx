import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  Badge,
  Box,
  Button,
  Code,
  Flex,
  Grid,
  HStack,
  Spinner,
  Switch,
  Text,
  VStack,
  useToast,
} from '@chakra-ui/react'
import { api } from '../lib/api'

// ---------------------------------------------------------------------------
// Metro-map step definitions
// ---------------------------------------------------------------------------

const STEPS = [
  { key: 'scanned', label: 'scanned', color: '#A0AEC0' }, // gray.400
  { key: 'gate', label: 'gate', color: '#4FD1C5' }, // teal.300
  { key: 'proposal', label: 'proposals', color: '#B794F4' }, // purple.300
  { key: 'approved', label: 'approved', color: '#F6E05E' }, // yellow.300
  { key: 'executed', label: 'executed', color: '#68D391' }, // green.300
  { key: 'managed', label: 'positions managed', color: '#63B3ED' }, // blue.300
]
const STEP_INDEX = Object.fromEntries(STEPS.map((s, i) => [s.key, i]))

// ---------------------------------------------------------------------------
// Tick event stream -> per-asset roadmap state
// ---------------------------------------------------------------------------

const initialTick = {
  running: false,
  assets: {}, // symbol -> { source, stepIndex, rejected, error, steps: {key: {reason, ...}} }
  order: [], // symbol display order
  portfolio: null,
  errors: [],
  halted: false,
  finished: false,
  events: [], // raw stream events, in arrival order
}

function upsert(state, symbol, patch, stepKey, stepData) {
  const prev = state.assets[symbol] || {
    source: 'watchlist',
    stepIndex: -1,
    rejected: false,
    error: null,
    steps: {},
  }
  const next = {
    ...prev,
    ...patch,
    steps: stepKey ? { ...prev.steps, [stepKey]: stepData } : prev.steps,
  }
  return {
    ...state,
    assets: { ...state.assets, [symbol]: next },
    order: state.order.includes(symbol) ? state.order : [...state.order, symbol],
  }
}

function tickReducer(state, ev) {
  switch (ev.type) {
    case 'reset':
      return { ...initialTick, running: true }
    case 'stream': {
      const e = ev.payload
      state = { ...state, events: [...state.events, e] }
      switch (e.event) {
        case 'portfolio':
          return {
            ...state,
            portfolio: e,
            errors: e.error ? [...state.errors, `portfolio: ${e.error}`] : state.errors,
          }
        case 'order':
          return upsert(
            state,
            e.symbol,
            { source: 'order', stepIndex: STEP_INDEX.managed, rejected: Boolean(e.cancelled) },
            'managed',
            {
              reason: `resting order ${e.action}${e.cancelled ? ' (cancelled)' : ''}: ${e.reason}\n${e.side} ${e.qty} @ ${e.price}`,
            },
          )
        case 'lifecycle':
          return upsert(
            state,
            e.symbol,
            { source: 'position', stepIndex: STEP_INDEX.managed },
            'managed',
            {
              reason: `${e.action}: ${e.reason}`,
              side: e.side,
              size: e.size,
              pnl: e.unrealised_pnl,
              newStop: e.new_stop,
            },
          )
        case 'candidates': {
          let s = state
          for (const sym of e.symbols || []) {
            s = upsert(s, sym, { source: e.sources?.[sym] || 'watchlist' }, 'scanned', {
              reason: `queued from ${e.sources?.[sym] || 'watchlist'}`,
              pending: true,
            })
          }
          return s
        }
        case 'scanned':
          return upsert(
            state,
            e.symbol,
            { stepIndex: STEP_INDEX.scanned },
            'scanned',
            { reason: e.summary || `snapshot built (${(e.timeframes || []).join(', ')})` },
          )
        case 'gate':
          return upsert(
            state,
            e.symbol,
            { stepIndex: STEP_INDEX.gate, rejected: !e.passed },
            'gate',
            { reason: e.reason, passed: e.passed },
          )
        case 'proposal': {
          const abstain = e.direction === 'NONE'
          return upsert(
            state,
            e.symbol,
            { stepIndex: STEP_INDEX.proposal, rejected: abstain },
            'proposal',
            {
              reason: abstain
                ? `abstained: ${e.reason}`
                : `${e.direction} @ ${e.entry_min}–${e.entry_max} · SL ${e.stop_loss} · TP ${e.target_price} · conf ${e.confidence} · ${e.duration || ''}\n${e.reason}`,
              direction: e.direction,
            },
          )
        }
        case 'governor': {
          const rejected = e.action === 'REJECT'
          const a = e.audit || {}
          return upsert(
            state,
            e.symbol,
            { stepIndex: STEP_INDEX.approved, rejected },
            'approved',
            {
              reason: rejected
                ? `governor rejected: ${e.reject_reason}`
                : `${e.action} · qty ${Number(e.qty).toFixed(6)} · ${e.leverage}x · risk $${(a.risk_usdt ?? 0).toFixed(2)} · margin $${(a.margin_needed ?? 0).toFixed(2)}\n${e.reason || ''}`,
              action: e.action,
            },
          )
        }
        case 'executed':
          return upsert(
            state,
            e.symbol,
            { stepIndex: STEP_INDEX.executed, rejected: !e.placed && false },
            'executed',
            { reason: e.reason, placed: e.placed },
          )
        case 'error':
          if (e.symbol) {
            return upsert(
              state,
              e.symbol,
              { error: e.message },
              null,
              null,
            )
          }
          return { ...state, errors: [...state.errors, `${e.scope}: ${e.message}`] }
        case 'halted':
          return { ...state, halted: true }
        case 'done':
          return { ...state, running: false, finished: true }
        default:
          return state
      }
    }
    case 'stopped':
      return { ...state, running: false }
    default:
      return state
  }
}

// Build a roadmap asset from a persisted GCS case artifact (same shape the
// live reducer produces, so <Roadmap /> renders both identically).
function assetFromCase(c) {
  const steps = {}
  let stepIndex = -1
  let rejected = false
  if (c.snapshot) {
    const summary = (c.snapshot.timeframes || [])
      .map((t) => (t.notes || '').split(';')[0])
      .filter(Boolean)
      .join('; ')
    steps.scanned = { reason: summary || 'snapshot built' }
    stepIndex = STEP_INDEX.scanned
  }
  if (c.gate) {
    const passed = Boolean(c.gate.plausible)
    steps.gate = {
      reason: passed ? c.gate.setup_hint || '' : c.gate.reject_reason || '',
      passed,
    }
    stepIndex = STEP_INDEX.gate
    rejected = !passed
  }
  if (c.proposal) {
    const p = c.proposal
    const abstain = p.long_short_none === 'NONE'
    steps.proposal = {
      reason: abstain
        ? `abstained: ${p.reason_abstain || ''}`
        : `${p.long_short_none} @ ${p.entry_price_min}–${p.entry_price_max} · SL ${p.stop_loss} · TP ${p.target_price} · conf ${p.confidence} · ${p.position_duration || ''}\n${p.reason_entry || ''}`,
      direction: p.long_short_none,
    }
    stepIndex = STEP_INDEX.proposal
    rejected = abstain
  }
  if (c.governor) {
    const g = c.governor
    const rej = g.action === 'REJECT'
    const a = g.audit || {}
    steps.approved = {
      reason: rej
        ? `governor rejected: ${g.reject_reason}`
        : `${g.action} · qty ${Number(g.qty).toFixed(6)} · ${g.leverage}x · risk $${(a.risk_usdt ?? 0).toFixed(2)} · margin $${(a.margin_needed ?? 0).toFixed(2)}\n${(g.reasons || []).join('; ')}`,
      action: g.action,
    }
    stepIndex = STEP_INDEX.approved
    rejected = rej
  }
  if (c.execution) {
    steps.executed = { reason: c.execution.note || '', placed: c.execution.placed }
    stepIndex = STEP_INDEX.executed
  }
  return {
    source: c.source || 'watchlist',
    stepIndex,
    rejected,
    error: c.error || null,
    steps,
  }
}

// ---------------------------------------------------------------------------
// UI atoms
// ---------------------------------------------------------------------------

function StatCard({ label, children }) {
  return (
    <Box bg="brand.card" border="1px solid" borderColor="brand.border" borderRadius="12px" p={4}>
      <Text fontSize="11px" color="gray.500" textTransform="uppercase" mb={2}>
        {label}
      </Text>
      {children}
    </Box>
  )
}

function ModeBadge({ mode }) {
  const colors = { shadow: 'gray', demo: 'yellow', live: 'red' }
  return (
    <Badge colorScheme={colors[mode] || 'gray'} fontSize="sm" px={2} py={0.5}>
      {mode || 'unknown'}
    </Badge>
  )
}

function AssetTab({ symbol, asset, active, onClick }) {
  const idx = Math.max(asset.stepIndex, 0)
  const color = STEPS[idx]?.color || STEPS[0].color
  return (
    <Button
      size="xs"
      h="24px"
      px={2.5}
      borderRadius="full"
      fontSize="11px"
      fontWeight="600"
      letterSpacing="0.3px"
      onClick={onClick}
      bg={active ? color : 'transparent'}
      color={active ? '#0a0a0a' : color}
      border="1px solid"
      borderColor={color}
      opacity={asset.rejected && !active ? 0.55 : 1}
      _hover={{ bg: active ? color : 'rgba(255,255,255,0.06)' }}
    >
      {symbol}
      {asset.rejected ? ' ✕' : ''}
      {asset.error ? ' !' : ''}
    </Button>
  )
}

function StationDot({ reached, terminal, rejected, color, pending }) {
  return (
    <Box
      w="14px"
      h="14px"
      borderRadius="full"
      bg={reached ? color : 'transparent'}
      border="2px solid"
      borderColor={reached ? color : '#2a2a2a'}
      boxShadow={terminal && rejected ? '0 0 0 3px rgba(252,129,129,0.35)' : undefined}
      position="relative"
      zIndex={1}
    >
      {pending && (
        <Spinner size="xs" position="absolute" top="-4px" left="-4px" color="gray.400" />
      )}
    </Box>
  )
}

function StepCard({ step, data, side, terminal, rejected }) {
  return (
    <Box
      bg="brand.card"
      border="1px solid"
      borderColor={terminal && rejected ? 'rgba(252,129,129,0.5)' : 'brand.border'}
      borderRadius="10px"
      p={3}
      textAlign="left"
      {...(side === 'left'
        ? { borderRight: '2px solid', borderRightColor: step.color }
        : { borderLeft: '2px solid', borderLeftColor: step.color })}
    >
      <HStack justify="space-between" mb={1}>
        <Text fontSize="10px" textTransform="uppercase" letterSpacing="0.5px" color={step.color}>
          {step.label}
        </Text>
        {terminal && rejected && (
          <Text fontSize="10px" color="red.300" fontWeight="700">
            stopped here
          </Text>
        )}
      </HStack>
      <Text fontSize="xs" color="gray.300" whiteSpace="pre-wrap">
        {data?.reason || '—'}
      </Text>
    </Box>
  )
}

function Roadmap({ asset }) {
  if (!asset) {
    return (
      <Text fontSize="sm" color="gray.500" px={2}>
        Run a tick to see the pipeline roadmap.
      </Text>
    )
  }
  const terminalIndex = asset.stepIndex
  return (
    <Box position="relative" py={2}>
      {/* the metro line */}
      <Box
        position="absolute"
        left="50%"
        top="0"
        bottom="0"
        w="2px"
        transform="translateX(-50%)"
        bg="#242424"
      />
      <VStack spacing={5} align="stretch">
        {STEPS.map((step, i) => {
          const data = asset.steps[step.key]
          const reached = asset.stepIndex >= i && Boolean(data)
          const isTerminal = i === terminalIndex
          const side = i % 2 === 0 ? 'left' : 'right'
          const isPositionRow = step.key === 'managed'
          const muted = !reached && !data
          return (
            <Grid
              key={step.key}
              templateColumns="1fr 40px 1fr"
              alignItems="center"
              columnGap={2}
            >
              <Box>
                {side === 'left' && (data ? (
                  <StepCard step={step} data={data} side="left" terminal={isTerminal} rejected={asset.rejected} />
                ) : (
                  <Text fontSize="10px" color={muted ? 'gray.600' : 'gray.400'} textAlign="right" pr={2} textTransform="uppercase">
                    {step.label}
                  </Text>
                ))}
              </Box>
              <Flex justify="center">
                <StationDot
                  reached={reached}
                  terminal={isTerminal}
                  rejected={asset.rejected}
                  color={step.color}
                  pending={Boolean(data?.pending)}
                />
              </Flex>
              <Box>
                {side === 'right' && (data ? (
                  <StepCard step={step} data={data} side="right" terminal={isTerminal} rejected={asset.rejected} />
                ) : (
                  <Text fontSize="10px" color={muted ? 'gray.600' : 'gray.400'} pl={2} textTransform="uppercase">
                    {isPositionRow && asset.source !== 'position' ? `${step.label} (n/a — new candidate)` : step.label}
                  </Text>
                ))}
              </Box>
            </Grid>
          )
        })}
      </VStack>
    </Box>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ConductorPage() {
  const toast = useToast()
  const [status, setStatus] = useState(null)
  const [config, setConfig] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [toggling, setToggling] = useState(false)
  const [tick, dispatch] = useReducer(tickReducer, initialTick)
  const [activeSymbol, setActiveSymbol] = useState(null)
  const [showRaw, setShowRaw] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const caseParam = new URLSearchParams(location.search).get('case')
  const [storedCase, setStoredCase] = useState(null)
  const [storedCaseError, setStoredCaseError] = useState(null)
  const [showRawCase, setShowRawCase] = useState(false)

  useEffect(() => {
    if (!caseParam) {
      setStoredCase(null)
      setStoredCaseError(null)
      return
    }
    let cancelled = false
    setStoredCase(null)
    setStoredCaseError(null)
    api
      .getConductorCase(caseParam)
      .then((data) => {
        if (!cancelled) setStoredCase(data)
      })
      .catch((err) => {
        if (!cancelled) setStoredCaseError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [caseParam])
  const esRef = useRef(null)

  const refresh = useCallback(async () => {
    setError(null)
    try {
      const [st, cfg] = await Promise.all([api.getConductorStatus(), api.getConductorConfig()])
      setStatus(st)
      setConfig(cfg)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    return () => esRef.current?.close()
  }, [refresh])

  // keep active tab valid as assets stream in
  useEffect(() => {
    if (!activeSymbol && tick.order.length) setActiveSymbol(tick.order[0])
    if (activeSymbol && tick.order.length && !tick.order.includes(activeSymbol)) {
      setActiveSymbol(tick.order[0])
    }
  }, [tick.order, activeSymbol])

  async function onToggle() {
    const next = !status?.loop_enabled
    setToggling(true)
    try {
      await api.setConductorEnabled(next)
      toast({
        status: next ? 'success' : 'warning',
        title: next ? 'Loop enabled' : 'KILL SWITCH: new entries halted',
      })
      await refresh()
    } catch (err) {
      toast({ status: 'error', title: 'Toggle failed', description: err.message })
    } finally {
      setToggling(false)
    }
  }

  async function onTick() {
    esRef.current?.close()
    dispatch({ type: 'reset' })
    setActiveSymbol(null)
    if (caseParam) navigate('/conductor', { replace: true })
    const es = new EventSource(await api.conductorTickStreamUrl())
    esRef.current = es
    es.onmessage = (msg) => {
      let payload
      try {
        payload = JSON.parse(msg.data)
      } catch {
        return
      }
      dispatch({ type: 'stream', payload })
      if (payload.event === 'done') {
        es.close()
        esRef.current = null
        refresh()
        window.dispatchEvent(new Event('conductor-tick-done'))
      }
    }
    es.onerror = () => {
      es.close()
      esRef.current = null
      dispatch({ type: 'stopped' })
      toast({ status: 'error', title: 'Tick stream disconnected' })
    }
  }

  if (loading) {
    return (
      <Flex align="center" gap={3} color="gray.300" p={4}>
        <Spinner size="sm" /> <Text>Connecting to conductor...</Text>
      </Flex>
    )
  }

  if (error) {
    return (
      <Box p={4}>
        <Text color="red.300" mb={2}>
          Conductor unreachable at {api.conductorUrl}
        </Text>
        <Code fontSize="xs" colorScheme="red" whiteSpace="pre-wrap">
          {error}
        </Code>
        <Box mt={3}>
          <Button variant="ghostline" size="sm" onClick={refresh}>
            retry
          </Button>
        </Box>
      </Box>
    )
  }

  const risk = config?.risk || {}
  const activeAsset = activeSymbol ? tick.assets[activeSymbol] : null

  return (
    <VStack align="stretch" spacing={4} maxW="1100px">
      <Flex align="center" gap={4} wrap="wrap">
        <Text fontSize="xl" fontWeight="700">
          conductor
        </Text>
        <ModeBadge mode={status?.execution_mode} />
        <HStack
          bg="brand.card"
          border="1px solid"
          borderColor={status?.loop_enabled ? 'green.500' : 'red.400'}
          borderRadius="10px"
          px={3}
          py={1.5}
          spacing={3}
        >
          <Text fontSize="sm" fontWeight="600" color={status?.loop_enabled ? 'green.300' : 'red.300'}>
            {status?.loop_enabled ? 'LOOP ACTIVE' : 'HALTED'}
          </Text>
          <Switch
            colorScheme="green"
            isChecked={Boolean(status?.loop_enabled)}
            onChange={onToggle}
            isDisabled={toggling}
          />
        </HStack>
        <Button
          variant="action"
          size="sm"
          onClick={onTick}
          isLoading={tick.running}
          loadingText="streaming tick..."
        >
          run tick now
        </Button>
        <Button variant="ghostline" size="sm" onClick={refresh}>
          refresh
        </Button>
        {tick.portfolio && (
          <Text fontSize="xs" color="gray.400">
            equity ${Number(tick.portfolio.equity_usdt).toLocaleString()} · open risk $
            {Number(tick.portfolio.open_risk_usdt).toFixed(0)} · positions{' '}
            {(tick.portfolio.open_positions || []).length}
          </Text>
        )}
      </Flex>

      {Boolean(tick.errors.length) && (
        <Code display="block" whiteSpace="pre-wrap" fontSize="xs" colorScheme="red" p={2}>
          {tick.errors.join('\n')}
        </Code>
      )}
      {tick.halted && (
        <Text fontSize="sm" color="orange.300">
          Loop is halted (kill switch) — only open positions were managed.
        </Text>
      )}

      {/* asset tabs */}
      {Boolean(tick.order.length) && (
        <Flex gap={2} wrap="wrap" align="center">
          {tick.order.map((sym) => (
            <AssetTab
              key={sym}
              symbol={sym}
              asset={tick.assets[sym]}
              active={sym === activeSymbol}
              onClick={() => setActiveSymbol(sym)}
            />
          ))}
          {tick.running && <Spinner size="xs" color="gray.500" />}
        </Flex>
      )}

      {/* stored case (selected from sidebar) */}
      {caseParam && (
        <StatCard
          label={`stored case — ${caseParam}${storedCase?.execution_mode ? ` · ${storedCase.execution_mode}` : ''}`}
        >
          {storedCaseError ? (
            <Text fontSize="sm" color="red.300">
              {storedCaseError}
            </Text>
          ) : !storedCase ? (
            <HStack color="gray.300">
              <Spinner size="sm" />
              <Text fontSize="sm">Loading case...</Text>
            </HStack>
          ) : (
            <>
              <Roadmap asset={assetFromCase(storedCase)} />
              <Button variant="ghostline" size="xs" mt={2} onClick={() => setShowRawCase((v) => !v)}>
                {showRawCase ? 'hide' : 'show'} raw case
              </Button>
              {showRawCase && (
                <Code
                  display="block"
                  whiteSpace="pre-wrap"
                  fontSize="xs"
                  p={2}
                  mt={2}
                  maxH="360px"
                  overflowY="auto"
                >
                  {JSON.stringify(storedCase, null, 2)}
                </Code>
              )}
            </>
          )}
        </StatCard>
      )}

      {/* metro-map roadmap (live tick) */}
      {!caseParam && (
        <StatCard
          label={
            activeSymbol
              ? `pipeline — ${activeSymbol} (${activeAsset?.source || ''})${activeAsset?.error ? ' — ERROR: ' + activeAsset.error : ''}`
              : 'pipeline'
          }
        >
          <Roadmap asset={activeAsset} />
        </StatCard>
      )}

      {/* raw event array (same style as before, now covers all stream events) */}
      {Boolean(tick.events.length) && (
        <Box>
          <Button variant="ghostline" size="xs" onClick={() => setShowRaw((v) => !v)}>
            {showRaw ? 'hide' : 'show'} raw events ({tick.events.length})
          </Button>
          {showRaw && (
            <Code
              display="block"
              whiteSpace="pre-wrap"
              fontSize="xs"
              p={2}
              mt={2}
              maxH="420px"
              overflowY="auto"
            >
              {JSON.stringify(tick.events, null, 2)}
            </Code>
          )}
        </Box>
      )}

      <Grid templateColumns={{ base: '1fr', md: 'repeat(3, 1fr)' }} gap={3}>
        <StatCard label="Models">
          <VStack align="start" spacing={1} fontSize="sm">
            <Text>
              gate: <Code fontSize="xs">{status?.models?.gate}</Code>
            </Text>
            <Text>
              synthesis: <Code fontSize="xs">{status?.models?.synthesis}</Code>
            </Text>
            <Text>
              reflection: <Code fontSize="xs">{status?.models?.reflection}</Code>
            </Text>
          </VStack>
        </StatCard>
        <StatCard label="Watchlist / timeframes">
          <VStack align="start" spacing={1} fontSize="sm">
            <Text>{(status?.watchlist || []).join(', ') || '—'}</Text>
            <Text color="gray.400">{(status?.timeframes || []).join(' · ')}</Text>
          </VStack>
        </StatCard>
        <StatCard label="Risk governor">
          <VStack align="start" spacing={1} fontSize="xs" color="gray.300">
            <Text>risk/trade: {(risk.risk_fraction * 100).toFixed(2)}% equity</Text>
            <Text>max positions: {risk.max_concurrent_positions}</Text>
            <Text>max open risk: {(risk.max_aggregate_open_risk * 100).toFixed(1)}%</Text>
            <Text>
              breakers: day {(risk.daily_loss_breaker_fraction * 100).toFixed(1)}% / week{' '}
              {(risk.weekly_loss_breaker_fraction * 100).toFixed(1)}%
            </Text>
            <Text>
              max leverage {risk.max_leverage}x · max margin {risk.max_margin_percent}%
            </Text>
          </VStack>
        </StatCard>
      </Grid>
    </VStack>
  )
}
