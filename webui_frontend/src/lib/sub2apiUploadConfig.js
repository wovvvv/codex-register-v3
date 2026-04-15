// src/lib/sub2apiUploadConfig.js — Sub2API upload settings normalization helpers.

function cleanText(value) {
  return typeof value === 'string' ? value.trim() : ''
}

function cleanUrl(value) {
  return cleanText(value).replace(/\/+$/, '')
}

function asBool(value) {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return value !== 0
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase()
    if (['true', '1', 'yes', 'on'].includes(normalized)) return true
    if (['false', '0', 'no', 'off', ''].includes(normalized)) return false
  }
  return !!value
}

function positiveInt(value, fallback = '') {
  if (value === '' || value === null || value === undefined) return fallback
  const num = Number(typeof value === 'string' ? value.trim() : value)
  return Number.isInteger(num) && num > 0 ? num : fallback
}

function normalizeIntList(value) {
  const source = Array.isArray(value)
    ? value
    : typeof value === 'string'
      ? value.split(/[\n,]/)
      : []

  const seen = new Set()
  const items = []
  for (const raw of source) {
    const num = positiveInt(raw, '')
    if (num === '' || seen.has(num)) continue
    seen.add(num)
    items.push(num)
  }
  return items
}

function nonNegativeFloat(value, fallback = '') {
  if (value === '' || value === null || value === undefined) return fallback
  const num = Number(typeof value === 'string' ? value.trim() : value)
  return Number.isFinite(num) && num >= 0 ? num : fallback
}

function normalizeModelWhitelist(value) {
  const source = Array.isArray(value)
    ? value
    : typeof value === 'string'
      ? value.split(/[\n,]/)
      : []

  const seen = new Set()
  const items = []
  for (const raw of source) {
    const model = cleanText(raw)
    if (!model || seen.has(model)) continue
    seen.add(model)
    items.push(model)
  }
  return items
}

export const EMPTY_SUB2API_UPLOAD_CONFIG = {
  base_url: '',
  api_key: '',
  group_ids: [],
  proxy_id: '',
  notes: '',
  concurrency: 1,
  load_factor: 1,
  priority: 2,
  rate_multiplier: 1,
  import_models: false,
  model_whitelist: [],
}

export function normalizeSub2APIUploadConfig(raw) {
  const data = raw && typeof raw === 'object' ? raw : {}
  return {
    base_url: cleanUrl(data.base_url),
    api_key: cleanText(data.api_key),
    group_ids: normalizeIntList(data.group_ids ?? data.group_id),
    proxy_id: positiveInt(data.proxy_id),
    notes: cleanText(data.notes),
    concurrency: positiveInt(data.concurrency, 1),
    load_factor: positiveInt(data.load_factor, 1),
    priority: positiveInt(data.priority, 2),
    rate_multiplier: nonNegativeFloat(data.rate_multiplier, 1),
    import_models: asBool(data.import_models),
    model_whitelist: normalizeModelWhitelist(data.model_whitelist),
  }
}

export function serializeSub2APIUploadConfig(raw) {
  const data = raw && typeof raw === 'object' ? raw : {}
  return {
    base_url: cleanUrl(data.base_url),
    api_key: cleanText(data.api_key),
    group_ids: normalizeIntList(data.group_ids ?? data.group_id),
    proxy_id: positiveInt(data.proxy_id, 0),
    notes: cleanText(data.notes),
    concurrency: positiveInt(data.concurrency, 1),
    load_factor: positiveInt(data.load_factor, 1),
    priority: positiveInt(data.priority, 2),
    rate_multiplier: nonNegativeFloat(data.rate_multiplier, 1),
    import_models: asBool(data.import_models),
    model_whitelist: normalizeModelWhitelist(data.model_whitelist),
  }
}
