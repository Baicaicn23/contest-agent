import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { UserBox } from './UserMenu.jsx'
import AutomationPop from './AutomationPop.jsx'
import {
  PlusCircleIcon, SearchIcon, ClockIcon, GridIcon, FolderIcon,
  ChevronDownIcon, FilterIcon, TrashIcon, PlusIcon, SpinnerIcon,
  CheckIcon, XSmallIcon, PanelIcon,
} from './Icon.jsx'

// 侧栏（M8 完全复刻竞品）：四操作入口（SVG 线性图标）→ 视图行（项目胶囊 +
// 筛选/垃圾桶）→「项目」标题行（整列折叠 + 新建）→ 项目树（两级、可折叠收纳、
// 运行中任务转圈）→ 未归类组 → 用户盒。
// 折叠/展开状态全部 localStorage 记忆；删除仅限手动项目（后端把关）。
const EXPANDED_KEY = 'ca-proj-expanded'
const LIST_OPEN_KEY = 'ca-proj-list-open'

function loadSet(key) {
  try { return new Set(JSON.parse(localStorage.getItem(key) || '[]')) } catch { return new Set() }
}

export default function Sidebar({ sessions, activeSessionId, onOpenSession,
                                  onNewChat, onOpenSettings, onOpenSearch,
                                  onOpenNotifications, onOpenPlugins,
                                  onToggleCollapse, runningIds, onCreateChat }) {
  const [projects, setProjects] = useState([])
  const [notifCount, setNotifCount] = useState(0)
  const [expanded, setExpanded] = useState(() => loadSet(EXPANDED_KEY))
  const [listOpen, setListOpen] = useState(() => localStorage.getItem(LIST_OPEN_KEY) !== '0')
  const [filterOpen, setFilterOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [deleteMode, setDeleteMode] = useState(false)
  const [confirmKey, setConfirmKey] = useState(null)   // 正在确认删除的项目键
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [automationOpen, setAutomationOpen] = useState(false)

  const refreshProjects = () => api.projects().then((r) => setProjects(r.projects)).catch(() => {})
  useEffect(() => {
    refreshProjects()
    api.notifications().then((n) => {
      setNotifCount(n.urgent_deadlines?.length || 0)
    }).catch(() => {})
  }, [])

  const persistExpanded = (next) => {
    setExpanded(next)
    localStorage.setItem(EXPANDED_KEY, JSON.stringify([...next]))
  }
  const toggleProject = (key) => {
    const next = new Set(expanded)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    persistExpanded(next)
  }
  const toggleList = () => {
    const next = !listOpen
    setListOpen(next)
    localStorage.setItem(LIST_OPEN_KEY, next ? '1' : '0')
  }

  const createProject = async () => {
    const name = newName.trim()
    if (!name) { setCreating(false); return }
    try {
      await api.createProject(name)
      await refreshProjects()
    } catch { /* 建失败保持输入行，用户可重试 */ }
    setNewName(''); setCreating(false)
  }

  const removeProject = async (key) => {
    try {
      await api.deleteProject(key)
      await refreshProjects()
    } catch (e) {
      alert(`删除失败：${e.message}`)   // 删除是破坏性操作，失败要看得见
    }
    setConfirmKey(null)
    setDeleteMode(false)
  }

  const q = query.trim().toLowerCase()
  const matchProject = (p, kids) =>
    !q || p.name.toLowerCase().includes(q) || kids.some((s) => (s.note || '').toLowerCase().includes(q))

  const owned = sessions.filter((s) => s.project_key)
  const loose = sessions.filter((s) => !s.project_key)
  const isRunning = (s) => runningIds?.has(s.id) || s.status === 'running'

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
          <button className="icon-btn" title="收起侧栏" onClick={onToggleCollapse}>
            <PanelIcon size={14} />
          </button>
        </span>
      </div>

      {/* 四操作入口（图二同款线性图标 + 快捷键） */}
      <button className="side-item" onClick={onNewChat}>
        <span className="side-ico"><PlusCircleIcon /></span> 新建任务
        <span className="side-shortcut">⌘N</span>
      </button>
      <button className="side-item" onClick={onOpenSearch}>
        <span className="side-ico"><SearchIcon /></span> 搜索
        <span className="side-shortcut">⌘K</span>
      </button>
      <div style={{ position: 'relative' }}>
        <button className="side-item" onClick={() => setAutomationOpen(!automationOpen)}>
          <span className="side-ico"><ClockIcon /></span> 自动化
        </button>
        {automationOpen && <AutomationPop sessions={sessions} onClose={() => setAutomationOpen(false)} />}
      </div>
      <button className="side-item" onClick={onOpenPlugins}>
        <span className="side-ico"><GridIcon /></span> 插件市场
      </button>

      {/* 视图行：项目胶囊（唯一视图）+ 筛选/垃圾桶 */}
      <div className="view-row">
        <span className="view-pill"><FolderIcon /> 项目</span>
        <span className="spacer" />
        <button className={`icon-btn ${filterOpen ? 'armed' : ''}`} title="筛选"
                onClick={() => { setFilterOpen(!filterOpen); setQuery('') }}>
          <FilterIcon />
        </button>
        <button className={`icon-btn ${deleteMode ? 'armed' : ''}`} title="删除项目（仅限手动创建）"
                onClick={() => { setDeleteMode(!deleteMode); setConfirmKey(null) }}>
          <TrashIcon />
        </button>
      </div>
      {filterOpen && (
        <input className="side-filter" autoFocus placeholder="按项目或会话名过滤…"
               value={query} onChange={(e) => setQuery(e.target.value)} />
      )}

      {/* 项目标题行：整列折叠收纳 + 新建 */}
      <div className="proj-head">
        <button className={`proj-head-toggle ${listOpen ? '' : 'closed'}`} onClick={toggleList}>
          项目 <ChevronDownIcon size={12} />
        </button>
        <span className="spacer" />
        <button className="icon-btn" title="新建项目" onClick={() => { setCreating(!creating); setNewName('') }}>
          <PlusIcon />
        </button>
      </div>

      <div className={`tree-kids ${listOpen ? 'open' : ''}`}>
        <div className="tree-kids-inner">
          {creating && (
            <div className="proj-create-row">
              <input autoFocus value={newName} placeholder="项目名称，回车创建"
                     onChange={(e) => setNewName(e.target.value)}
                     onKeyDown={(e) => {
                       if (e.key === 'Enter') createProject()
                       if (e.key === 'Escape') setCreating(false)
                     }} />
              <button className="icon-btn" title="创建" onClick={createProject}><CheckIcon /></button>
              <button className="icon-btn" title="取消" onClick={() => setCreating(false)}><XSmallIcon /></button>
            </div>
          )}

          {projects.filter((p) => matchProject(p, owned.filter((s) => s.project_key === p.key)))
                   .map((p) => {
            const kids = owned.filter((s) => s.project_key === p.key)
            return (
              <ProjectNode key={p.key} project={p} sessions={kids}
                           open={expanded.has(p.key)} activeSessionId={activeSessionId}
                           runningIds={runningIds}
                           onToggle={() => toggleProject(p.key)}
                           onOpenSession={onOpenSession}
                           onCreateChat={onCreateChat}
                           deleteMode={deleteMode}
                           confirmKey={confirmKey}
                           onAskDelete={() => setConfirmKey(p.key)}
                           onCancelDelete={() => setConfirmKey(null)}
                           onConfirmDelete={() => removeProject(p.key)} />
            )
          })}
          {!projects.length && !creating && <div className="tree-empty">还没有项目。识别比赛或手动新建。</div>}

          {/* 未归类组：无主会话的收纳处（低视觉权重，可折叠） */}
          {loose.length > 0 && (!q || loose.some((s) => (s.note || '').toLowerCase().includes(q))) && (
            <ProjectNode project={{ key: '__loose__', name: '未归类', source: 'loose', deadline: null }}
                         sessions={loose} open={expanded.has('__loose__')}
                         activeSessionId={activeSessionId} runningIds={runningIds}
                         onToggle={() => toggleProject('__loose__')}
                         onOpenSession={onOpenSession}
                         deleteMode={false} confirmKey={null} />
          )}
        </div>
      </div>

      <div className="spacer" />
      <UserBox onOpenSettings={onOpenSettings} />
    </aside>
  )
}

// 项目节点：项目行（点击折叠/展开，状态在 localStorage）+ 会话子行。
// 行尾 ＋ = 在该项目下新建对话（首条消息自动归属，hover 显示）；
// deleteMode 时手动项目行尾替换为删除钮 → 确认态（红字两钮，防误删）。
function ProjectNode({ project, sessions, open, activeSessionId, runningIds,
                       onToggle, onOpenSession, onCreateChat,
                       deleteMode, confirmKey, onAskDelete, onCancelDelete, onConfirmDelete }) {
  const isRunning = (s) => runningIds?.has(s.id) || s.status === 'running'
  return (
    <>
      {confirmKey === project.key ? (
        <div className="proj-confirm">
          <span>删除「{project.name}」？会话将回到未归类</span>
          <span className="proj-confirm-actions">
            <button className="icon-btn danger" title="确认删除" onClick={onConfirmDelete}><CheckIcon /></button>
            <button className="icon-btn" title="取消" onClick={onCancelDelete}><XSmallIcon /></button>
          </span>
        </div>
      ) : (
        <button className={`side-item project ${open ? 'expanded' : ''}`}
                title={`${project.name}（${sessions.length} 个会话）`}
                onClick={onToggle}>
          <span className="side-ico"><FolderIcon open={open} /></span>
          <span className="title">{project.name}</span>
          {project.deadline && <span className="proj-ddl">{String(project.deadline).slice(5, 10)}</span>}
          {!deleteMode && project.source !== 'loose' && (
            <span className="proj-add" title={`在「${project.name}」中新建对话`}
                  onClick={(e) => { e.stopPropagation(); onCreateChat?.(project) }}>
              <PlusIcon size={13} />
            </span>
          )}
          {deleteMode && project.source === 'manual' && (
            <span className="proj-del" title="删除该项目"
                  onClick={(e) => { e.stopPropagation(); onAskDelete() }}>
              <TrashIcon />
            </span>
          )}
        </button>
      )}
      <div className={`tree-kids ${open ? 'open' : ''}`}>
        <div className="tree-kids-inner">
          {sessions.map((s) => (
            <button key={s.id}
                    className={`session-item sub ${activeSessionId === s.id ? 'active' : ''}`}
                    onClick={() => onOpenSession(s)}>
              {isRunning(s)
                ? <span className="sub-run"><SpinnerIcon /> 刚刚</span>
                : <span className={`sub-badge t-${s.task_type}`}>{TASK_LABELS[s.task_type] || s.task_type}</span>}
              <span className="title">{s.note || `#${s.id}`}</span>
              {!isRunning(s) && <span className="sub-time">{relTime(s.started_at)}</span>}
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

// ISO 时间 → 人话相对时间（"13分 / 3小时 / 2天"）
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
