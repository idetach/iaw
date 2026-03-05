import { Box, SimpleGrid, Text } from '@chakra-ui/react'
import { useAppStore } from '../../store/useAppStore'
import { formatTimestampForUi, isTemporalFieldKey } from '../../lib/datetime'

function formatValue(value) {
  if (value === null || value === undefined || value === '') {
    return '—'
  }
  if (Array.isArray(value)) {
    return value.length ? value.join(', ') : '—'
  }
  if (typeof value === 'object') {
    return JSON.stringify(value)
  }
  return String(value)
}

function hasRenderableValue(value) {
  if (value === null || value === undefined || value === '') {
    return false
  }
  if (Array.isArray(value)) {
    return value.length > 0
  }
  return true
}

function parseConfidence(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) {
    return null
  }
  if (n <= 1) {
    return Math.max(0, Math.min(1, n))
  }
  if (n <= 100) {
    return n / 100
  }
  return 1
}

function confidenceFill(value) {
  if (value === null) {
    return { fullSlices: 0, partialPercent: 0 }
  }
  const scaled = Math.max(0, Math.min(10, value * 10))
  const fullSlices = Math.floor(scaled)
  const partialPercent = Math.round((scaled - fullSlices) * 100)
  return { fullSlices, partialPercent }
}

export default function DataPairs({ fields, source }) {
  const timezone = useAppStore((s) => s.settings.timezone)

  return (
    <SimpleGrid columns={{ base: 1, md: 2 }} spacing={3}>
      {fields.map((field) => {
        const rawValue = source?.[field.key]
        const formattedTemporal = isTemporalFieldKey(field.key)
          ? formatTimestampForUi(rawValue, timezone)
          : null
        const valueText = formattedTemporal || formatValue(rawValue)
        const shouldAnimate = hasRenderableValue(rawValue)
        const confidenceValue = field.key === 'confidence' ? parseConfidence(rawValue) : null
        const { fullSlices, partialPercent } = confidenceFill(confidenceValue)

        return (
          <Text key={field.key} fontSize="sm" color="gray.200">
            <Text as="span" color="gray.500">
              {field.label}:{' '}
            </Text>
            <Text as="span" key={`${field.key}:${valueText}`} className={shouldAnimate ? 'fade-in' : ''}>
              {valueText}
            </Text>
            {field.key === 'confidence' && confidenceValue !== null && (
              <Box as="span" display="inline-flex" gap="2px" ml={2} verticalAlign="middle">
                {Array.from({ length: 10 }).map((_, idx) => (
                  <Box
                    as="span"
                    key={`confidence-slice-${idx}`}
                    w="8px"
                    h="7px"
                    bg={
                      idx < fullSlices
                        ? 'brand.yellow'
                        : idx === fullSlices && partialPercent > 0
                          ? `linear-gradient(to right, var(--chakra-colors-brand-yellow) ${partialPercent}%, var(--chakra-colors-gray-500) ${partialPercent}%)`
                          : 'gray.500'
                    }
                  />
                ))}
              </Box>
            )}
          </Text>
        )
      })}
    </SimpleGrid>
  )
}
