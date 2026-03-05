const TEMPORAL_FIELD_KEY_RE = /(timestamp|_time_|time_from|time_to|created_at|updated_at)/i

export function isTemporalFieldKey(fieldKey) {
  return TEMPORAL_FIELD_KEY_RE.test(fieldKey || '')
}

export function resolveTimeZone(timezoneSetting) {
  if (!timezoneSetting || timezoneSetting === 'local') {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  }
  return timezoneSetting
}

function toDate(value) {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value
  }

  if (typeof value === 'number') {
    const tsMs = value < 1e12 ? value * 1000 : value
    const date = new Date(tsMs)
    return Number.isNaN(date.getTime()) ? null : date
  }

  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (!trimmed) {
      return null
    }

    if (/^\d+$/.test(trimmed)) {
      const asNumber = Number(trimmed)
      return toDate(asNumber)
    }

    const date = new Date(trimmed)
    return Number.isNaN(date.getTime()) ? null : date
  }

  return null
}

export function formatTimestampForUi(value, timezoneSetting) {
  const date = toDate(value)
  if (!date) {
    return null
  }

  const options = {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }

  const timeZone = resolveTimeZone(timezoneSetting)
  try {
    return new Intl.DateTimeFormat(undefined, { ...options, timeZone }).format(date)
  } catch {
    return new Intl.DateTimeFormat(undefined, options).format(date)
  }
}
