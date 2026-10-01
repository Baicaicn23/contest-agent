import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { UserBox } from './UserMenu.jsx'

// Codex 式侧栏：头部（产品名/通知铃/搜索）→ 新聊天 → 项目树 → skills配置 → 最近。
// 项目树 = 比赛卡自动派生的项目（M5），子行显示归属的会话数。
export default function Sidebar({ sessions, activeSessionId, onOpenSession,
                                  onNewChat, onOpenSettings, onOpenSearch,
                                  onOpenPlugins }) {
  const [projects, setProjects] = useState([])
  const [notifCount, setNotifCount] = useState(0)

  useEffect(() => {
    api.projects().then((r) => setProjects(r.projects)).catch(() => {})
    api.notifications().then((n) => {
      setNotifCount(n.urgent_deadlines?.length || 0)
    }).catch(() => {})
  }, [])

  return (
    <aside className="sidebar codex">
      <div className="side-head">
        <span className="side-product">Contest Agent <span className="chev">⌄</span></span>
        <span className="side-head-icons">
          <button className="icon-btn" title={notifCount ? `${notifCount} 条紧急截止` : '通知'}
                  onClick={onOpenSearch} style={{ position: 'relative' }}>
            通知
            {notifCount > 0 && <span className="badge">{notifCount}</span>}
          </button>
          <button className="icon-btn" title="搜索" onClick={onOpenSearch}>搜索</button>
        </span>
      </div>

      <button className="side-item" onClick={onNewChat}>
        <span className="icon">＋</span> 新聊天
      </button>

      <div className="side-section">项目</div>
      {projects.map((p) => (
        <button key={p.key} className="side-item project"
                title={`${p.name}（${p.sessions} 个会话）`}
                onClick={() => onOpenSession({ id: p.key, name: p.name })}>
          <span className="proj-mark" />
          <span className="title">{p.name}</span>
          {p.deadline && <span className="proj-ddl">{p.deadline.slice(5)}</span>}
        </button>
      ))}

      <button className="side-item" onClick={onOpenPlugins}>
        <span className="icon">技</span> skills配置
      </button>

      <div className="side-section">最近</div>
      {sessions.map((s) => (
        <button key={s.id}
                className={`session-item ${activeSessionId === s.id ? 'active' : ''}`}
                onClick={() => onOpenSession(s)}>
          <span className="title">{s.note || `${s.task_type} #${s.id}`}</span>
        </button>
      ))}

      <div className="spacer" />
      <UserBox onOpenSettings={onOpenSettings} />
    </aside>
  )
}
