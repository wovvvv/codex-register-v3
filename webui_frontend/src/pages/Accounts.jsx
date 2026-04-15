// pages/Accounts.jsx
import { useState, useEffect, useCallback, useRef } from 'react'
import api from '../lib/api.js'
import { StatusBadge } from '../components/Badge.jsx'

const STATUSES = ['', '注册完成', 'failed', 'email_creation_failed', 'imported']
const PAGE_SIZE = 50

function CopyBtn({ text }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(text ?? '').then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <button onClick={copy} title="复制" className="text-gray-400 hover:text-blue-500 transition-colors ml-1">
      {copied ? '✓' : '⎘'}
    </button>
  )
}

function IndeterminateCheckbox({ indeterminate, className = '', ...props }) {
  const ref = useRef(null)
  useEffect(() => { if (ref.current) ref.current.indeterminate = !!indeterminate }, [indeterminate])
  return <input type="checkbox" ref={ref} className={`rounded cursor-pointer accent-blue-600 ${className}`} {...props} />
}

function BulkBar({ selCount, total, selAllDB, onSelectAllDB, onClearSel, children }) {
  if (selCount === 0 && !selAllDB) return null
  const displayCount = selAllDB ? total : selCount
  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 bg-gray-900 text-white rounded-2xl shadow-2xl px-5 py-3 text-sm whitespace-nowrap">
      <span className="font-medium">
        已选 <span className="text-blue-400 font-bold">{displayCount}</span> 条
        {selAllDB && <span className="ml-1 text-xs text-green-400 font-semibold">（全库）</span>}
      </span>
      {!selAllDB && selCount > 0 && total > selCount && onSelectAllDB && (
        <button onClick={onSelectAllDB} className="text-xs text-blue-400 hover:text-blue-300 underline">
          选择全部 {total} 条
        </button>
      )}
      <div className="w-px h-4 bg-gray-700 flex-shrink-0" />
      {children}
      <button onClick={onClearSel} className="text-gray-500 hover:text-white text-lg leading-none ml-1">×</button>
    </div>
  )
}

export function Accounts() {
  const [rows, setRows]       = useState([])
  const [total, setTotal]     = useState(0)
  const [status, setStatus]   = useState('')
  const [page, setPage]       = useState(0)
  const [loading, setLoading] = useState(false)
  const [sel, setSel]           = useState(new Set())
  const [selAllDB, setSelAllDB] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [uploading, setUploading] = useState({})
  const [sub2apiUploading, setSub2apiUploading] = useState({})
  const [batchUploading, setBatchUploading] = useState(false)
  const [batchSub2APIUploading, setBatchSub2APIUploading] = useState(false)
  const [exportingTokenZip, setExportingTokenZip] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    api.getAccounts({ status, limit: PAGE_SIZE, offset: page * PAGE_SIZE })
      .then(d => { setRows(d.items); setTotal(d.total) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [status, page])

  useEffect(() => { load() }, [load])
  useEffect(() => { setSel(new Set()); setSelAllDB(false) }, [status, page])

  const pages       = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const pageEmails  = rows.map(r => r.email)
  const allPageSel  = pageEmails.length > 0 && pageEmails.every(e => sel.has(e))
  const somePageSel = !allPageSel && pageEmails.some(e => sel.has(e))

  const toggleRow  = (email) => { setSelAllDB(false); setSel(s => { const n = new Set(s); n.has(email) ? n.delete(email) : n.add(email); return n }) }
  const togglePage = () => { setSelAllDB(false); setSel(s => { const n = new Set(s); if (allPageSel) pageEmails.forEach(e => n.delete(e)); else pageEmails.forEach(e => n.add(e)); return n }) }
  const clearSel   = () => { setSel(new Set()); setSelAllDB(false) }
  const tokenEmailSet = new Set(rows.filter(r => !!r.access_token).map(r => r.email))
  const refreshTokenEmailSet = new Set(rows.filter(r => !!r.refresh_token).map(r => r.email))
  const selectedExplicitEmails = [...sel]
  const selectedUploadableEmails = selectedExplicitEmails.filter(email => tokenEmailSet.has(email))
  const selectedSub2APIUploadableEmails = selectedExplicitEmails.filter(email => refreshTokenEmailSet.has(email))

  const handleDelete = async () => {
    const n = selAllDB ? total : sel.size
    if (!window.confirm(`确认删除 ${n} 条账户记录？此操作不可撤销。`)) return
    setDeleting(true)
    try {
      await api.batchDeleteAccounts(selAllDB ? { select_all: true, status } : { emails: [...sel] })
      clearSel(); load()
    } catch (e) { alert('删除失败：' + e.message) }
    finally { setDeleting(false) }
  }

  const handleUploadOne = async (email) => {
    setUploading((prev) => ({ ...prev, [email]: true }))
    try {
      const resp = await api.uploadCliProxy({ email })
      if (resp.ok) alert(`上传成功：${email}`)
      else alert(`上传失败：${resp.message || '未知错误'}`)
    } catch (e) {
      alert('上传失败：' + e.message)
    } finally {
      setUploading((prev) => ({ ...prev, [email]: false }))
    }
  }

  const handleBatchUpload = async () => {
    if (selAllDB) {
      alert('批量上传仅支持当前显式选中的邮箱集合，不支持“全库选择”。')
      return
    }
    if (selectedExplicitEmails.length === 0) {
      alert('请先勾选要上传的账号。')
      return
    }
    if (selectedUploadableEmails.length === 0) {
      alert('所选账号均无 access_token，无法上传 CPA。')
      return
    }

    setBatchUploading(true)
    try {
      const resp = await api.uploadCliProxyBatch({ emails: selectedUploadableEmails })
      const skipped = selectedExplicitEmails.length - selectedUploadableEmails.length
      const skippedHint = skipped > 0 ? `，跳过无 access_token ${skipped} 条` : ''
      alert(`批量上传完成：成功 ${resp.success}/${resp.total}${skippedHint}`)
    } catch (e) {
      alert('批量上传失败：' + e.message)
    } finally {
      setBatchUploading(false)
    }
  }

  const handleUploadOneSub2API = async (email) => {
    setSub2apiUploading((prev) => ({ ...prev, [email]: true }))
    try {
      const resp = await api.uploadSub2API({ email })
      if (resp.ok) alert(`上传成功：${email}`)
      else alert(`上传失败：${resp.message || '未知错误'}`)
    } catch (e) {
      alert('上传失败：' + e.message)
    } finally {
      setSub2apiUploading((prev) => ({ ...prev, [email]: false }))
    }
  }

  const handleBatchUploadSub2API = async () => {
    if (selAllDB) {
      alert('批量上传仅支持当前显式选中的邮箱集合，不支持“全库选择”。')
      return
    }
    if (selectedExplicitEmails.length === 0) {
      alert('请先勾选要上传的账号。')
      return
    }
    if (selectedSub2APIUploadableEmails.length === 0) {
      alert('所选账号均无 refresh_token，无法上传 Sub2API。')
      return
    }

    setBatchSub2APIUploading(true)
    try {
      const resp = await api.uploadSub2APIBatch({ emails: selectedSub2APIUploadableEmails })
      const skipped = selectedExplicitEmails.length - selectedSub2APIUploadableEmails.length
      const skippedHint = skipped > 0 ? `，跳过无 refresh_token ${skipped} 条` : ''
      alert(`批量上传完成：成功 ${resp.success}/${resp.total}${skippedHint}`)
    } catch (e) {
      alert('批量上传失败：' + e.message)
    } finally {
      setBatchSub2APIUploading(false)
    }
  }

  const handleExportTokenZip = async () => {
    setExportingTokenZip(true)
    try {
      const body = selAllDB || sel.size === 0
        ? { select_all: true, status }
        : { emails: [...sel] }

      const { blob, filename } = await api.exportTokenZip(body)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (e) {
      alert('导出失败：' + e.message)
    } finally {
      setExportingTokenZip(false)
    }
  }

  return (
    <div className="p-6 space-y-4 pb-24">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-xl font-bold text-gray-800">账户列表</h2>
          <p className="text-sm text-gray-500 mt-0.5">共 {total} 条记录</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <select value={status} onChange={e => { setStatus(e.target.value); setPage(0) }}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
            {STATUSES.map(s => <option key={s} value={s}>{s || '全部状态'}</option>)}
          </select>
          <a href={api.exportUrl('csv')} className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 transition-colors">导出 CSV</a>
          <button
            onClick={handleExportTokenZip}
            disabled={exportingTokenZip}
            className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-60 transition-colors"
          >
            {exportingTokenZip ? '导出中…' : '导出 Token ZIP'}
          </button>
          <button onClick={load} className="bg-blue-600 hover:bg-blue-700 text-white rounded-lg px-3 py-2 text-sm font-medium transition-colors">刷新</button>
        </div>
      </div>

      {/* 全库选择提示 */}
      {allPageSel && !selAllDB && total > rows.length && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg px-4 py-2.5 flex items-center gap-3 text-sm">
          <span className="text-blue-700">当前页 {rows.length} 条已全选。</span>
          <button onClick={() => setSelAllDB(true)} className="text-blue-600 hover:text-blue-800 font-semibold underline text-xs">
            选择全部数据库 {total} 条记录
          </button>
        </div>
      )}
      {selAllDB && (
        <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-2.5 flex items-center gap-3 text-sm">
          <span className="text-green-700">已选中全部数据库 <strong>{total}</strong> 条记录。</span>
          <button onClick={clearSel} className="text-green-600 hover:text-green-800 underline text-xs">取消全选</button>
        </div>
      )}

      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50">
              <th className="px-4 py-3 w-10">
                <IndeterminateCheckbox
                  checked={allPageSel || selAllDB}
                  indeterminate={somePageSel && !selAllDB}
                  onChange={togglePage}
                />
              </th>
              {['邮箱', '密码', '状态', '服务商', 'Access Token', '注册时间', '操作'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {loading && rows.length === 0 && <tr><td colSpan={8} className="text-center py-12 text-gray-400">加载中…</td></tr>}
            {!loading && rows.length === 0 && <tr><td colSpan={8} className="text-center py-12 text-gray-400">暂无数据</td></tr>}
            {rows.map(r => {
              const checked = selAllDB || sel.has(r.email)
              const canUpload = !!r.access_token
              const canUploadSub2API = !!r.refresh_token
              const rowUploading = !!uploading[r.email]
              const rowSub2APIUploading = !!sub2apiUploading[r.email]
              return (
                <tr key={r.email} className={`transition-colors ${checked ? 'bg-blue-50' : 'hover:bg-gray-50'}`}>
                  <td className="px-4 py-3 w-10">
                    <input type="checkbox" checked={checked} onChange={() => toggleRow(r.email)} className="rounded cursor-pointer accent-blue-600" />
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-700 whitespace-nowrap">{r.email}<CopyBtn text={r.email} /></td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-500 whitespace-nowrap"><span className="select-all">{r.password}</span><CopyBtn text={r.password} /></td>
                  <td className="px-4 py-3"><StatusBadge status={r.status} /></td>
                  <td className="px-4 py-3 text-xs text-gray-500">{r.provider || '—'}</td>
                  <td className="px-4 py-3 max-w-[180px]">
                    {r.access_token
                      ? <div className="flex items-center gap-1"><span className="font-mono text-xs text-gray-400 truncate">{r.access_token.slice(0, 20)}…</span><CopyBtn text={r.access_token} /></div>
                      : <span className="text-gray-300 text-xs">—</span>}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-400 whitespace-nowrap">{r.created_at?.slice(0, 19) || '—'}</td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleUploadOne(r.email)}
                        disabled={!canUpload || rowUploading}
                        title={canUpload ? '' : '该账号暂无可上传认证信息'}
                        className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-medium px-2.5 py-1.5 rounded-lg transition-colors"
                      >
                        {rowUploading ? '上传中…' : '上传 CPA'}
                      </button>
                      <button
                        onClick={() => handleUploadOneSub2API(r.email)}
                        disabled={!canUploadSub2API || rowSub2APIUploading}
                        title={canUploadSub2API ? '' : '该账号暂无 refresh_token，无法上传 Sub2API'}
                        className="bg-teal-600 hover:bg-teal-700 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-medium px-2.5 py-1.5 rounded-lg transition-colors"
                      >
                        {rowSub2APIUploading ? '上传中…' : '上传 Sub2API'}
                      </button>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-gray-500">第 {page + 1} / {pages} 页 · 共 {total} 条</span>
          <div className="flex gap-1">
            <button disabled={page === 0} onClick={() => setPage(p => p - 1)} className="px-3 py-1 rounded border border-gray-200 disabled:opacity-40 hover:bg-gray-50">上一页</button>
            <button disabled={page >= pages - 1} onClick={() => setPage(p => p + 1)} className="px-3 py-1 rounded border border-gray-200 disabled:opacity-40 hover:bg-gray-50">下一页</button>
          </div>
        </div>
      )}

      <BulkBar selCount={sel.size} total={total} selAllDB={selAllDB} onSelectAllDB={() => setSelAllDB(true)} onClearSel={clearSel}>
        <button
          onClick={handleBatchUpload}
          disabled={batchUploading || selAllDB || selectedUploadableEmails.length === 0}
          title={selAllDB ? '批量上传仅支持显式选中的邮箱集合' : (selectedUploadableEmails.length === 0 ? '所选账号暂无可上传认证信息' : '')}
          className="flex items-center gap-1.5 bg-indigo-500 hover:bg-indigo-600 disabled:opacity-60 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
        >
          {batchUploading ? '上传中…' : '⬆️ 上传所选'}
        </button>
        <button
          onClick={handleBatchUploadSub2API}
          disabled={batchSub2APIUploading || selAllDB || selectedSub2APIUploadableEmails.length === 0}
          title={selAllDB ? '批量上传仅支持显式选中的邮箱集合' : (selectedSub2APIUploadableEmails.length === 0 ? '所选账号暂无 refresh_token' : '')}
          className="flex items-center gap-1.5 bg-teal-500 hover:bg-teal-600 disabled:opacity-60 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
        >
          {batchSub2APIUploading ? '上传中…' : '⬆️ 上传 Sub2API'}
        </button>
        <button onClick={handleDelete} disabled={deleting}
          className="flex items-center gap-1.5 bg-red-500 hover:bg-red-600 disabled:opacity-60 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors">
          {deleting ? '删除中…' : '🗑️ 删除所选'}
        </button>
      </BulkBar>
    </div>
  )
}
