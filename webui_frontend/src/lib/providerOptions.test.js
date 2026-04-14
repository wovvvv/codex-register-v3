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

test('Outlook 拆分 provider family：fetch_method 按 trim+lowercase 归类，legacy 缺省归入 graph', () => {
  const sample = {
    'mail.outlook': [
      { email: 'imap1@x.com', fetch_method: ' IMAP ' },
      { email: 'graph1@x.com', fetch_method: ' graph ' },
      { email: 'graph2@x.com' },
    ],
  }

  const settingsOpts = buildSettingsProviderOptions(sample)
  const dashboardOpts = buildDashboardProviderOptions(sample)
  const jobsOpts = buildJobsProviderOptions(sample)

  assert.equal(settingsOpts.some(([value]) => value === 'outlook:no-token'), false)
  assert.equal(dashboardOpts.some(([value]) => value === 'outlook:no-token'), false)
  assert.equal(jobsOpts.some(([value]) => value === 'outlook:no-token'), false)

  assert.equal(dashboardOpts.some(([value]) => value === 'outlook'), true)
  assert.equal(dashboardOpts.some(([value]) => value === 'outlook-imap'), true)
  assert.equal(dashboardOpts.some(([value]) => value === 'outlook-graph'), true)
  assert.equal(dashboardOpts.find(([value]) => value === 'outlook-imap')?.[1], 'Outlook IMAP（1 账户轮换）')
  assert.equal(dashboardOpts.find(([value]) => value === 'outlook-graph')?.[1], 'Outlook Graph（2 账户轮换）')

  assert.equal(jobsOpts.some(([value]) => value === 'outlook'), true)
  assert.equal(jobsOpts.some(([value]) => value === 'outlook-imap'), true)
  assert.equal(jobsOpts.some(([value]) => value === 'outlook-graph'), true)
})

test('Jobs 包含 mixed/filter fixed selectors，且 Outlook fixed 标签带 IMAP/Graph 前缀', () => {
  const sample = {
    'mail.outlook': [
      { email: 'imap1@x.com', fetch_method: ' IMAP ' },
      { email: 'graph1@x.com', fetch_method: ' graph ' },
      { email: 'graph2@x.com' },
    ],
  }

  const jobsOpts = buildJobsProviderOptions(sample)

  assert.equal(jobsOpts.some(([value]) => value === 'outlook:0'), true)
  assert.equal(jobsOpts.some(([value]) => value === 'outlook-imap:0'), true)
  assert.equal(jobsOpts.some(([value]) => value === 'outlook-graph:0'), true)

  assert.equal(jobsOpts.find(([value]) => value === 'outlook-imap:0')?.[1], '└ IMAP: imap1@x.com')
  assert.equal(jobsOpts.find(([value]) => value === 'outlook-graph:0')?.[1], '└ Graph: graph1@x.com')
  assert.equal(jobsOpts.find(([value]) => value === 'outlook-graph:1')?.[1], '└ Graph: graph2@x.com')
})

test('Dashboard/Jobs 不暴露空的 Outlook split provider family', () => {
  const graphOnlySample = {
    'mail.outlook': [
      { email: 'legacy@x.com' },
      { email: 'graph1@x.com', fetch_method: ' Graph ' },
    ],
  }
  const imapOnlySample = {
    'mail.outlook': [
      { email: 'imap1@x.com', fetch_method: ' IMAP ' },
    ],
  }

  const graphOnlyDashboardOpts = buildDashboardProviderOptions(graphOnlySample)
  const graphOnlyJobsOpts = buildJobsProviderOptions(graphOnlySample)
  const imapOnlyDashboardOpts = buildDashboardProviderOptions(imapOnlySample)
  const imapOnlyJobsOpts = buildJobsProviderOptions(imapOnlySample)

  assert.equal(graphOnlyDashboardOpts.some(([value]) => value === 'outlook-imap'), false)
  assert.equal(graphOnlyJobsOpts.some(([value]) => value === 'outlook-imap'), false)
  assert.equal(graphOnlyJobsOpts.some(([value]) => value === 'outlook-imap:0'), false)
  assert.equal(graphOnlyDashboardOpts.some(([value]) => value === 'outlook-graph'), true)

  assert.equal(imapOnlyDashboardOpts.some(([value]) => value === 'outlook-graph'), false)
  assert.equal(imapOnlyJobsOpts.some(([value]) => value === 'outlook-graph'), false)
  assert.equal(imapOnlyJobsOpts.some(([value]) => value === 'outlook-graph:0'), false)
  assert.equal(imapOnlyDashboardOpts.some(([value]) => value === 'outlook-imap'), true)
})
