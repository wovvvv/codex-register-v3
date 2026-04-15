export function formatJobElapsed(started, finished = null) {
  const end = typeof finished === 'number' ? finished : Date.now() / 1000
  const s = Math.max(0, Math.floor(end - started))
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${s % 60}s`
}
