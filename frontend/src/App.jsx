import { useEffect, useState } from 'react'
import { api, COMMANDS } from './api.js'
import IconRail from './components/IconRail.jsx'
import Sidebar from './components/Sidebar.jsx'
import TabBar, { useTabs } from './components/TabBar.jsx'
import SearchOverlay from './components/SearchOverlay.jsx'
import NotificationsPop from './components/NotificationsPop.jsx'
import ToolPanel from './components/ToolPanel.jsx'
import SettingsPage from './views/SettingsPage.jsx'
import CustomizePage from './views/CustomizePage.jsx'
import HomeView from './views/HomeView.jsx'
import ChatView from './views/ChatView.jsx'
import { UserBox } from './components/UserMenu.jsx'
import UsageCard from './components/UsageCard.jsx'

// 应用外壳（M5 Codex 化）：图标栏 → 侧栏（项目树/最近/用户）→ 标签页 + 主区。
// 视图 = 标签页里的聊天 / 首页 / 统计 / 截止日程 / 设置全页 / Customize。
// 全局状态：模式与主题（localStorage 持久化）、配置、会话列表、多标签。
const THEME_KEY = 'ca-theme'
const FS_KEY = 'ca-fontsize'

export default function App() {
  const [rail, setRail] = useState('home')            // 图标栏定位：home/stats/deadlines
  const [tabs, setTabs] = useState([{ key: 'home', title: '首页' }])
  const [activeTab, setActiveTab] = useState('home')
  const [config, setConfig] = useState(null)
  const [sessions, setSessions] = useState([])
  const [projects, setProjects] = useState([])
  const [project, setProject] = useState(null)        // composer 选中的项目
  const [branch, setBranch] = useState('main')
  const [accessFull, setAccessFull] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [customizeOpen, setCustomizeOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [notifOpen, setNotifOpen] = useState(false)
  const [toolPanel, setToolPanel] = useState(false)
  const [theme, setTheme] = useState(() => localStorage.getItem(THEME_KEY) || 'light')
  const [fontSize, setFontSize] = useState(() => localStorage.getItem(FS_KEY) || 'medium')

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem(THEME_KEY, theme)
  }, [theme])
  useEffect(() => {
    document.documentElement.dataset.fs = fontSize
    localStorage.setItem(FS_KEY, fontSize)
  }, [fontSize])

  const refreshConfig = () => api.config().then((c) => {
    setConfig(c); setAccessFull(!!c.access_full)
  }).catch(() => {})
  const refreshSessions = () => api.sessions(30).then((r) => setSessions(r.sessions)).catch(() => {})

  useEffect(() => {
    refreshConfig(); refreshSessions()
    api.projects().then((r) => setProjects(r.projects)).catch(() => {})
    api.gitBranch().then((r) => setBranch(r.branch)).catch(() => {})
  }, [])

  // Customize 全页没有自己的 Esc 监听（SettingsPage 有），在壳层统一补：
  // 按 Esc 关 Customize，避免只能精准点到左上角小叉。
  // 打开 Customize 时 rail 被置为 'none'（主区让位），关闭后要回工作台，否则主区空白。
  const closeCustomize = () => {
    setCustomizeOpen(false)
    setRail((r) => (r === 'none' ? 'home' : r))
  }
  useEffect(() => {
    if (!customizeOpen) return
    const onKey = (e) => { if (e.key === 'Escape') closeCustomize() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [customizeOpen])

  const toggleAccess = async () => {
    try {
      await api.setAccess(!accessFull)
      await refreshConfig()
    } catch { /* 静默：状态条会在下次刷新时对齐 */ }
  }

  // 从首页发消息 = 开一个聊天标签（首条消息由 ChatView 自动发送）
  const openChat = (text, assistantText, bindProject) => {
    const tab = {
      key: `chat-${Date.now()}`, title: text ? text.slice(0, 12) : '新聊天',
      sessionId: null, initialUser: text || null,
      initialAssistant: assistantText || null,
      bindProjectKey: bindProject?.key || null,
    }
    setTabs((ts) => [...ts, tab])
    setActiveTab(tab.key)
    setRail('home')
  }

  const openSessionReplay = async (session) => {
    // 侧栏两种入口：数字 id（最近列表）= 回放；项目 key = 只读占位
    if (typeof session.id !== 'number') return
    setRail('home')
    setTabs((ts) => {
      const exist = ts.find((t) => t.sessionId === session.id)
      if (exist) { setActiveTab(exist.key); return ts }
      const tab = { key: `replay-${session.id}-${Date.now()}`, title: session.note || `会话 #${session.id}`,
                    sessionId: session.id }
      setActiveTab(tab.key)
      return [...ts, tab]
    })
  }

  const runCommandFromHome = async (cmdName) => {
    const cmd = COMMANDS.find((c) => c.cmd === `/${cmdName}`) ||
                COMMANDS.find((c) => c.cmd.includes(cmdName))
    if (!cmd) return
    try {
      const result = await cmd.run()
      openChat(cmd.cmd, result)
    } catch (e) {
      openChat(cmd.cmd, `注意：${e.message}`)
    }
  }

  // 主区：激活 tab 是聊天/回放 → ChatView；否则按 rail 显示面板。
  // 回放 tab 的 key 以 replay- 开头（TabBar 只展示 chat- 标签，回放不占标签位）。
  const activeTabObj = tabs.find((t) => t.key === activeTab) || tabs[0]
  const showChat = rail === 'home' &&
    (activeTabObj?.key?.startsWith('chat') || activeTabObj?.key?.startsWith('replay'))

  const modelLabel = config?.models?.find((m) => m.name === config?.active_model)?.model || '…'

  return (
    <div className="app codex-app" onClick={() => setNotifOpen(false)}>
      <IconRail active={rail} onNavigate={setRail} onOpenSettings={() => setSettingsOpen(true)} />

      <Sidebar
        sessions={sessions}
        activeSessionId={showChat ? activeTabObj?.sessionId : null}
        onOpenSession={openSessionReplay}
        onNewChat={() => { setRail('home')
          const tab = { key: `chat-${Date.now()}`, title: '新聊天', sessionId: null }
          setTabs((ts) => [...ts, tab]); setActiveTab(tab.key) }}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenSearch={() => setSearchOpen(true)}
        onOpenNotifications={() => setNotifOpen(true)}
        onOpenPlugins={() => { setCustomizeOpen(true); setRail('none') }}
      />

      <main className="main">
        {/* 标签页条：聊天标签 + 右侧工具面板开关 */}
        <div className="main-topbar">
          <TabBar
            tabs={tabs.filter((t) => t.key.startsWith('chat'))}
            activeKey={showChat ? activeTab : ''}
            onSelect={(key) => { setRail('home'); setActiveTab(key) }}
            onClose={(key) => setTabs((ts) => {
              const rest = ts.filter((t) => t.key !== key)
              if (key === activeTab && rest.length) setActiveTab(rest[rest.length - 1].key)
              if (!rest.length) {
                const fresh = { key: `chat-${Date.now()}`, title: '新聊天', sessionId: null }
                setTabs([fresh]); setActiveTab(fresh.key)
              }
              return rest
            })}
            onNew={() => openChat(null)}
          />
          <div className="spacer" />
          <button className="icon-btn" title="工具面板（output 文件）"
                  onClick={() => setToolPanel(!toolPanel)}>▤</button>
        </div>

        {/* 各视图根都挂 view-enter：条件渲染换视图时 200ms 淡入，消除跳变感 */}
        {rail === 'home' && showChat && (
          <ChatView key={activeTab}
                    className="view-enter"
                    sessionId={activeTabObj.sessionId}
                    title={activeTabObj.title}
                    initialUser={activeTabObj.initialUser}
                    initialAssistant={activeTabObj.initialAssistant}
                    bindProjectKey={activeTabObj.bindProjectKey}
                    projectName={project?.name}
                    onSessionsChanged={refreshSessions}
                    onCloseTab={() => setTabs((ts) => ts.filter((t) => t.key !== activeTab))} />
        )}

        {rail === 'home' && !showChat && (
          <HomeView className="view-enter"
                    userName="momo"
                    project={project}
                    onProjectChange={setProject}
                    branch={branch}
                    accessFull={accessFull}
                    onToggleAccess={toggleAccess}
                    modelLabel={modelLabel}
                    onSend={(text, proj) => openChat(text, null, proj)}
                    onCommand={(name) => runCommandFromHome(name)}
                    onCommandResult={(userText, result) => openChat(userText, result)} />
        )}

        {rail === 'stats' && (
          <div className="view-enter" style={{ flex: 1, overflowY: 'auto', padding: '24px 32px' }}>
            <h1 style={{ fontSize: 22, margin: '0 0 16px' }}>统计</h1>
            <UsageCard />
          </div>
        )}

        {rail === 'deadlines' && <DeadlinesView />}

        {customizeOpen && (
          <div className="fullpage-mask">
            <CustomizePage onOpenSettings={() => setSettingsOpen(true)} />
            <button className="icon-btn fullpage-close" onClick={closeCustomize}>✕</button>
          </div>
        )}

        {settingsOpen && (
          <div className="fullpage-mask">
            <SettingsPage
              config={config}
              onConfigChange={refreshConfig}
              theme={theme} setTheme={setTheme}
              fontSize={fontSize} setFontSize={setFontSize}
              accessFull={accessFull} onToggleAccess={toggleAccess}
              onClose={() => setSettingsOpen(false)}
              onOpenPlugins={() => { setSettingsOpen(false); setCustomizeOpen(true) }}
            />
            <button className="icon-btn fullpage-close" onClick={() => setSettingsOpen(false)}>✕</button>
          </div>
        )}

        {/* 底部状态条 */}
        <div className="statusbar">
          <button className="pill-btn" onClick={() => setSettingsOpen(true)}>
            自动入库 <span>＋</span>
          </button>
          <div className="spacer" />
          {config?.budget_per_task_yuan != null && (
            <span>预算 {config.budget_per_task_yuan} 元/任务</span>
          )}
          <button className="model-pill" onClick={() => setSettingsOpen(true)}>
            <span>{modelLabel}</span>
            <span className={`dot ${config?.models?.find((m) => m.name === config?.active_model)?.has_key ? 'ok' : ''}`} />
          </button>
        </div>
      </main>

      {toolPanel && <ToolPanel onClose={() => setToolPanel(false)} />}

      {notifOpen && (
        <NotificationsPop
          onClose={() => setNotifOpen(false)}
          onOpenDeadlines={() => setRail('deadlines')} />
      )}

      {searchOpen && (
        <SearchOverlay onClose={() => setSearchOpen(false)} onOpenSession={openSessionReplay} />
      )}

      {settingsOpen ? null : null}
    </div>
  )
}

// 截止日程视图（图标栏）：只读列表。
function DeadlinesView() {
  const [data, setData] = useState(null)
  useEffect(() => {
    api.deadlines().then(setData).catch((e) => setData({ deadlines: [], error: e.message }))
  }, [])
  return (
    <div className="view-enter" style={{ flex: 1, overflowY: 'auto', padding: '24px 32px' }}>
      <h1 style={{ fontSize: 22, margin: '0 0 16px' }}>截止日程</h1>
      {data?.error && <div className="models-empty">注意：{data.error}</div>}
      {data && !data.error && data.count === 0 && (
        <div className="models-empty">未来 30 天没有临近截止的比赛。</div>
      )}
      {data?.deadlines?.map((d) => (
        <a key={d.url} className="idea-row" href={d.url} target="_blank" rel="noreferrer">
          <span className={`idea-icon ddl-dot l${d.remaining <= 1 ? 3 : d.remaining <= 3 ? 2 : 1}`} />
          <span style={{ flex: 1 }}>
            {d.name} <span style={{ color: 'var(--text-dim)', fontSize: 13 }}>{d.label}</span>
          </span>
          <span style={{ color: 'var(--text-faint)', fontSize: 12.5 }}>{d.deadline}</span>
        </a>
      ))}
    </div>
  )
}
