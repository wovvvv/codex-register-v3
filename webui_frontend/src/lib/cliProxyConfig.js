// src/lib/cliProxyConfig.js — CLI Proxy settings normalization helpers.

const TARGETS = new Set(['local', 'remote'])

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

function cleanUrl(value) {
  return (typeof value === 'string' ? value.trim() : '').replace(/\/+$/, '')
}

function normalizeTarget(value) {
  const target = typeof value === 'string' ? value.trim().toLowerCase() : ''
  return TARGETS.has(target) ? target : 'local'
}

function cleanText(value) {
  return typeof value === 'string' ? value.trim() : ''
}

function positiveInt(value, fallback) {
  const num = Number(typeof value === 'string' ? value.trim() : value)
  return Number.isInteger(num) && num > 0 ? num : fallback
}

function legacyUrl(data) {
  const target = normalizeTarget(data?.target)
  const key = target === 'remote' ? 'remote_url' : 'local_url'
  return cleanText(data?.[key])
}

export const EMPTY_CLI_PROXY_CONFIG = {
  enabled: false,
  cpa_url: '',
  api_key: '',
  monitor_interval_minutes: 180,
  monitor_active_probe: false,
  monitor_probe_timeout: 8,
}

export function normalizeCliProxyConfig(raw) {
  const data = raw && typeof raw === 'object' ? raw : {}
  return {
    enabled: asBool(data.enabled),
    cpa_url: cleanText(data.cpa_url) || legacyUrl(data),
    api_key: cleanText(data.api_key),
    monitor_interval_minutes: positiveInt(data.monitor_interval_minutes, 180),
    monitor_active_probe: asBool(data.monitor_active_probe),
    monitor_probe_timeout: positiveInt(data.monitor_probe_timeout, 8),
  }
}

export function serializeCliProxyConfig(raw) {
  const data = raw && typeof raw === 'object' ? raw : {}
  return {
    enabled: asBool(data.enabled),
    cpa_url: cleanText(data.cpa_url),
    api_key: cleanText(data.api_key),
    monitor_interval_minutes: positiveInt(data.monitor_interval_minutes, 180),
    monitor_active_probe: asBool(data.monitor_active_probe),
    monitor_probe_timeout: positiveInt(data.monitor_probe_timeout, 8),
  }
}
