// pages/Jobs.jsx
import { useState, useEffect, useRef } from 'react'
import api from '../lib/api.js'
import { StatusBadge, Spinner } from '../components/Badge.jsx'
import { buildJobsProviderOptions, DEFAULT_JOBS_PROVIDER_OPTIONS } from '../lib/cfworkerConfig.js'
import { formatJobElapsed } from '../lib/jobTiming.js'
import { EMPTY_SUB2API_UPLOAD_CONFIG, normalizeSub2APIUploadConfig, serializeSub2APIUploadConfig } from '../lib/sub2apiUploadConfig.js'

function useProviderOptions() {
  const [opts, setOpts] = useState(DEFAULT_JOBS_PROVIDER_OPTIONS)
  useEffect(() => {
    api.getSettings().then((settings) => {
      setOpts(buildJobsProviderOptions(settings))
    }).catch(() => {})
  }, [])
  return opts
}

function IndeterminateCheckbox({ indeterminate, ...props }) {
  const ref = useRef(null)
  useEffect(() => { if (ref.current) ref.current.indeterminate = !!indeterminate }, [indeterminate])
  return <input type="checkbox" ref={ref} className="rounded cursor-pointer accent-blue-600" {...props} />
}

function BulkBar({ selCount, total, selAll, onSelectAll, onClearSel, children }) {
  if (selCount === 0 && !selAll) return null
  const displayCount = selAll ? total : selCount
  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 bg-gray-900 text-white rounded-2xl shadow-2xl px-5 py-3 text-sm whitespace-nowrap">
      <span className="font-medium">
        已选 <span className="text-blue-400 font-bold">{displayCount}</span> 个任务
        {selAll && <span className="ml-1 text-xs text-green-400 font-semibold">（全部）</span>}
      </span>
      {!selAll && selCount > 0 && total > selCount && (
        <button onClick={onSelectAll} className="text-xs text-blue-400 hover:text-blue-300 underline">
          选择全部 {total} 个
        </button>
      )}
      <div className="w-px h-4 bg-gray-700 flex-shrink-0" />
      {children}
      <button onClick={onClearSel} className="text-gray-500 hover:text-white text-lg leading-none ml-1">×</button>
    </div>
  )
}

export function Jobs() {
  const [jobs, setJobs]           = useState([])
  const [selected, setSelected]   = useState(null)
  const [detail, setDetail]       = useState(null)
  const [form, setForm]           = useState({
    count: 1,
    engine: 'camoufox',
    provider: 'imap:0',
    upload_provider: 'none',
    sub2api_upload: { ...EMPTY_SUB2API_UPLOAD_CONFIG },
  })
  const [starting, setStarting]   = useState(false)
  const [startErr, setStartErr]   = useState('')
  const logRef                    = useRef(null)
  const providerOpts              = useProviderOptions()
  const [jobGroupIdsText, setJobGroupIdsText] = useState('')
  const [jobModelWhitelistText, setJobModelWhitelistText] = useState('')

  // Bulk selection
  const [sel, setSel]       = useState(new Set())
  const [selAll, setSelAll] = useState(false)
  const [batchBusy, setBatchBusy] = useState(false)
  const [resultUploading, setResultUploading] = useState({})

  useEffect(() => {
    const poll = () => api.getJobs().then(setJobs).catch(() => {})
    poll()
    const id = setInterval(poll, 3000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    api.getMergedConfig().then((cfg) => {
      const normalized = normalizeSub2APIUploadConfig(cfg?.sub2api_upload)
      setForm((prev) => ({
        ...prev,
        upload_provider: typeof cfg?.upload_provider === 'string' ? cfg.upload_provider : 'none',
        sub2api_upload: normalized,
      }))
      setJobGroupIdsText(normalized.group_ids.join('\n'))
      setJobModelWhitelistText(normalized.model_whitelist.join('\n'))
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!selected) { setDetail(null); return }
    const poll = () => api.getJob(selected).then(d => { setDetail(d); if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight }).catch(() => {})
    poll()
    const id = setInterval(poll, 2000)
    return () => clearInterval(id)
  }, [selected])

  const startJob = async () => {
    setStarting(true); setStartErr('')
    try {
      const payload = {
        ...form,
        sub2api_upload: serializeSub2APIUploadConfig(form.sub2api_upload),
      }
      const { job_id } = await api.startJob(payload); setSelected(job_id); api.getJobs().then(setJobs)
    }
    catch (e) { setStartErr(e.message) }
    finally { setStarting(false) }
  }

  const setUploadField = (key, value) => {
    setForm((prev) => ({
      ...prev,
      sub2api_upload: {
        ...prev.sub2api_upload,
        [key]: value,
      },
    }))
  }
  const handleJobGroupIdsTextChange = (value) => {
    setJobGroupIdsText(value)
    setUploadField('group_ids', value.split(/[\n,]/).map(item => item.trim()).filter(Boolean))
  }
  const handleJobModelWhitelistTextChange = (value) => {
    setJobModelWhitelistText(value)
    setUploadField('model_whitelist', value.split(/[\n,]/).map(item => item.trim()).filter(Boolean))
  }

  const cancelJob = async (id, e) => { e.stopPropagation(); await api.cancelJob(id).catch(() => {}); api.getJobs().then(setJobs) }
  const deleteJob = async (id, e) => {
    e.stopPropagation()
    await api.deleteJob(id).catch(() => {})
    if (selected === id) { setSelected(null); setDetail(null) }
    api.getJobs().then(setJobs)
  }

  // Bulk selection helpers
  const allIds  = jobs.map(j => j.id)
  const allSel  = allIds.length > 0 && allIds.every(id => sel.has(id))
  const someSel = !allSel && allIds.some(id => sel.has(id))

  const toggleRow = (id) => { setSelAll(false); setSel(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n }) }
  const toggleAll = () => { setSelAll(false); setSel(s => { const n = new Set(s); if (allSel) allIds.forEach(id => n.delete(id)); else allIds.forEach(id => n.add(id)); return n }) }
  const clearSel  = () => { setSel(new Set()); setSelAll(false) }

  const handleBatchAction = async (action) => {
    const n = selAll ? jobs.length : sel.size
    const label = action === 'cancel' ? '取消' : '删除'
    if (!window.confirm(`确认${label} ${n} 个任务？`)) return
    setBatchBusy(true)
    try {
      await api.batchJobsAction(selAll ? { action, select_all: true } : { action, ids: [...sel] })
      clearSel()
      api.getJobs().then(setJobs)
      if (action === 'delete' && sel.has(selected)) { setSelected(null); setDetail(null) }
    } catch (e) { alert(`${label}失败：` + e.message) }
    finally { setBatchBusy(false) }
  }

  const handleResultUpload = async (email) => {
    setResultUploading((prev) => ({ ...prev, [email]: true }))
    try {
      const resp = await api.uploadCliProxy({ email })
      if (resp.ok) alert(`上传成功：${email}`)
      else alert(`上传失败：${resp.message || '未知错误'}`)
    } catch (e) {
      alert('上传失败：' + e.message)
    } finally {
      setResultUploading((prev) => ({ ...prev, [email]: false }))
    }
  }

  return (
    <div className="p-6 space-y-6 pb-24">
      <div>
        <h2 className="text-xl font-bold text-gray-800">注册任务</h2>
        <p className="text-sm text-gray-500 mt-0.5">启动并监控批量注册任务</p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Start form */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
          <h3 className="font-semibold text-gray-700 mb-4">新建任务</h3>
          <div className="space-y-3">
            <label className="block">
              <span className="text-xs text-gray-500 font-medium">注册数量</span>
              <input type="number" min={1} max={100} value={form.count}
                onChange={e => setForm(f => ({ ...f, count: +e.target.value }))}
                className="mt-1 block w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
            </label>
            <label className="block">
              <span className="text-xs text-gray-500 font-medium">浏览器引擎</span>
              <select value={form.engine} onChange={e => setForm(f => ({ ...f, engine: e.target.value }))}
                className="mt-1 block w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
                <option value="camoufox">Camoufox (推荐)</option>
                <option value="playwright">Playwright</option>
              </select>
            </label>
            <label className="block">
              <span className="text-xs text-gray-500 font-medium">邮件服务</span>
              <select value={form.provider} onChange={e => setForm(f => ({ ...f, provider: e.target.value }))}
                className="mt-1 block w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
                {providerOpts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
            <label className="block">
              <span className="text-xs text-gray-500 font-medium">上传目标</span>
              <select value={form.upload_provider} onChange={e => setForm(f => ({ ...f, upload_provider: e.target.value }))}
                className="mt-1 block w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
                <option value="none">不自动上传</option>
                <option value="cpa">CLI Proxy / CPA</option>
                <option value="sub2api">Sub2API</option>
              </select>
            </label>
            {form.upload_provider === 'sub2api' && (
              <div className="space-y-3 rounded-xl border border-gray-100 bg-gray-50/70 p-4">
                <p className="text-xs font-medium text-gray-600">Sub2API 任务覆盖</p>
                <label className="block">
                  <span className="text-xs text-gray-500 font-medium">Group IDs</span>
                  <textarea
                    rows={3}
                    value={jobGroupIdsText}
                    onChange={e => handleJobGroupIdsTextChange(e.target.value)}
                    className="mt-1 block w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-400"
                    placeholder={"1\n2"}
                  />
                </label>
                <label className="block">
                  <span className="text-xs text-gray-500 font-medium">Proxy ID</span>
                  <input type="number" min={1} value={form.sub2api_upload.proxy_id}
                    onChange={e => setUploadField('proxy_id', e.target.value)}
                    className="mt-1 block w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
                </label>
                <label className="block">
                  <span className="text-xs text-gray-500 font-medium">备注</span>
                  <input value={form.sub2api_upload.notes}
                    onChange={e => setUploadField('notes', e.target.value)}
                    className="mt-1 block w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <label className="block">
                    <span className="text-xs text-gray-500 font-medium">并发数</span>
                    <input type="number" min={1} value={form.sub2api_upload.concurrency}
                      onChange={e => setUploadField('concurrency', e.target.value)}
                      className="mt-1 block w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
                  </label>
                  <label className="block">
                    <span className="text-xs text-gray-500 font-medium">负载因子</span>
                    <input type="number" min={1} value={form.sub2api_upload.load_factor}
                      onChange={e => setUploadField('load_factor', e.target.value)}
                      className="mt-1 block w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
                  </label>
                  <label className="block">
                    <span className="text-xs text-gray-500 font-medium">优先级</span>
                    <input type="number" min={1} value={form.sub2api_upload.priority}
                      onChange={e => setUploadField('priority', e.target.value)}
                      className="mt-1 block w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
                  </label>
                  <label className="block">
                    <span className="text-xs text-gray-500 font-medium">账号计费倍率</span>
                    <input type="number" min={0} step="0.1" value={form.sub2api_upload.rate_multiplier}
                      onChange={e => setUploadField('rate_multiplier', e.target.value)}
                      className="mt-1 block w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
                  </label>
                </div>
                <label className="flex items-center gap-2 text-sm text-gray-700">
                  <input type="checkbox" checked={!!form.sub2api_upload.import_models}
                    onChange={e => setUploadField('import_models', e.target.checked)}
                    className="rounded accent-blue-600" />
                  自动获取可用模型
                </label>
                <label className="block">
                  <span className="text-xs text-gray-500 font-medium">模型白名单</span>
                  <textarea
                    rows={4}
                    value={jobModelWhitelistText}
                    onChange={e => handleJobModelWhitelistTextChange(e.target.value)}
                    className="mt-1 block w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-400"
                    placeholder={"gpt-5.4\ngpt-5.1-codex"}
                  />
                </label>
              </div>
            )}
            {startErr && <p className="text-xs text-red-500">{startErr}</p>}
            <button onClick={startJob} disabled={starting}
              className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white font-medium py-2.5 rounded-lg text-sm transition-colors">
              {starting ? <Spinner /> : '🚀'} {starting ? '启动中…' : '开始注册'}
            </button>
          </div>
        </div>

        {/* Job list */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden xl:col-span-2">
          <div className="px-5 py-4 border-b border-gray-100 flex items-center gap-3">
            {jobs.length > 0 && (
              <IndeterminateCheckbox
                checked={allSel || selAll}
                indeterminate={someSel && !selAll}
                onChange={toggleAll}
              />
            )}
            <h3 className="font-semibold text-gray-700">任务列表</h3>
          </div>
          {jobs.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-12">暂无任务</p>
          ) : (
            <div className="divide-y divide-gray-50">
              {jobs.map(j => {
                const checked = selAll || sel.has(j.id)
                return (
                  <div
                    key={j.id}
                    className={`flex items-center gap-3 px-5 py-3.5 transition-colors ${checked ? 'bg-blue-50' : j.id === selected ? 'bg-blue-50' : 'hover:bg-gray-50'}`}
                  >
                    {/* Checkbox (stops click propagation) */}
                    <div onClick={e => { e.stopPropagation(); toggleRow(j.id) }} className="flex-shrink-0">
                      <input type="checkbox" checked={checked} onChange={() => {}} className="rounded cursor-pointer accent-blue-600" />
                    </div>
                    {/* Row content (selects job for log) */}
                    <div className="flex-1 min-w-0 cursor-pointer" onClick={() => setSelected(j.id === selected ? null : j.id)}>
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs text-gray-700 font-semibold">{j.id}</span>
                        <StatusBadge status={j.status} />
                      </div>
                      <p className="text-xs text-gray-400 mt-0.5">{j.provider} · ×{j.count} · 成功 {j.success}/{j.done}</p>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0 ml-2">
                      {j.status === 'running' && <Spinner />}
                      <span className="text-xs text-gray-400">{formatJobElapsed(j.started, j.finished)}</span>
                      {j.status === 'running' && (
                        <button onClick={e => cancelJob(j.id, e)}
                          className="text-xs text-orange-400 hover:text-orange-600 border border-orange-200 hover:border-orange-400 px-1.5 py-0.5 rounded transition-colors"
                          title="取消任务">取消</button>
                      )}
                      <button onClick={e => deleteJob(j.id, e)}
                        className="text-gray-300 hover:text-red-500 transition-colors text-base" title="删除">×</button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* Log panel */}
      {selected && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
            <h3 className="font-semibold text-gray-700">
              任务日志 <span className="font-mono text-blue-500 text-sm">{selected}</span>
            </h3>
            {detail && (
              <div className="flex items-center gap-3 text-xs text-gray-500">
                <span>进度: {detail.done}/{detail.count}</span>
                <span>成功: {detail.success}</span>
                <StatusBadge status={detail.status} />
                {detail.status === 'running' && (
                  <button onClick={e => cancelJob(selected, e)}
                    className="text-xs text-orange-500 hover:text-orange-700 border border-orange-200 hover:border-orange-400 px-2 py-0.5 rounded transition-colors font-medium">
                    ⛔ 取消任务
                  </button>
                )}
              </div>
            )}
          </div>
          <div ref={logRef} className="log-terminal bg-gray-950 text-green-400 p-4 h-64 overflow-y-auto">
            {detail?.logs?.length
              ? detail.logs.map((line, i) => {
                  const isOAuth = line.includes('[OAuth]')
                  const isWarn  = line.includes('⚠️') || line.includes('错误') || line.includes('失败')
                  const isOk    = line.includes('✅') || line.includes('成功')
                  let cls = 'text-green-400'
                  if (isOAuth && isOk)   cls = 'text-blue-400 font-medium'
                  else if (isOAuth && isWarn) cls = 'text-yellow-400'
                  else if (isOAuth)      cls = 'text-cyan-400'
                  else if (isWarn)       cls = 'text-yellow-500'
                  return <div key={i} className={cls}>{line}</div>
                })
              : <span className="text-gray-600">等待日志…</span>
            }
          </div>
          {detail?.results?.length > 0 && (
            <div className="border-t border-gray-100 bg-white">
              <div className="px-5 py-4 border-b border-gray-100">
                <h4 className="font-semibold text-gray-700">任务结果</h4>
                <p className="text-xs text-gray-400 mt-0.5">仅对包含 access token 的结果开放手动上传。</p>
              </div>
              <div className="divide-y divide-gray-50">
                {detail.results.map((result, index) => {
                  const email = result.email || `result-${index}`
                  const canUpload = !!result.email && !!result.access_token
                  const uploading = !!resultUploading[email]
                  return (
                    <div key={`${email}-${index}`} className="px-5 py-3 flex items-center gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-mono text-xs text-gray-700 truncate">{result.email || '—'}</span>
                          <StatusBadge status={result.status || 'unknown'} />
                          {canUpload
                            ? <span className="text-xs px-1.5 py-0.5 rounded bg-green-100 text-green-700">有 Token</span>
                            : <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-400">无 Token</span>}
                        </div>
                        <p className="text-xs text-gray-400 mt-1">
                          {result.account_id ? `account_id: ${result.account_id}` : '当前结果未返回 account_id'}
                        </p>
                      </div>
                      <button
                        onClick={() => handleResultUpload(result.email)}
                        disabled={!canUpload || uploading}
                        title={canUpload ? '' : '该结果暂无可上传认证信息'}
                        className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-medium px-2.5 py-1.5 rounded-lg transition-colors"
                      >
                        {uploading ? '上传中…' : '上传 CPA'}
                      </button>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Bulk action bar */}
      <BulkBar selCount={sel.size} total={jobs.length} selAll={selAll} onSelectAll={() => setSelAll(true)} onClearSel={clearSel}>
        <button onClick={() => handleBatchAction('cancel')} disabled={batchBusy}
          className="flex items-center gap-1.5 bg-orange-500 hover:bg-orange-600 disabled:opacity-60 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors">
          {batchBusy ? '处理中…' : '⛔ 取消所选'}
        </button>
        <button onClick={() => handleBatchAction('delete')} disabled={batchBusy}
          className="flex items-center gap-1.5 bg-red-500 hover:bg-red-600 disabled:opacity-60 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors">
          {batchBusy ? '处理中…' : '🗑️ 删除所选'}
        </button>
      </BulkBar>
    </div>
  )
}
