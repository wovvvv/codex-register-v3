const ADDRESS_MODES = new Set(['inbox', 'plus_alias', 'random_local_part'])
const AUTH_TYPES = new Set(['password', 'oauth2'])
const ALIAS_AUTO_DOMAINS = new Set(['qq.com', 'gmail.com'])
const DEFAULT_PROVIDER_NAME = '默认 IMAP 服务商'

export const EMPTY_IMAP_ACCOUNT = { email: '', credential: '' }

export const EMPTY_IMAP_PROVIDER = {
  name: '新 IMAP 服务商',
  host: '',
  port: 993,
  ssl: true,
  folder: 'INBOX',
  auth_type: 'password',
  address_mode: 'inbox',
  registration_domain: '',
  accounts: [],
}

function normalizeRegistrationDomain(value) {
  return String(value || '').trim().toLowerCase()
}

function normalizePort(value) {
  if (value === '' || value === null || value === undefined) {
    return EMPTY_IMAP_PROVIDER.port
  }
  const port = typeof value === 'string' ? Number(value.trim()) : Number(value)
  if (!Number.isInteger(port) || port <= 0 || port > 65535) {
    return EMPTY_IMAP_PROVIDER.port
  }
  return port
}

function normalizeAuthType(value) {
  const authType = String(value || '').trim().toLowerCase()
  return AUTH_TYPES.has(authType) ? authType : EMPTY_IMAP_PROVIDER.auth_type
}

function normalizeAddressMode(mode, useAlias, accountEmail = '') {
  const explicit = typeof mode === 'string' ? mode.trim().toLowerCase() : ''
  if (ADDRESS_MODES.has(explicit)) return explicit
  return legacyUseAliasToAddressMode(useAlias, accountEmail)
}

function normalizeAccount(raw) {
  return {
    email: (raw?.email || '').trim(),
    credential: (raw?.credential || raw?.password || raw?.access_token || '').trim(),
  }
}

function normalizeProvider(raw, fallbackName = EMPTY_IMAP_PROVIDER.name) {
  const accounts = Array.isArray(raw?.accounts) ? raw.accounts.map(normalizeAccount) : []
  const registrationDomain = normalizeRegistrationDomain(raw?.registration_domain)
  const name = String(raw?.name || '').trim() || fallbackName
  const host = String(raw?.host || '').trim()
  const folder = String(raw?.folder || '').trim() || EMPTY_IMAP_PROVIDER.folder
  return {
    name,
    host,
    port: normalizePort(raw?.port),
    ssl: raw?.ssl === undefined ? EMPTY_IMAP_PROVIDER.ssl : !!raw.ssl,
    folder,
    auth_type: normalizeAuthType(raw?.auth_type),
    address_mode: normalizeAddressMode(raw?.address_mode, raw?.use_alias, accounts[0]?.email),
    registration_domain: registrationDomain,
    accounts,
  }
}

function isLegacyAccountEntry(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return false
  return ('email' in raw || 'password' in raw || 'access_token' in raw || 'credential' in raw) && !('accounts' in raw)
}

function isProviderEntry(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return false
  return 'accounts' in raw || !isLegacyAccountEntry(raw)
}

export function legacyUseAliasToAddressMode(useAlias, accountEmail = '') {
  if (typeof useAlias === 'boolean') {
    return useAlias ? 'plus_alias' : 'inbox'
  }
  const email = String(accountEmail || '').trim().toLowerCase()
  const domain = email.includes('@') ? email.split('@').pop() : ''
  return ALIAS_AUTO_DOMAINS.has(domain) ? 'plus_alias' : 'inbox'
}

export function validateRegistrationDomain(value) {
  const d = String(value || '').trim().toLowerCase()
  if (!d) return ''
  if (d.includes('*')) return ''
  if (!d.includes('.')) return ''
  const ok = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/.test(d)
  return ok ? d : ''
}

export function normalizeImapProviders(raw) {
  const list = Array.isArray(raw) ? raw : []
  if (list.length === 0) return []

  const providers = []
  const accounts = []

  list.forEach((item) => {
    if (isLegacyAccountEntry(item)) {
      accounts.push(normalizeAccount(item))
      return
    }
    if (isProviderEntry(item)) {
      providers.push(item)
    }
  })

  const normalizedProviders = providers.map((prov, i) => normalizeProvider(prov, `IMAP 服务商 ${i + 1}`))
  if (accounts.length === 0) {
    return normalizedProviders
  }

  const defaultProvider = normalizeProvider({ name: DEFAULT_PROVIDER_NAME, accounts }, DEFAULT_PROVIDER_NAME)
  return normalizedProviders.length > 0 ? [...normalizedProviders, defaultProvider] : [defaultProvider]
}

export function serializeImapProviders(raw) {
  const providers = Array.isArray(raw) ? raw : []
  return providers.map((prov, i) => {
    const normalizedProvider = normalizeProvider(prov, `IMAP 服务商 ${i + 1}`)
    return {
      name: normalizedProvider.name,
      host: normalizedProvider.host,
      port: normalizedProvider.port,
      ssl: normalizedProvider.ssl,
      folder: normalizedProvider.folder,
      auth_type: normalizedProvider.auth_type,
      address_mode: normalizedProvider.address_mode,
      registration_domain: normalizeRegistrationDomain(normalizedProvider.registration_domain),
      accounts: normalizedProvider.accounts.map(acc => ({
        email: String(acc.email || '').trim(),
        credential: String(acc.credential || '').trim(),
      })),
    }
  })
}

export function buildImapProviderOptions(raw) {
  const list = Array.isArray(raw) ? raw : []
  if (list.length > 0 && list.every(isLegacyAccountEntry)) {
    return list.map((acc, i) => [
      `imap:${i}`,
      acc.email ? `IMAP: ${String(acc.email).trim()}` : `IMAP 账户 ${i + 1}`,
    ])
  }

  const providers = normalizeImapProviders(raw)
  if (providers.length === 0) {
    return [['imap:0', 'IMAP 服务商 1']]
  }

  const items = []
  providers.forEach((prov, i) => {
    const name = prov.name || `IMAP 服务商 ${i + 1}`
    const accounts = Array.isArray(prov.accounts) ? prov.accounts : []
    items.push([`imap:${i}`, `${name}（全部 ${accounts.length} 账户轮换）`])
    accounts.forEach((acc, j) => {
      items.push([`imap:${i}:${j}`, `└ ${acc.email || `账户 ${j + 1}`}`])
    })
  })
  return items
}
