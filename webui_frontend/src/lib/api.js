// src/lib/api.js — Thin wrapper around fetch for the FastAPI backend.
const BASE = '/api'

async function req(method, path, body) {
  const opts = { method }
  if (body !== undefined) {
    opts.headers = { 'Content-Type': 'application/json' }
    opts.body = JSON.stringify(body)
  }
  const res = await fetch(BASE + path, opts)
  if (!res.ok) {
    let msg = `${res.status}`
    try { msg = (await res.json()).detail || msg } catch { /* ignore */ }
    throw new Error(msg)
  }
  return res.json()
}

async function download(method, path, body) {
  const opts = { method }
  if (body !== undefined) {
    opts.headers = { 'Content-Type': 'application/json' }
    opts.body = JSON.stringify(body)
  }
  const res = await fetch(BASE + path, opts)
  if (!res.ok) {
    let msg = `${res.status}`
    try { msg = (await res.json()).detail || msg } catch { /* ignore */ }
    throw new Error(msg)
  }
  const blob = await res.blob()
  const disposition = res.headers.get('Content-Disposition') || ''
  const match = disposition.match(/filename="?([^"]+)"?/)
  return { blob, filename: match?.[1] || 'download.bin' }
}

const api = {
  // ── Common config (YAML-backed) ─────────────────────────────────────
  getConfig:  ()       => req('GET',  '/config'),
  saveConfig: (data)   => req('POST', '/config', data),

  // ── Non-common settings (DB-backed) ─────────────────────────────────
  getSettings:        ()            => req('GET',  '/settings'),
  getSection:         (s)           => req('GET',  `/settings/${encodeURIComponent(s)}`),
  saveSection:        (s, data)     => req('POST', `/settings/${encodeURIComponent(s)}`, data),
  getMergedConfig:    ()            => req('GET',  '/settings_merged'),

  // ── Mail import ──────────────────────────────────────────────────────────
  parseImapAccounts:    (text)     => req('POST', '/mail/import/imap',          { text }),
  parseImapAccountsNew: (text)     => req('POST', '/mail/import/imap/accounts', { text }),
  saveImapAccounts:     (accounts) => req('POST', '/mail/import/imap/save',     { accounts }),
  parseOutlookAccounts: (text)     => req('POST', '/mail/import/outlook',       { text }),
  saveOutlookAccounts:  (accounts) => req('POST', '/mail/import/outlook/save',  { accounts }),

  // ── Accounts ─────────────────────────────────────────────────────────
  getAccounts:        (params = {}) => req('GET',    '/accounts?' + new URLSearchParams(params)),
  getStats:           ()            => req('GET',    '/accounts/stats'),
  exportUrl:          (fmt)         => `${BASE}/accounts/export?fmt=${fmt}`,
  exportTokenZip:     (body)        => download('POST', '/accounts/export-token-zip', body),
  deleteAccount:      (email)       => req('DELETE', `/accounts/${encodeURIComponent(email)}`),
  batchDeleteAccounts:(body)        => req('POST',   '/accounts/batch-delete', body),
  uploadCliProxy:     (body)        => req('POST',   '/cli-proxy/upload', body),
  uploadCliProxyBatch:(body)        => req('POST',   '/cli-proxy/upload-batch', body),
  uploadSub2API:      (body)        => req('POST',   '/sub2api/upload', body),
  uploadSub2APIBatch: (body)        => req('POST',   '/sub2api/upload-batch', body),
  getCliProxyMonitorStatus: ()      => req('GET',    '/cli-proxy/monitor/status'),
  startCliProxyMonitor:     ()      => req('POST',   '/cli-proxy/monitor/start'),
  stopCliProxyMonitor:      ()      => req('POST',   '/cli-proxy/monitor/stop'),
  runCliProxyMonitorOnce:   ()      => req('POST',   '/cli-proxy/monitor/run-once'),
  getCliProxyMonitorHistory:(limit = 100) => req('GET', `/cli-proxy/monitor/history?limit=${limit}`),

  // ── Jobs ─────────────────────────────────────────────────────────────
  getJobs:         ()     => req('GET',    '/jobs'),
  getJob:          (id)   => req('GET',    `/jobs/${id}`),
  startJob:        (data) => req('POST',   '/jobs', data),
  cancelJob:       (id)   => req('POST',   `/jobs/${id}/cancel`),
  deleteJob:       (id)   => req('DELETE', `/jobs/${id}`),
  batchJobsAction: (body) => req('POST',   '/jobs/batch-action', body),

  // ── Proxies ──────────────────────────────────────────────────────────
  getProxies:         ()     => req('GET',    '/proxies'),
  addProxy:           (addr) => req('POST',   '/proxies', { address: addr }),
  deleteProxy:        (addr) => req('DELETE', `/proxies/${encodeURIComponent(addr)}`),
  batchDeleteProxies: (body) => req('POST',   '/proxies/batch-delete', body),
}

export default api
