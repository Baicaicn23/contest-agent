import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { UserBox } from './UserMenu.jsx'
import AutomationPop from './AutomationPop.jsx'

// Codex/Globex 式侧栏（M7 图二化改造）：
//   头部（产品名/通知铃）→ 四个操作入口（新建任务/搜索/自动化/插件市场）
//   → 项目树（项目 → 归属会话，两级可展开）→ 最近（未归属会话）→ 用户盒。
// 数据全部真实：项目来自比赛卡+手动，子行会话按 project_key 分组，
// 相对时间来自 started_at；展开/收起用 grid 轨道过渡（见 app.css .tree-kids）。
export default function Sidebar({ sessions, activeSessionId, onOpenSession,
                                  onNewChat, onOpenSettings, onOpenSearch,
                                  onOpenNotifications, onOpenPlugins }) {
  const [projects, setProjects] = useState([])
  const [notifCount, setNotifCount] = useState(0)
  const [expanded, setExpanded] = useState(() => new Set())
  const [automationOpen, setAutomationOpen] = useState(false)
  const automationRef = useRef(null)

  useEffect(() => {
    api.projects().then((r) => setProjects(r.projects)).catch(() => {})
    api.notifications().then((n) => {
      setNotifCount(n.urgent_deadlines?.length || 0)
    }).catch(() => {})
  }, [])

  // 自动化 popover 的"点外部收起"（同 ProjectChip 的做法）
  useEffect(() => {
    if (!automationOpen) return
    const onDoc = (e) => {
      if (automationRef.current && !automationRef.current.contains(e.target)) {
        setAutomationOpen(false)
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [automationOpen])

  const toggleProject = (key) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const owned = sessions.filter((s) => s.project_key)
  const loose = sessions.filter((s) => !s.project_key)

  return (
    <aside className="sidebar codex">
      <div className="side-head">
        <span className="side-product">Contest Agent <span className="chev">⌄</span></span>
        <span className="side-head-icons">
          <button className="icon-btn" title={notifCount ? `${notifCount} 条紧急截止` : '通知'}
                  onClick={(e) => { e.stopPropagation(); onOpenNotifications() }}
                  style={{ position: 'relative' }}>
            通知
            {notifCount > 0 && <span className="badge">{notifCount}</span>}
          </button>
        </span>
      </div>

      {/* 操作入口区（图二同构）：新建/搜索/自动化/插件市场 */}
      <button className="side-item" onClick={onNewChat}>
        <span className="icon">＋</span> 新建任务
        <span className="side-shortcut">⌘N</span>
      </button>
      <button className="side-item" onClick={onOpenSearch}>
        <span className="icon">搜</span> 搜索
        <span className="side-shortcut">⌘K</span>
      </button>
      <div style={{ position: 'relative' }} ref={automationRef}>
        <button className="side-item" onClick={() => setAutomationOpen(!automationOpen)}>
          <span className="icon">自</span> 自动化
        </button>
        {automationOpen && <AutomationPop sessions={sessions} onClose={() => setAutomationOpen(false)} />}
      </div>
      <button className="side-item" onClick={onOpenPlugins}>
        <span className="icon">插</span> 插件市场
      </button>

      <div className="side-section">项目</div>
      {projects.map((p) => (
        <ProjectNode key={p.key} project={p}
                     sessions={owned.filter((s) => s.project_key === p.key)}
                     open={expanded.has(p.key)}
                     activeSessionId={activeSessionId}
                     onToggle={() => toggleProject(p.key)}
                     onOpenSession={onOpenSession} />
      ))}
      {!projects.length && <div className="tree-empty">还没有项目。识别比赛后自动出现。</div>}

      <div className="side-section">最近</div>
      {loose.map((s) => (
        <button key={s.id}
                className={`session-item ${activeSessionId === s.id ? 'active' : ''}`}
                onClick={() => onOpenSession(s)}>
          <span className="title">{s.note || `${s.task_type} #${s.id}`}</span>
          <span className="sub-time">{relTime(s.started_at)}</span>
        </button>
      ))}

      <div className="spacer" />
      <UserBox onOpenSettings={onOpenSettings} />
    </aside>
  )
}

// 项目节点：项目行（点击展开/收起）+ 归属会话子行（grid 轨道过渡动画）。
function ProjectNode({ project, sessions, open, activeSessionId, onToggle, onOpenSession }) {
  return (
    <>
      <button className={`side-item project ${open ? 'expanded' : ''}`}
              title={`${project.name}（${sessions.length} 个会话）`}
              onClick={onToggle}>
        <span className={`tree-chev ${open ? 'down' : ''}`}>▸</span>
        <span className="proj-mark" />
        <span className="title">{project.name}</span>
        {project.deadline && <span className="proj-ddl">{String(project.deadline).slice(5, 10)}</span>}
      </button>
      <div className={`tree-kids ${open ? 'open' : ''}`}>
        <div className="tree-kids-inner">
          {sessions.map((s) => (
            <button key={s.id}
                    className={`session-item sub ${activeSessionId === s.id ? 'active' : ''}`}
                    onClick={() => onOpenSession(s)}>
              <span className={`sub-badge t-${s.task_type}`}>{TASK_LABELS[s.task_type] || s.task_type}</span>
              <span className="title">{s.note || `#${s.id}`}</span>
              <span className="sub-time">{relTime(s.started_at)}</span>
            </button>
          ))}
          {!sessions.length && <div className="tree-empty">还没有会话</div>}
        </div>
      </div>
    </>
  )
}

// 任务类型 → 中文徽章（与 ChatView 的 TASK_LABELS 同口径）
const TASK_LABELS = {
  chat: '对话', identify: '识别', watch: '盯梢',
  generate: '生成', study_path: '备考', eval: '评测',
}

// ISO 时间 → 人话相对时间（"13分 / 3小时 / 2天"，图二同款）
export function relTime(iso) {
  if (!iso) return ''
  const diff = Date.now() - new Date(iso).getTime()
  if (Number.isNaN(diff)) return ''
  const m = Math.floor(diff / 60000)
  if (m < 1) return '刚刚'
  if (m < 60) return `${m}分`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}小时`
  return `${Math.floor(h / 24)}天`
}
