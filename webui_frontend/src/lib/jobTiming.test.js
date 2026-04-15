import test from 'node:test'
import assert from 'node:assert/strict'
import { formatJobElapsed } from './jobTiming.js'

test('formatJobElapsed uses ended time when job already finished', () => {
  assert.equal(formatJobElapsed(100, 130), '30s')
  assert.equal(formatJobElapsed(100, 185), '1m 25s')
})

test('formatJobElapsed falls back to current time for running jobs', () => {
  const realNow = Date.now
  Date.now = () => 190_000
  try {
    assert.equal(formatJobElapsed(100), '1m 30s')
  } finally {
    Date.now = realNow
  }
})
