import { useEffect, useState } from 'react'
import { api } from '../api.js'

// 通知下拉（侧栏"通知"按钮）：紧急截止 + 近期完成数。数据来自真实台账与守望。
// M6：修好接线（此前按钮误开搜索）、fixed 定位挂侧栏头部下方、
// 关闭钮统一左上、Esc 关闭、紧迫度用彩点表达（无 emoji 规范）。
export default function NotificationsPop({ onOpenDeadlines, onClose }) {
  const [data, setData] = useState(null)
  useEffect(() => {
    api.notifications().then(setData).catch(() => {})
  }, [])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const urgent = data?.urgent_deadlines || []

  return (
    <div className="popover notif-pop" onClick={(e) => e.stopPropagation()}>
      <button className="icon-btn close-btn-tl" title="关闭（Esc）" onClick={onClose}>✕</button>
      <div className="menu-user" style={{ paddingLeft: 40 }}>
        <div className="name">通知</div>
      </div>
      <div className="menu-sep" />
      {!data && <div style={{ padding: 10, fontSize: 13, color: 'var(--text-dim)' }}>加载中…</div>}
      {data && urgent.length === 0 && (
        <div style={{ padding: 10, fontSize: 13, color: 'var(--text-dim)' }}>
          没有紧急截止。近 24h 完成 {data.completed_recently} 个任务。
        </div>
      )}
      {urgent.map((d) => (
        <div key={d.name} className="menu-item" style={{ cursor: 'default' }}>
          <span className={`ddl-dot l${d.remaining <= 1 ? 3 : d.remaining <= 3 ? 2 : 1}`} />
          <span style={{ flex: 1 }}>{d.name}<br />
            <span style={{ color: 'var(--text-faint)', fontSize: 12 }}>{d.label}</span>
          </span>
        </div>
      ))}
      <div className="menu-sep" />
      <button className="menu-item" onClick={() => { onClose(); onOpenDeadlines() }}>
        查看全部截止日程
      </button>
    </div>
  )
}
