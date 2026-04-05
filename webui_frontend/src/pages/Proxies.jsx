// pages/Proxies.jsx
import { useState, useEffect, useRef } from 'react'
import api from '../lib/api.js'
import { Badge, Spinner } from '../components/Badge.jsx'

function fmt(ts) {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
}

function IndeterminateCheckbox({ indeterminate, ...props }) {
  const ref = useRef(null)
  useEffect(() => { if (ref.current) ref.current.indeterminate = !!indeterminate }, [indeterminate])
  return <input type="checkbox" ref={ref} className="rounded cursor-pointer accent-blue-600" {...props} />
}

function BulkBar({ selCount, total, selAllDB, onSelectAllDB, onClearSel, children }) {
  if (selCount === 0 && !selAllDB) return null
  const displayCount = selAllDB ? total : selCount
  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 bg-gray-900 text-white rounded-2xl shadow-2xl px-5 py-3 text-sm whitespace-nowrap">
      <span className="font-medium">
        已选 <span className="text-blue-400 font-bold">{displayCount}</span> 条
        {selAllDB && <span className="ml-1 text-xs text-green-400 font-semibold">（全部）</span>}
      </span>
      {!selAllDB && selCount > 0 && total > selCount && (
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

export function Proxies() {
  const [proxies, setProxies] = useState([])
  const [input,   setInput]   = useState('')
  const [adding,  setAdding]  = useState(false)
  const [addErr,  setAddErr]  = useState('')
  const [loading, setLoading] = useState(false)
  const [sel,     setSel]     = useState(new Set())
  const [selAll,  setSelAll]  = useState(false)
  const [deleting, setDeleting] = useState(false)

  const load = () => {
    setLoading(true)
    api.getProxies().then(p => { setProxies(p); setSel(new Set()); setSelAll(false) }).catch(() => {}).finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  const addProxy = async () => {
    const addr = input.trim()
    if (!addr) return
    setAdding(true); setAddErr('')
    try { await api.addProxy(addr); setInput(''); load() }
    catch (e) { setAddErr(e.message) }
    finally { setAdding(false) }
  }

  const deleteProxy = async (addr) => {
    await api.deleteProxy(addr).catch(() => {})
    load()
  }

  const active   = proxies.filter(p => p.is_active).length
  const inactive = proxies.length - active
  const allKeys  = proxies.map(p => p.address)
  const allSel   = allKeys.length > 0 && allKeys.every(k => sel.has(k))
  const someSel  = !allSel && allKeys.some(k => sel.has(k))

  const toggleRow  = (addr) => { setSelAll(false); setSel(s => { const n = new Set(s); n.has(addr) ? n.delete(addr) : n.add(addr); return n }) }
  const toggleAll  = () => { setSelAll(false); setSel(s => { const n = new Set(s); if (allSel) allKeys.forEach(k => n.delete(k)); else allKeys.forEach(k => n.add(k)); return n }) }
  const clearSel   = () => { setSel(new Set()); setSelAll(false) }

  const handleBatchDelete = async () => {
    const n = selAll ? proxies.length : sel.size
    if (!window.confirm(`确认删除 ${n} 个代理？此操作不可撤销。`)) return
    setDeleting(true)
    try {
      await api.batchDeleteProxies(selAll ? { select_all: true } : { addresses: [...sel] })
      clearSel(); load()
    } catch (e) { alert('删除失败：' + e.message) }
    finally { setDeleting(false) }
  }

  return (
    <div className="p-6 space-y-5 pb-24">
      <div>
        <h2 className="text-xl font-bold text-gray-800">代理池</h2>
        <p className="text-sm text-gray-500 mt-0.5">
          共 {proxies.length} 个代理 · 活跃 {active} · 禁用 {inactive}
        </p>
      </div>

      {/* Add proxy */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
        <h3 className="font-semibold text-gray-700 mb-3">添加代理</h3>
        <div className="flex gap-2">
          <input value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => e.key === 'Enter' && addProxy()}
            placeholder="http://user:pass@host:port"
            className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
          <button onClick={addProxy} disabled={adding || !input.trim()}
            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors">
            {adding ? <Spinner /> : null}{adding ? '添加中…' : '添加'}
          </button>
        </div>
        {addErr && <p className="text-xs text-red-500 mt-2">{addErr}</p>}
        <p className="text-xs text-gray-400 mt-2">
          支持格式：<code className="bg-gray-100 px-1 rounded">http://host:port</code>、
          <code className="bg-gray-100 px-1 rounded">http://user:pass@host:port</code>、
          <code className="bg-gray-100 px-1 rounded">socks5://host:port</code>
        </p>
      </div>

      {/* 全选提示 */}
      {allSel && !selAll && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg px-4 py-2.5 flex items-center gap-3 text-sm">
          <span className="text-blue-700">当前全部 {proxies.length} 条已全选。</span>
          <button onClick={() => setSelAll(true)} className="text-blue-600 hover:text-blue-800 font-semibold underline text-xs">
            确认选择全部 {proxies.length} 条
          </button>
        </div>
      )}

      {/* Proxy table */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-x-auto">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <h3 className="font-semibold text-gray-700">代理列表</h3>
          <button onClick={load} className="text-xs text-blue-500 hover:underline">刷新</button>
        </div>
        {loading && proxies.length === 0 ? (
          <div className="text-center py-12 text-gray-400 flex justify-center"><Spinner /></div>
        ) : proxies.length === 0 ? (
          <p className="text-center py-12 text-gray-400 text-sm">暂无代理，请先添加</p>
        ) : (
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="px-4 py-3 w-10">
                  <IndeterminateCheckbox
                    checked={allSel || selAll}
                    indeterminate={someSel && !selAll}
                    onChange={toggleAll}
                  />
                </th>
                {['地址', '失败次数', '最后使用', '状态', '操作'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {proxies.map(p => {
                const checked = selAll || sel.has(p.address)
                return (
                  <tr key={p.address} className={`transition-colors ${checked ? 'bg-blue-50' : !p.is_active ? 'opacity-50 hover:bg-gray-50' : 'hover:bg-gray-50'}`}>
                    <td className="px-4 py-3 w-10">
                      <input type="checkbox" checked={checked} onChange={() => toggleRow(p.address)} className="rounded cursor-pointer accent-blue-600" />
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-700">{p.address}</td>
                    <td className="px-4 py-3 text-xs">
                      <span className={p.fail_count >= 3 ? 'text-red-500 font-medium' : 'text-gray-500'}>{p.fail_count}</span>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-400 whitespace-nowrap">{fmt(p.last_used)}</td>
                    <td className="px-4 py-3">
                      {p.is_active ? <Badge color="green">活跃</Badge> : <Badge color="red">禁用</Badge>}
                    </td>
                    <td className="px-4 py-3">
                      <button onClick={() => deleteProxy(p.address)} className="text-xs text-red-400 hover:text-red-600 transition-colors">删除</button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      <BulkBar selCount={sel.size} total={proxies.length} selAllDB={selAll} onSelectAllDB={() => setSelAll(true)} onClearSel={clearSel}>
        <button onClick={handleBatchDelete} disabled={deleting}
          className="flex items-center gap-1.5 bg-red-500 hover:bg-red-600 disabled:opacity-60 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors">
          {deleting ? '删除中…' : '🗑️ 删除所选'}
        </button>
      </BulkBar>
    </div>
  )
}
