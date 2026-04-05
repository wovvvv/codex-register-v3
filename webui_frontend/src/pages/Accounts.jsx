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
          <a href={api.exportUrl('json')} className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 transition-colors">导出 JSON</a>
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
              {['邮箱', '密码', '状态', '服务商', 'Access Token', '注册时间'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {loading && rows.length === 0 && <tr><td colSpan={7} className="text-center py-12 text-gray-400">加载中…</td></tr>}
            {!loading && rows.length === 0 && <tr><td colSpan={7} className="text-center py-12 text-gray-400">暂无数据</td></tr>}
            {rows.map(r => {
              const checked = selAllDB || sel.has(r.email)
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
        <button onClick={handleDelete} disabled={deleting}
          className="flex items-center gap-1.5 bg-red-500 hover:bg-red-600 disabled:opacity-60 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors">
          {deleting ? '删除中…' : '🗑️ 删除所选'}
        </button>
      </BulkBar>
    </div>
  )
}
