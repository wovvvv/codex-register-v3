import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildImapProviderOptions,
  EMPTY_IMAP_PROVIDER,
  legacyUseAliasToAddressMode,
  normalizeImapProviders,
  serializeImapProviders,
  validateRegistrationDomain,
} from './imapProviders.js'

test('legacy flat IMAP accounts -> 单个 provider', () => {
  const result = normalizeImapProviders([
    { email: 'a@gmail.com', password: 'p1' },
    { email: 'b@qq.com', access_token: 'tk2' },
  ])

  assert.equal(result.length, 1)
  assert.equal(result[0].accounts.length, 2)
  assert.equal(result[0].accounts[0].email, 'a@gmail.com')
  assert.equal(result[0].accounts[0].credential, 'p1')
  assert.equal(result[0].accounts[1].email, 'b@qq.com')
  assert.equal(result[0].accounts[1].credential, 'tk2')
  assert.equal('email' in result[0], false)
  assert.equal('password' in result[0], false)
  assert.equal('access_token' in result[0], false)
})

test('legacy use_alias=true -> address_mode=plus_alias', () => {
  const mode = legacyUseAliasToAddressMode(true, 'x@example.com')
  assert.equal(mode, 'plus_alias')
})

test('legacy use_alias=null + Gmail/QQ 域名自动映射 plus_alias', () => {
  assert.equal(legacyUseAliasToAddressMode(null, 'x@gmail.com'), 'plus_alias')
  assert.equal(legacyUseAliasToAddressMode(undefined, 'x@qq.com'), 'plus_alias')
  assert.equal(legacyUseAliasToAddressMode(null, 'x@example.com'), 'inbox')
})

test('新 provider shape 保留 random_local_part + registration_domain', () => {
  const result = normalizeImapProviders([{
    name: 'Cloudflare IMAP',
    address_mode: 'random_local_part',
    registration_domain: 'dfghdfghd.xyz',
    accounts: [],
  }])

  assert.equal(result[0].address_mode, 'random_local_part')
  assert.equal(result[0].registration_domain, 'dfghdfghd.xyz')
})

test('provider-based 缺字段时补默认值', () => {
  const result = normalizeImapProviders([{ name: 'p1', accounts: [{ email: 'u@x.com' }] }])

  assert.equal(result.length, 1)
  assert.equal(result[0].name, 'p1')
  assert.equal(result[0].address_mode, EMPTY_IMAP_PROVIDER.address_mode)
  assert.equal(result[0].registration_domain, EMPTY_IMAP_PROVIDER.registration_domain)
  assert.deepEqual(result[0].accounts[0], { email: 'u@x.com', credential: '' })
})

test('normalize 后 provider 不保留 use_alias', () => {
  const result = normalizeImapProviders([{
    name: 'legacy-provider',
    use_alias: true,
    accounts: [{ email: 'x@gmail.com', credential: 'c' }],
  }])
  assert.equal(result[0].address_mode, 'plus_alias')
  assert.equal('use_alias' in result[0], false)
})

test('非法 registration_domain 在 normalize 阶段保留规范化值', () => {
  const result = normalizeImapProviders([{
    name: 'p1',
    address_mode: 'random_local_part',
    registration_domain: '  *.Bad_Domain.COM ',
    accounts: [],
  }])
  assert.equal(result[0].registration_domain, '*.bad_domain.com')
})

test('normalizeAccount 仅保留页面需要字段', () => {
  const result = normalizeImapProviders([
    { email: 'a@gmail.com', password: 'p1', access_token: 'tk', extra: 'ignored' },
  ])

  assert.deepEqual(result[0].accounts[0], {
    email: 'a@gmail.com',
    credential: 'p1',
  })
})

test('provider shape 判定支持混合/不完整数据', () => {
  const result = normalizeImapProviders([
    { email: 'legacy@example.com', password: 'p1' },
    { name: 'provider without accounts yet' },
  ])

  assert.equal(result.length, 2)
  assert.equal(result[0].name, 'provider without accounts yet')
  assert.deepEqual(result[0].accounts, [])
  assert.equal(result[1].name, '默认 IMAP 服务商')
  assert.deepEqual(result[1].accounts, [{ email: 'legacy@example.com', credential: 'p1' }])
})

test('legacy flat accounts 的 provider options 保持旧 selector 语义', () => {
  const result = buildImapProviderOptions([
    { email: 'legacy1@example.com', password: 'p1' },
    { email: 'legacy2@example.com', password: 'p2' },
  ])

  assert.deepEqual(result, [
    ['imap:0', 'IMAP: legacy1@example.com'],
    ['imap:1', 'IMAP: legacy2@example.com'],
  ])
})

test('provider-based 结构的 provider options 保持新 selector 语义', () => {
  const result = buildImapProviderOptions([{
    name: 'provider-a',
    accounts: [
      { email: 'a@example.com', credential: 'p1' },
      { email: 'b@example.com', credential: 'p2' },
    ],
  }])

  assert.deepEqual(result, [
    ['imap:0', 'provider-a（全部 2 账户轮换）'],
    ['imap:0:0', '└ a@example.com'],
    ['imap:0:1', '└ b@example.com'],
  ])
})

test('provider options 在混合/不完整数据下不误判', () => {
  const result = buildImapProviderOptions([
    { email: 'legacy@example.com', password: 'p1' },
    { name: 'provider without accounts yet' },
  ])

  assert.deepEqual(result, [
    ['imap:0', 'provider without accounts yet（全部 0 账户轮换）'],
    ['imap:1', '默认 IMAP 服务商（全部 1 账户轮换）'],
    ['imap:1:0', '└ legacy@example.com'],
  ])
})

test('normalize 阶段把未知 auth_type 回退到 password', () => {
  const result = normalizeImapProviders([{
    name: 'p1',
    auth_type: 'token',
    accounts: [],
  }])

  assert.equal(result[0].auth_type, 'password')
})

test('normalize 阶段把非法端口收敛到 993', () => {
  for (const port of ['', 0, -1, 65536, Number.NaN]) {
    const result = normalizeImapProviders([{ name: 'p1', port, accounts: [] }])
    assert.equal(result[0].port, 993)
  }
})

test('保存序列化后 provider 仅包含允许字段', () => {
  const serialized = serializeImapProviders([{
    name: ' provider ',
    host: ' imap.example.com ',
    port: 993,
    ssl: true,
    folder: ' INBOX ',
    auth_type: 'password',
    address_mode: 'plus_alias',
    registration_domain: ' Example.COM ',
    use_alias: true,
    email: 'legacy@x.com',
    password: 'legacy-pass',
    accounts: [{ email: ' user@x.com ', credential: ' c ' }],
  }])

  assert.deepEqual(Object.keys(serialized[0]).sort(), [
    'accounts',
    'address_mode',
    'auth_type',
    'folder',
    'host',
    'name',
    'port',
    'registration_domain',
    'ssl',
  ])
  assert.equal(serialized[0].registration_domain, 'example.com')
  assert.deepEqual(serialized[0].accounts[0], { email: 'user@x.com', credential: 'c' })
})

test('保存序列化时把非法端口收敛到 993', () => {
  for (const port of ['', 0, -1, 70000, Number.NaN]) {
    const serialized = serializeImapProviders([{ name: 'p1', port, accounts: [] }])
    assert.equal(serialized[0].port, 993)
  }
})

test('registration_domain 校验：合法/非法', () => {
  assert.equal(validateRegistrationDomain('  ExAmple-Mail.com  '), 'example-mail.com')
  assert.equal(validateRegistrationDomain('a.b'), 'a.b')

  assert.equal(validateRegistrationDomain('*.example.com'), '')
  assert.equal(validateRegistrationDomain('localhost'), '')
  assert.equal(validateRegistrationDomain('bad_domain.com'), '')
  assert.equal(validateRegistrationDomain('trailing-.com'), '')
})
