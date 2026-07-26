import { useCallback, useEffect, useState } from 'react'
import {
  Badge,
  Box,
  Button,
  Checkbox,
  Code,
  FormControl,
  FormLabel,
  Heading,
  HStack,
  Input,
  Select,
  SimpleGrid,
  Spinner,
  Text,
  useToast,
  VStack,
} from '@chakra-ui/react'
import { api } from '../../lib/api'

const MODEL_FIELDS = [
  { key: 'model_gate', label: 'Gate model', hint: 'every candidate, every tick — cheapest tier' },
  { key: 'model_synthesis', label: 'Synthesis model', hint: 'gate survivors only — strongest tier' },
  { key: 'model_reflection', label: 'Reflection model', hint: 'closed trades only — strong tier' },
]

export default function ConductorTickSettings() {
  const toast = useToast()
  const [data, setData] = useState(null)
  const [form, setForm] = useState({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [sched, setSched] = useState(null)
  const [schedMinutes, setSchedMinutes] = useState('')
  const [schedSaving, setSchedSaving] = useState(false)

  const load = useCallback(async () => {
    setError(null)
    try {
      const res = await api.getConductorSettings()
      setData(res)
      setForm(res.editable || {})
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  const loadSched = useCallback(async () => {
    try {
      const res = await api.getSchedulerInterval()
      setSched(res)
      if (res?.interval_minutes != null) setSchedMinutes(String(res.interval_minutes))
    } catch {
      setSched({ configured: false })
    }
  }, [])

  useEffect(() => {
    load()
    loadSched()
  }, [load, loadSched])

  async function onSaveSched() {
    const minutes = Number(schedMinutes)
    if (!Number.isInteger(minutes) || minutes < 1) {
      toast({ status: 'error', title: 'Enter whole minutes >= 1' })
      return
    }
    setSchedSaving(true)
    try {
      const res = await api.setSchedulerInterval(minutes)
      toast({ status: 'success', title: `Cloud cadence: every ${res.interval_minutes ?? minutes} min` })
      await loadSched()
    } catch (err) {
      toast({ status: 'error', title: 'Scheduler update failed', description: err.message })
    } finally {
      setSchedSaving(false)
    }
  }

  function set(key, value) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  async function onSave() {
    setSaving(true)
    try {
      const res = await api.updateConductorSettings(form)
      toast({ status: 'success', title: `Saved: ${res.applied.join(', ') || 'no changes'}` })
      await load()
    } catch (err) {
      toast({ status: 'error', title: 'Save failed', description: err.message })
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <HStack color="gray.300" p={2}>
        <Spinner size="sm" /> <Text>Loading conductor settings...</Text>
      </HStack>
    )
  }

  if (error) {
    return (
      <Box>
        <Text color="red.300" mb={2}>
          Conductor unreachable at {api.conductorUrl}
        </Text>
        <Code fontSize="xs" whiteSpace="pre-wrap">
          {error}
        </Code>
        <Box mt={3}>
          <Button variant="ghostline" size="sm" onClick={load}>
            retry
          </Button>
        </Box>
      </Box>
    )
  }

  const guarded = data?.guarded || {}
  const modelOptions = data?.model_options || []

  return (
    <VStack align="stretch" spacing={6} maxW="860px">
      <HStack justify="space-between">
        <Heading size="md">Conductor tick</Heading>
        <Button variant="action" size="sm" onClick={onSave} isLoading={saving}>
          save
        </Button>
      </HStack>

      {/* model routing */}
      <Box>
        <Heading size="sm" mb={1}>
          Model routing
        </Heading>
        <Text fontSize="xs" color="gray.500" mb={3}>
          Cost tiers by call volume × stakes (ADR-0005). Fable &gt; Opus &gt; Sonnet &gt; Haiku.
        </Text>
        <SimpleGrid columns={{ base: 1, md: 3 }} spacing={4}>
          {MODEL_FIELDS.map(({ key, label, hint }) => (
            <FormControl key={key}>
              <FormLabel color="gray.400" fontSize="sm">
                {label}
              </FormLabel>
              <Select value={form[key] || ''} onChange={(e) => set(key, e.target.value)} size="sm">
                {modelOptions.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
                {form[key] && !modelOptions.includes(form[key]) && (
                  <option value={form[key]}>{form[key]}</option>
                )}
              </Select>
              <Text fontSize="10px" color="gray.500" mt={1}>
                {hint}
              </Text>
            </FormControl>
          ))}
        </SimpleGrid>
      </Box>

      {/* candidate flow */}
      <Box>
        <Heading size="sm" mb={3}>
          Candidate flow
        </Heading>
        <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
          <FormControl>
            <FormLabel color="gray.400" fontSize="sm">
              Watchlist (comma-separated)
            </FormLabel>
            <Input
              size="sm"
              value={form.watchlist || ''}
              onChange={(e) => set('watchlist', e.target.value)}
            />
          </FormControl>
          <FormControl>
            <FormLabel color="gray.400" fontSize="sm">
              Timeframes (comma-separated)
            </FormLabel>
            <Input
              size="sm"
              value={form.timeframes || ''}
              onChange={(e) => set('timeframes', e.target.value)}
            />
          </FormControl>
          <FormControl>
            <FormLabel color="gray.400" fontSize="sm">
              Max candidates per tick
            </FormLabel>
            <Input
              size="sm"
              type="number"
              value={form.max_candidates_per_tick ?? ''}
              onChange={(e) => set('max_candidates_per_tick', e.target.value)}
            />
          </FormControl>
          <FormControl>
            <FormLabel color="gray.400" fontSize="sm">
              Min proposal confidence (0–1)
            </FormLabel>
            <Input
              size="sm"
              type="number"
              step="0.05"
              value={form.min_confidence ?? ''}
              onChange={(e) => set('min_confidence', e.target.value)}
            />
          </FormControl>
        </SimpleGrid>
        <HStack spacing={6} mt={3}>
          <Checkbox
            isChecked={Boolean(form.radar_enabled)}
            onChange={(e) => set('radar_enabled', e.target.checked)}
          >
            <Text fontSize="sm">radar candidates (extreme events)</Text>
          </Checkbox>
          <Checkbox
            isChecked={Boolean(form.include_recent_outcomes)}
            onChange={(e) => set('include_recent_outcomes', e.target.checked)}
          >
            <Text fontSize="sm">LLM memory: recent outcomes in synthesis (experiment)</Text>
          </Checkbox>
          <Checkbox
            isChecked={Boolean(form.persist_cases)}
            onChange={(e) => set('persist_cases', e.target.checked)}
          >
            <Text fontSize="sm">persist cases to GCS</Text>
          </Checkbox>
        </HStack>
      </Box>

      {/* orders + mode */}
      <Box>
        <Heading size="sm" mb={3}>
          Resting orders & mode
        </Heading>
        <SimpleGrid columns={{ base: 1, md: 5 }} spacing={4}>
          <FormControl>
            <FormLabel color="gray.400" fontSize="sm">
              Order TTL (minutes)
            </FormLabel>
            <Input
              size="sm"
              type="number"
              value={form.order_ttl_minutes ?? ''}
              onChange={(e) => set('order_ttl_minutes', e.target.value)}
            />
          </FormControl>
          <FormControl>
            <FormLabel color="gray.400" fontSize="sm">
              Max drift (ATRs)
            </FormLabel>
            <Input
              size="sm"
              type="number"
              step="0.5"
              value={form.order_max_drift_atr ?? ''}
              onChange={(e) => set('order_max_drift_atr', e.target.value)}
            />
          </FormControl>
          <FormControl>
            <FormLabel color="gray.400" fontSize="sm">
              Reconcile timeframe
            </FormLabel>
            <Select
              size="sm"
              value={form.order_reconcile_timeframe || '1h'}
              onChange={(e) => set('order_reconcile_timeframe', e.target.value)}
            >
              {['4h', '1h', '30m', '15m'].map((tf) => (
                <option key={tf} value={tf}>
                  {tf}
                </option>
              ))}
            </Select>
          </FormControl>
          <FormControl>
            <FormLabel color="gray.400" fontSize="sm">
              Tick cadence (minutes, 0 = off)
            </FormLabel>
            <Input
              size="sm"
              type="number"
              value={form.tick_interval_minutes ?? ''}
              onChange={(e) => set('tick_interval_minutes', e.target.value)}
            />
            <Text fontSize="10px" color="gray.500" mt={1}>
              internal ticker for local runs; on Cloud Run keep 0 and use Cloud Scheduler
            </Text>
          </FormControl>
          <FormControl>
            <FormLabel color="gray.400" fontSize="sm">
              Execution mode
            </FormLabel>
            <Select
              size="sm"
              value={form.execution_mode || 'demo'}
              onChange={(e) => set('execution_mode', e.target.value)}
            >
              <option value="shadow">shadow (log only)</option>
              <option value="demo">demo (Bybit demo)</option>
            </Select>
            <Text fontSize="10px" color="gray.500" mt={1}>
              live requires env + go-live checklist (ADR-0003)
            </Text>
          </FormControl>
        </SimpleGrid>
      </Box>

      {/* cloud tick cadence — Cloud Scheduler (ADR-0009) */}
      {sched?.configured && (
        <Box>
          <HStack mb={1}>
            <Heading size="sm">Cloud tick cadence</Heading>
            <Badge colorScheme={sched.state === 'ENABLED' ? 'green' : 'yellow'} fontSize="10px">
              {sched.state?.toLowerCase() || 'scheduler'}
            </Badge>
          </HStack>
          <Text fontSize="xs" color="gray.500" mb={3}>
            Drives ticks on Cloud Run via Cloud Scheduler ({sched.job}). Editing this updates the
            scheduler job directly — separate from the local internal ticker above (ADR-0009).
          </Text>
          <HStack align="flex-end" spacing={4}>
            <FormControl maxW="220px">
              <FormLabel color="gray.400" fontSize="sm">
                Every N minutes
              </FormLabel>
              <Input
                size="sm"
                type="number"
                value={schedMinutes}
                onChange={(e) => setSchedMinutes(e.target.value)}
              />
              <Text fontSize="10px" color="gray.500" mt={1}>
                current: <Code fontSize="10px">{sched.schedule}</Code>
                {sched.interval_minutes != null && ` (~${sched.interval_minutes} min)`}
              </Text>
            </FormControl>
            <Button variant="action" size="sm" onClick={onSaveSched} isLoading={schedSaving}>
              update cadence
            </Button>
          </HStack>
        </Box>
      )}

      {/* guarded risk caps — read-only */}
      <Box>
        <HStack mb={1}>
          <Heading size="sm">Risk caps</Heading>
          <Badge colorScheme="red" fontSize="10px">
            env-only
          </Badge>
        </HStack>
        <Text fontSize="xs" color="gray.500" mb={3}>
          Deliberately not editable here — changing risk limits requires a redeploy plus an
          experiment log / ADR (ADR-0006).
        </Text>
        <SimpleGrid columns={{ base: 2, md: 3 }} spacing={2} fontSize="xs" color="gray.300">
          <Text>risk/trade: {(guarded.risk_fraction * 100).toFixed(2)}%</Text>
          <Text>max slots: {guarded.max_concurrent_positions}</Text>
          <Text>max open risk: {(guarded.max_aggregate_open_risk * 100).toFixed(1)}%</Text>
          <Text>max margin used: {(guarded.max_total_margin_fraction * 100).toFixed(0)}%</Text>
          <Text>max leverage: {guarded.max_leverage}x</Text>
          <Text>max margin/trade: {guarded.max_margin_percent}%</Text>
          <Text>cooldown: {guarded.symbol_cooldown_hours}h</Text>
          <Text>day breaker: {(guarded.daily_loss_breaker_fraction * 100).toFixed(1)}%</Text>
          <Text>week breaker: {(guarded.weekly_loss_breaker_fraction * 100).toFixed(1)}%</Text>
        </SimpleGrid>
      </Box>
    </VStack>
  )
}
