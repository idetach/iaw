import { useEffect, useMemo, useState } from 'react'
import {
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

export default function TradeFormCard({ caseId, proposal, existingTrade }) {
  const saveTrade = useAppStore((s) => s.saveTrade)
  const savingTrade = useAppStore((s) => s.savingTrade)
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

  return (
    <SectionCard title="Trade Form">
      <VStack align="stretch" spacing={3}>
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
