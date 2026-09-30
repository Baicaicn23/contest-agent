import { UserBox } from './UserMenu.jsx'

// 左侧栏：顶部模式切换（情报站/工作台）→ 菜单 → 会话列表 → 底部用户区。
// 两个模式共用这根侧栏，菜单项按模式切换（对应截图 1 与截图 3 的差异）。
const TASK_LABELS = {
  chat: '对话',
  identify: '识别',
  watch: '盯梢',
  generate: '生成材料',
  study_path: '备考路径',
  eval: '评测',
}

export default function Sidebar({ mode, onModeChange, sessions, activeSessionId,
                                  onOpenSession, onNewChat, onOpenSettings }) {
  return (
    <aside className="sidebar">
      <div className="mode-switch">
        <button className={mode === 'cowork' ? 'active' : ''}
                onClick={() => onModeChange('cowork')}>
          <span>◈</span> 情报站
        </button>
        <button className={mode === 'code' ? 'active' : ''}
                onClick={() => onModeChange('code')}>
          <span>⌘</span> 工作台
        </button>
      </div>

      <button className="side-item" onClick={onNewChat}>
        <span className="icon">＋</span> 新会话
      </button>

      {mode === 'cowork' ? (
        <>
          <button className="side-item"><span className="icon">▤</span> 项目</button>
          <button className="side-item"><span className="icon">▣</span> 工件</button>
          <button className="side-item"><span className="icon">◔</span> 定时任务</button>
          <button className="side-item" onClick={onOpenSettings}>
            <span className="icon">✎</span> 自定义
          </button>
        </>
      ) : (
        <button className="side-item" onClick={onOpenSettings}>
          <span className="icon">✎</span> 自定义
        </button>
      )}

      {mode === 'cowork' && <div className="side-section">任务</div>}
      {mode === 'code' && (
        <div className="side-section">
          <span>近期会话</span>
        </div>
      )}
      {mode === 'code' && sessions.map((s) => (
        <button key={s.id}
                className={`session-item ${activeSessionId === s.id ? 'active' : ''}`}
                onClick={() => onOpenSession(s)}>
          <span className={`dot ${s.status === 'completed' ? 'done' : ''}`} />
          <span className="title">
            {TASK_LABELS[s.task_type] || s.task_type} · {s.note || `#${s.id}`}
          </span>
        </button>
      ))}

      <div className="spacer" />
      <UserBox onOpenSettings={onOpenSettings} />
    </aside>
  )
}
