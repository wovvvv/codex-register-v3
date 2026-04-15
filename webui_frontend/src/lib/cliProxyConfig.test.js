import test from 'node:test'
import assert from 'node:assert/strict'

import {
  EMPTY_CLI_PROXY_CONFIG,
  normalizeCliProxyConfig,
  serializeCliProxyConfig,
} from './cliProxyConfig.js'

test('默认配置归一化', () => {
  const normalized = normalizeCliProxyConfig(undefined)
  assert.deepEqual(normalized, EMPTY_CLI_PROXY_CONFIG)
  assert.equal(normalized.cpa_url, '')
  assert.equal(normalized.monitor_interval_minutes, 180)
  assert.equal(normalized.monitor_active_probe, false)
  assert.equal(normalized.monitor_probe_timeout, 8)
})

test('旧版 local/remote 配置自动迁移为单一 cpa_url', () => {
  const normalized = normalizeCliProxyConfig({
    target: 'remote',
    local_url: 'http://127.0.0.1:8317',
    remote_url: 'https://cpa.opentan.xyz/management.html#/',
  })
  assert.equal(normalized.cpa_url, 'https://cpa.opentan.xyz/management.html#/')
})

test('cpa_url 去除首尾空格但保留用户输入结构', () => {
  const normalized = normalizeCliProxyConfig({
    cpa_url: '  http://127.0.0.1:8317/management.html#/  ',
  })
  assert.equal(normalized.cpa_url, 'http://127.0.0.1:8317/management.html#/')
})

test('serialize 保留核心字段', () => {
  const serialized = serializeCliProxyConfig({
    enabled: 'true',
    cpa_url: ' http://127.0.0.1:8317/management.html#/ ',
    api_key: '  secret-key  ',
    monitor_interval_minutes: '10',
    monitor_active_probe: 'true',
    monitor_probe_timeout: '15',
  })

  assert.deepEqual(serialized, {
    enabled: true,
    cpa_url: 'http://127.0.0.1:8317/management.html#/',
    api_key: 'secret-key',
    monitor_interval_minutes: 10,
    monitor_active_probe: true,
    monitor_probe_timeout: 15,
  })
})
