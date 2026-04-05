import { useEffect, useMemo, useState } from 'react'
import {
  Box,
  Button,
  HStack,
  Input,
  Select,
  SimpleGrid,
  Text,
  Textarea,
  useToast,
  VStack,
} from '@chakra-ui/react'
import SectionCard from './SectionCard'
import { proposalFields } from './fieldSets'
import { useAppStore } from '../../store/useAppStore'
import { formatTimestampForUi, isTemporalFieldKey } from '../../lib/datetime'

const numberFields = new Set([
  'target_price',
  'stop_loss',
  'leverage',
  'margin_percent',
  'entry_price_min',
  'entry_price_max',
  'confidence',
])

const longTextFields = new Set(['reason_entry', 'reason_abstain'])

const selectFields = {
  long_short_none: ['LONG', 'SHORT', 'NONE'],
  position_duration: ['HOUR', 'DAY', 'SWING'],
  position_strategy: ['ADD_UP', 'DCA', 'CONTRARIAN', 'SCALP', 'HOLD'],
}

function normalizeForForm(value) {
  if (value === null || value === undefined) {
    return ''
  }
  if (Array.isArray(value)) {
    return value.join(', ')
  }
  return String(value)
}

function formToPayload(form) {
  const payload = {}
  for (const field of proposalFields) {
    const raw = form[field.key]
    if (raw === '') {
      payload[field.key] = null
      continue
    }
    if (field.key === 'rationale_tags') {
      payload[field.key] = raw
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean)
      continue
    }
    if (numberFields.has(field.key)) {
      const n = Number(raw)
      payload[field.key] = Number.isFinite(n) ? n : null
      continue
    }
    payload[field.key] = raw
  }
  return payload
}

function TradeExecutionBanner({ exec }) {
  if (!exec) return null
  const params = exec.order_params || {}
  const result = exec.order_result || {}
  const side = params.side || result.side
  const sideColor = side === 'Buy' ? 'green.300' : side === 'Sell' ? 'red.300' : 'gray.400'
  const orderId = result.orderId || result.order_id || exec.order_result?.result?.orderId
  const executedAt = exec.executed_at ? new Date(exec.executed_at).toLocaleString() : null
  return (
    <Box
      border="1px solid"
      borderColor={side === 'Buy' ? 'green.700' : side === 'Sell' ? 'red.800' : 'gray.700'}
      borderRadius="md"
      px={3}
      py={2}
      bg={side === 'Buy' ? 'rgba(72,187,120,0.07)' : side === 'Sell' ? 'rgba(252,129,129,0.07)' : 'transparent'}
    >
      <HStack justify="space-between" wrap="wrap" spacing={3}>
        <HStack spacing={3}>
          <Text fontSize="11px" fontWeight="700" color={sideColor} textTransform="uppercase">
            {side || '—'} {params.orderType || ''}
          </Text>
          {params.qty && (
            <Text fontSize="11px" color="gray.400">qty {params.qty}</Text>
          )}
          {params.price && (
            <Text fontSize="11px" color="gray.400">@ {params.price}</Text>
          )}
          {params.stopLoss && (
            <Text fontSize="11px" color="orange.300">SL {params.stopLoss}</Text>
          )}
          {params.takeProfit && (
            <Text fontSize="11px" color="blue.300">TP {params.takeProfit}</Text>
          )}
        </HStack>
        <HStack spacing={3}>
          {orderId && (
            <Text fontSize="10px" color="gray.500" fontFamily="mono">{String(orderId).slice(0, 12)}…</Text>
          )}
          {executedAt && (
            <Text fontSize="10px" color="gray.500">{executedAt}</Text>
          )}
        </HStack>
      </HStack>
    </Box>
  )
}

export default function TradeFormCard({ caseId, proposal, existingTrade, tradeExecution }) {
  const saveTrade = useAppStore((s) => s.saveTrade)
  const savingTrade = useAppStore((s) => s.savingTrade)
  const executeTrade = useAppStore((s) => s.executeTrade)
  const executingTrade = useAppStore((s) => s.executingTrade)
  const timezone = useAppStore((s) => s.settings.timezone)
  const [isEditing, setIsEditing] = useState(false)
  const toast = useToast()

  const initialState = useMemo(() => {
    const source = existingTrade || proposal || {}
    const out = {}
    for (const field of proposalFields) {
      out[field.key] = normalizeForForm(source[field.key])
    }
    return out
  }, [existingTrade, proposal])

  const [form, setForm] = useState(initialState)

  useEffect(() => {
    if (!isEditing) {
      setForm(initialState)
    }
  }, [initialState, isEditing])

  const setFromSource = (source) => {
    const out = {}
    for (const field of proposalFields) {
      out[field.key] = normalizeForForm(source?.[field.key])
    }
    setForm(out)
  }

  const onSave = async () => {
    if (!caseId) {
      return
    }
    try {
      const payload = formToPayload(form)
      await saveTrade(caseId, payload)
      setIsEditing(false)
      toast({ status: 'success', title: 'Trade saved' })
    } catch (error) {
      toast({ status: 'error', title: 'Failed to save trade', description: error.message })
    }
  }

  const onExecute = async () => {
    if (!caseId) {
      return
    }
    const ok = window.confirm(
      `Execute trade from proposal_validated.json for case ${caseId}?\n\nThis will place a real order on Bybit.`
    )
    if (!ok) return
    try {
      await executeTrade(caseId)
      toast({ status: 'success', title: 'Trade executed', description: 'Order placed via agent_trading' })
    } catch (error) {
      toast({ status: 'error', title: 'Execution failed', description: error.message })
    }
  }

  return (
    <SectionCard title="Trade Form">
      <VStack align="stretch" spacing={3}>
        <TradeExecutionBanner exec={tradeExecution} />
        <SimpleGrid columns={{ base: 1, md: 2 }} spacing={2}>
          {proposalFields.map((field) => {
            const value = form[field.key] ?? ''
            const disabled = !isEditing
            const formattedTemporal = disabled && isTemporalFieldKey(field.key)
              ? formatTimestampForUi(value, timezone)
              : null
            const displayValue = formattedTemporal || value

            if (selectFields[field.key]) {
              return (
                <VStack key={field.key} align="stretch" spacing={1}>
                  <Text fontSize="11px" color="gray.500">
                    {field.label}
                  </Text>
                  <Select
                    size="sm"
                    value={displayValue}
                    isDisabled={disabled}
                    onChange={(e) => setForm((prev) => ({ ...prev, [field.key]: e.target.value }))}
                    borderColor="brand.border"
                    bg="#111"
                  >
                    <option value="">—</option>
                    {selectFields[field.key].map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </Select>
                </VStack>
              )
            }

            if (longTextFields.has(field.key)) {
              return (
                <VStack key={field.key} align="stretch" spacing={1} gridColumn={{ md: 'span 2' }}>
                  <Text fontSize="11px" color="gray.500">
                    {field.label}
                  </Text>
                  <Textarea
                    size="sm"
                    minH="82px"
                    value={displayValue}
                    isDisabled={disabled}
                    onChange={(e) => setForm((prev) => ({ ...prev, [field.key]: e.target.value }))}
                    borderColor="brand.border"
                    bg="#111"
                  />
                </VStack>
              )
            }

            return (
              <VStack key={field.key} align="stretch" spacing={1}>
                <Text fontSize="11px" color="gray.500">
                  {field.label}
                </Text>
                <Input
                  size="sm"
                  type={numberFields.has(field.key) ? 'number' : 'text'}
                  value={displayValue}
                  isDisabled={disabled}
                  onChange={(e) => setForm((prev) => ({ ...prev, [field.key]: e.target.value }))}
                  borderColor="brand.border"
                  bg="#111"
                />
              </VStack>
            )
          })}
        </SimpleGrid>

        <HStack wrap="wrap">
          <Button
            variant="action"
            onClick={onExecute}
            isLoading={executingTrade}
            isDisabled={!caseId || !proposal?.long_short_none || proposal?.long_short_none === 'NONE'}
            title="Place order on Bybit from proposal_validated.json via agent_trading"
          >
            execute
          </Button>
          <Button
            variant="ghostline"
            onClick={() => {
              setFromSource(proposal || {})
              setIsEditing(true)
            }}
          >
            take trade
          </Button>
          <Button variant="ghostline" onClick={() => setIsEditing((prev) => !prev)}>
            {isEditing ? 'cancel edit' : 'edit'}
          </Button>
          <Button variant="action" onClick={onSave} isLoading={savingTrade} isDisabled={!isEditing || !caseId}>
            save
          </Button>
        </HStack>
      </VStack>
    </SectionCard>
  )
}
