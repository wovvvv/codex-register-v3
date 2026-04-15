import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  CFWORKER_PROVIDER_OPTION,
  buildDashboardProviderOptions,
  buildJobsProviderOptions,
  buildSettingsProviderOptions,
} from './cfworkerConfig.js'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const pagesDir = path.resolve(__dirname, '../pages')

function readPage(name) {
  return fs.readFileSync(path.join(pagesDir, name), 'utf8')
}

test('Settings/Dashboard/Jobs 的 provider options 源包含 CF Worker', () => {
  assert.equal(CFWORKER_PROVIDER_OPTION[0], 'cfworker')
  assert.equal(CFWORKER_PROVIDER_OPTION[1], 'CF Worker')

  const settingsOpts = buildSettingsProviderOptions({})
  const dashboardOpts = buildDashboardProviderOptions({})
  const jobsOpts = buildJobsProviderOptions({})

  assert.equal(settingsOpts.some(([value, label]) => value === 'cfworker' && label === 'CF Worker'), true)
  assert.equal(dashboardOpts.some(([value, label]) => value === 'cfworker' && label === 'CF Worker'), true)
  assert.equal(jobsOpts.some(([value, label]) => value === 'cfworker' && label === 'CF Worker'), true)

  for (const page of ['Settings.jsx', 'Dashboard.jsx', 'Jobs.jsx']) {
    const source = readPage(page)
    assert.match(source, /build(Settings|Dashboard|Jobs)ProviderOptions/)
  }
})

test('现有 IMAP / Outlook provider 选项仍存在', () => {
  const sample = {
    'mail.imap': [
      { name: 'p1', accounts: [{ email: 'a@x.com' }] },
      { email: 'legacy@x.com' },
    ],
    'mail.outlook': [{ email: 'o@x.com' }],
  }

  const settingsOpts = buildSettingsProviderOptions(sample)
  const dashboardOpts = buildDashboardProviderOptions(sample)
  const jobsOpts = buildJobsProviderOptions(sample)

  for (const opts of [settingsOpts, dashboardOpts, jobsOpts]) {
    assert.equal(opts.some(([value]) => String(value).startsWith('imap:')), true)
    assert.equal(opts.some(([value]) => String(value).startsWith('outlook')), true)
  }
})

test('Jobs 和 Dashboard 暴露 outlook:no-token 轮换选项', () => {
  const sample = {
    'mail.outlook': [{ email: 'o1@x.com' }, { email: 'o2@x.com' }],
  }

  const settingsOpts = buildSettingsProviderOptions(sample)
  const dashboardOpts = buildDashboardProviderOptions(sample)
  const jobsOpts = buildJobsProviderOptions(sample)

  assert.equal(settingsOpts.some(([value]) => value === 'outlook:no-token'), false)
  assert.equal(dashboardOpts.some(([value]) => value === 'outlook:no-token'), true)
  assert.equal(jobsOpts.some(([value]) => value === 'outlook:no-token'), true)
})

test('outlook:no-token 标签展示未获取 token 的剩余数量', () => {
  const sample = {
    'mail.outlook': [{ email: 'o1@x.com' }, { email: 'o2@x.com' }, { email: 'o3@x.com' }],
  }

  const jobsOpts = buildJobsProviderOptions(sample, {
    outlookStats: { configured: 3, with_token: 1, without_token: 2 },
  })
  const dashboardOpts = buildDashboardProviderOptions(sample, {
    outlookStats: { configured: 3, with_token: 1, without_token: 2 },
  })

  assert.equal(
    jobsOpts.find(([value]) => value === 'outlook:no-token')?.[1],
    'Outlook（仅未获取 Access Token 账户轮换，剩余 2 个）',
  )
  assert.equal(
    dashboardOpts.find(([value]) => value === 'outlook:no-token')?.[1],
    'Outlook（仅未获取 Access Token 账户轮换，剩余 2 个）',
  )
})

test('Jobs 页只保留上传目标，不再展示 Sub2API 任务覆盖字段', () => {
  const source = readPage('Jobs.jsx')

  assert.match(source, /上传目标/)
  assert.doesNotMatch(source, /Sub2API 任务覆盖/)
  assert.doesNotMatch(source, /Group IDs/)
  assert.doesNotMatch(source, /模型白名单/)
  assert.doesNotMatch(source, /serializeSub2APIUploadConfig/)
  assert.doesNotMatch(source, /EMPTY_SUB2API_UPLOAD_CONFIG/)
})
