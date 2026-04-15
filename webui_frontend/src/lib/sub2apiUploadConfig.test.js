import test from 'node:test'
import assert from 'node:assert/strict'

import {
  EMPTY_SUB2API_UPLOAD_CONFIG,
  normalizeSub2APIUploadConfig,
  serializeSub2APIUploadConfig,
} from './sub2apiUploadConfig.js'

test('默认 Sub2API 上传配置归一化', () => {
  const normalized = normalizeSub2APIUploadConfig(undefined)
  assert.deepEqual(normalized, EMPTY_SUB2API_UPLOAD_CONFIG)
  assert.equal(normalized.base_url, '')
  assert.equal(normalized.api_key, '')
  assert.deepEqual(normalized.group_ids, [])
  assert.equal(normalized.priority, 2)
  assert.equal(normalized.import_models, false)
  assert.deepEqual(normalized.model_whitelist, [])
})

test('serialize 保留核心字段并清理白名单', () => {
  const serialized = serializeSub2APIUploadConfig({
    base_url: ' http://sub2api:8080/ ',
    api_key: ' worker-secret ',
    group_ids: ['9', '10'],
    proxy_id: '7',
    notes: ' from worker ',
    concurrency: '1',
    load_factor: '1',
    priority: '2',
    rate_multiplier: '0.5',
    import_models: true,
    model_whitelist: ['gpt-5.4', ' ', 'gpt-5.4', 'gpt-4.1'],
  })

  assert.deepEqual(serialized, {
    base_url: 'http://sub2api:8080',
    api_key: 'worker-secret',
    group_ids: [9, 10],
    proxy_id: 7,
    notes: 'from worker',
    concurrency: 1,
    load_factor: 1,
    priority: 2,
    rate_multiplier: 0.5,
    import_models: true,
    model_whitelist: ['gpt-5.4', 'gpt-4.1'],
  })
})
