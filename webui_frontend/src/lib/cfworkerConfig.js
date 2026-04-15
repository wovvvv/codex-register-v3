export const EMPTY_CFWORKER_CONFIG = {
  api_url: '',
  admin_token: '',
  custom_auth: '',
  fingerprint: '',
  domain: '',
  domains: [],
  enabled_domains: [],
  subdomain: '',
  random_subdomain: false,
}

export const CFWORKER_PROVIDER_OPTION = ['cfworker', 'CF Worker']
const GPTMAIL_PROVIDER_OPTION = ['gptmail', 'GptMail']
const NPCMAIL_PROVIDER_OPTION = ['npcmail', 'NpcMail']
const YYDSMAIL_PROVIDER_OPTION = ['yydsmail', 'YYDSMail']

export const DEFAULT_SETTINGS_PROVIDER_OPTIONS = [
  ['imap:0', 'IMAP 服务商 1'],
  GPTMAIL_PROVIDER_OPTION,
  CFWORKER_PROVIDER_OPTION,
]

export const DEFAULT_DASHBOARD_PROVIDER_OPTIONS = [
  ['imap:0', 'IMAP 服务商 1'],
  CFWORKER_PROVIDER_OPTION,
]

export const DEFAULT_JOBS_PROVIDER_OPTIONS = [
  ['imap:0', 'IMAP 服务商 1'],
  GPTMAIL_PROVIDER_OPTION,
  CFWORKER_PROVIDER_OPTION,
]

function normalizeBool(value) {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return value !== 0
  if (typeof value === 'string') {
    const v = value.trim().toLowerCase()
    if (v === 'true' || v === '1' || v === 'yes' || v === 'on') return true
    if (v === 'false' || v === '0' || v === 'no' || v === 'off' || v === '') return false
  }
  return Boolean(value)
}

function normalizeString(value) {
  return typeof value === 'string' ? value.trim() : ''
}

function normalizeDomain(value) {
  return normalizeString(value).toLowerCase()
}

export function normalizeDomainList(value) {
  const list = Array.isArray(value)
    ? value
    : typeof value === 'string'
      ? value.split(/[\n,]+/)
      : []

  const dedup = new Set()
  for (const item of list) {
    const normalized = normalizeDomain(item)
    if (normalized) dedup.add(normalized)
  }
  return [...dedup]
}

export function normalizeCfworkerConfig(raw) {
  const source = raw && typeof raw === 'object' ? raw : {}
  const domains = normalizeDomainList(source.domains)
  const enabledDomains = normalizeDomainList(source.enabled_domains)
    .filter((domain) => domains.includes(domain))

  return {
    api_url: normalizeString(source.api_url),
    admin_token: normalizeString(source.admin_token),
    custom_auth: normalizeString(source.custom_auth),
    fingerprint: normalizeString(source.fingerprint),
    domain: normalizeDomain(source.domain),
    domains,
    enabled_domains: enabledDomains,
    subdomain: normalizeString(source.subdomain),
    random_subdomain: normalizeBool(source.random_subdomain),
  }
}

export function serializeCfworkerConfig(raw) {
  const normalized = normalizeCfworkerConfig(raw)
  return {
    api_url: normalized.api_url,
    admin_token: normalized.admin_token,
    custom_auth: normalized.custom_auth,
    fingerprint: normalized.fingerprint,
    domain: normalized.domains.length > 0 ? '' : normalized.domain,
    domains: normalized.domains,
    enabled_domains: normalized.enabled_domains,
    subdomain: normalized.subdomain,
    random_subdomain: normalized.random_subdomain,
  }
}

function buildOutlookNoTokenLabel(outlookStats) {
  const remaining = Number(outlookStats?.without_token)
  return Number.isFinite(remaining) && remaining >= 0
    ? `Outlook（仅未获取 Access Token 账户轮换，剩余 ${remaining} 个）`
    : 'Outlook（仅未获取 Access Token 账户轮换）'
}

function buildProviderOptions(settings = {}, mode = 'settings', meta = {}) {
  const items = []
  const imapProviders = Array.isArray(settings['mail.imap']) ? settings['mail.imap'] : []
  const isProviderShape = imapProviders.length > 0 && imapProviders[0] && typeof imapProviders[0] === 'object' && 'accounts' in imapProviders[0]

  if (isProviderShape) {
    imapProviders.forEach((prov, i) => {
      const name = prov?.name || `IMAP 服务商 ${i + 1}`
      const accounts = Array.isArray(prov?.accounts) ? prov.accounts : []
      if (mode === 'dashboard') {
        items.push([`imap:${i}`, `${name} (${accounts.length} 账户)`])
      } else {
        items.push([`imap:${i}`, `${name}（全部 ${accounts.length} 账户轮换）`])
        if (mode === 'jobs') {
          accounts.forEach((acc, j) => {
            const label = acc?.email ? acc.email : `账户 ${j + 1}`
            items.push([`imap:${i}:${j}`, `└ ${label}`])
          })
        }
      }
    })
  } else {
    imapProviders.forEach((acc, i) => {
      items.push([`imap:${i}`, acc?.email ? `IMAP: ${acc.email}` : `IMAP 账户 ${i + 1}`])
    })
  }

  if (!items.some(([v]) => String(v).startsWith('imap:'))) {
    items.push(['imap:0', 'IMAP 服务商 1'])
  }

  const outlookAccounts = Array.isArray(settings['mail.outlook']) ? settings['mail.outlook'] : []
  const outlookNoTokenLabel = buildOutlookNoTokenLabel(meta.outlookStats)
  if (outlookAccounts.length > 0) {
    if (mode === 'dashboard') {
      items.push(['outlook', `Outlook (${outlookAccounts.length} 账户)`])
      items.push(['outlook:no-token', outlookNoTokenLabel])
    } else {
      items.push(['outlook', `Outlook（全部 ${outlookAccounts.length} 账户轮换）`])
      if (mode !== 'settings') {
        items.push(['outlook:no-token', outlookNoTokenLabel])
      }
      if (mode !== 'dashboard') {
        outlookAccounts.forEach((acc, i) => {
          const label = acc?.email ? acc.email : `Outlook 账户 ${i + 1}`
          items.push([`outlook:${i}`, `└ ${label}`])
        })
      }
    }
  }

  items.push(
    GPTMAIL_PROVIDER_OPTION,
    NPCMAIL_PROVIDER_OPTION,
    YYDSMAIL_PROVIDER_OPTION,
    CFWORKER_PROVIDER_OPTION,
  )
  return items
}

export function buildSettingsProviderOptions(settings) {
  return buildProviderOptions(settings, 'settings')
}

export function buildDashboardProviderOptions(settings, meta) {
  return buildProviderOptions(settings, 'dashboard', meta)
}

export function buildJobsProviderOptions(settings, meta) {
  return buildProviderOptions(settings, 'jobs', meta)
}
