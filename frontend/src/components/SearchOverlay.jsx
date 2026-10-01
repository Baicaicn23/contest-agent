import { useEffect, useState } from 'react'
import { api } from '../api.js'

// 全局搜索 overlay（侧栏 🔍）：跨 会话/卡片/通知 的实时搜索。
// 点会话 → 打开会话回放；点卡片/通知 → 打开原文链接。
export default function SearchOverlay({ onClose, onOpenSession }) {
  const [q, setQ] = useState('')
  const [result, setResult] = useState(null)

  useEffect(() => {
    if (!q.trim()) { setResult(null); return }
    const timer = setTimeout(() => {
      api.search(q).then(setResult).catch(() => setResult(null))
    }, 250)
    return () => clearTimeout(timer)
  }, [q])

  const has = result && (result.sessions.length || result.cards.length || result.notices.length)

  return (
    <div className="modal-mask" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="search-overlay">
        <input autoFocus placeholder="搜索会话、比赛、通知…" value={q}
               onChange={(e) => setQ(e.target.value)}
               onKeyDown={(e) => e.key === 'Escape' && onClose()} />
        {has && (
          <div className="search-results">
            {result.sessions.map((s) => (
              <button key={`s${s.id}`} className="cmd-item"
                      onClick={() => { onOpenSession(s.id); onClose() }}>
                <span className="cmd">会话</span> {s.title}
              </button>
            ))}
            {result.cards.map((c) => (
              <a key={c.url} className="cmd-item" href={c.url} target="_blank" rel="noreferrer">
                <span className="cmd">卡片</span> {c.name}
              </a>
            ))}
            {result.notices.map((n) => (
              <a key={n.url} className="cmd-item" href={n.url} target="_blank" rel="noreferrer">
                <span className="cmd">通知</span> {n.title}
              </a>
            ))}
          </div>
        )}
        {q && result && !has && (
          <div style={{ padding: 14, color: 'var(--text-dim)', fontSize: 13 }}>没有匹配结果。</div>
        )}
        {!q && (
          <div style={{ padding: 14, color: 'var(--text-faint)', fontSize: 13 }}>
            输入关键词，跨 会话 / 比赛卡片 / 官网通知 进行搜索。
          </div>
        )}
      </div>
    </div>
  )
}
