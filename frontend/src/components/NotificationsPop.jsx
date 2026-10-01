import { useEffect, useState } from 'react'
import { api } from '../api.js'

// 通知下拉（侧栏铃铛）：紧急截止 + 近期完成数。数据来自真实台账与守望。
export default function NotificationsPop({ onOpenDeadlines, onClose }) {
  const [data, setData] = useState(null)
  useEffect(() => {
    api.notifications().then(setData).catch(() => {})
  }, [])

  return (
    <div className="popover" style={{ top: 8, left: 8, right: 8 }} onClick={(e) => e.stopPropagation()}>
      <div className="menu-user"><div className="name">通知</div></div>
      <div className="menu-sep" />
      {!data && <div style={{ padding: 10, fontSize: 13, color: 'var(--text-dim)' }}>加载中…</div>}
      {data && data.urgent_deadlines.length === 0 && (
        <div style={{ padding: 10, fontSize: 13, color: 'var(--text-dim)' }}>
          没有紧急截止。近 24h 完成 {data.completed_recently} 个任务。
        </div>
      )}
      {data && data.urgent_deadlines.map((d) => (
        <div key={d.name} className="menu-item" style={{ cursor: 'default' }}>
          <span className="icon">⏱</span>
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
