import test from 'node:test'
import assert from 'node:assert/strict'

import {
  normalizeCfworkerConfig,
  serializeCfworkerConfig,
} from './cfworkerConfig.js'

test('domains 归一化：trim/lowercase/dedupe', () => {
  const normalized = normalizeCfworkerConfig({
    domains: [' Foo.COM ', 'foo.com', 'BAR.com  ', '', '  '],
  })

  assert.deepEqual(normalized.domains, ['foo.com', 'bar.com'])
})

test('enabled_domains 过滤为 domains 子集', () => {
  const normalized = normalizeCfworkerConfig({
    domains: ['a.com', 'b.com'],
    enabled_domains: ['A.com', 'c.com', '  b.com  '],
  })

  assert.deepEqual(normalized.enabled_domains, ['a.com', 'b.com'])
})

test('空 domains 时 enabled_domains 折叠为空', () => {
  const normalized = normalizeCfworkerConfig({
    domains: [],
    enabled_domains: ['a.com'],
  })

  assert.deepEqual(normalized.enabled_domains, [])
})

test('domain pool 存在时 domain 序列化清空', () => {
  const serialized = serializeCfworkerConfig({
    domain: 'single.com',
    domains: ['a.com'],
    enabled_domains: ['a.com'],
  })

  assert.equal(serialized.domain, '')
  assert.deepEqual(serialized.domains, ['a.com'])
})

test('random_subdomain 归一化为 boolean', () => {
  assert.equal(normalizeCfworkerConfig({ random_subdomain: 1 }).random_subdomain, true)
  assert.equal(normalizeCfworkerConfig({ random_subdomain: 0 }).random_subdomain, false)
})
