import { useEffect, useState } from 'react'
import { api, COMMANDS } from './api.js'
import IconRail from './components/IconRail.jsx'
import Sidebar from './components/Sidebar.jsx'
import TabBar, { useTabs } from './components/TabBar.jsx'
import SearchOverlay from './components/SearchOverlay.jsx'
import NotificationsPop from './components/NotificationsPop.jsx'
import RightDock from './components/RightDock.jsx'
import SettingsPage from './views/SettingsPage.jsx'
import CustomizePage from './views/CustomizePage.jsx'
import HomeView from './views/HomeView.jsx'
import ChatView from './views/ChatView.jsx'
import { UserBox } from './components/UserMenu.jsx'
import UsageCard from './components/UsageCard.jsx'
import { PanelIcon } from './components/Icon.jsx'

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
  // 侧栏折叠（M8）：记忆在 localStorage；收起后主区全宽，左上浮展开钮
  const [sideCollapsed, setSideCollapsed] = useState(() => localStorage.getItem('ca-side-collapsed') === '1')
  // 正在运行的会话（M8 侧栏树转圈）：ChatView 发消息时标记，结束/异常时解除
  const [runningIds, setRunningIds] = useState(() => new Set())

  const toggleSide = () => {
    setSideCollapsed((c) => {
      localStorage.setItem('ca-side-collapsed', c ? '0' : '1')
      return !c
    })
  }
  const handleRunning = (sessionId, running) => {
    setRunningIds((prev) => {
      const next = new Set(prev)
      if (running) next.add(sessionId)
      else next.delete(sessionId)
      return next
    })
  }

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

  // 侧栏状态对齐的兜底（M8）：本地标记是乐观显示，后端 status 才是真相。
  // 每 15 秒拉一次会话列表，网络抖动/事件回调丢失导致的转圈最多错 15 秒。
  useEffect(() => {
    const timer = setInterval(refreshSessions, 15_000)
    return () => clearInterval(timer)
  }, [])

  // 首条消息已消费：把 tab 里的 initialUser 清掉，切视图重挂载时不会重发
  const consumeInitial = (tabKey) => {
    setTabs((ts) => ts.map((t) => (t.key === tabKey ? { ...t, initialUser: null, initialAssistant: null } : t)))
  }
  // 会话号回写 tab（侧栏高亮 + 上下文 % 的数据来源）
  const handleSessionCreated = (sessionId) => {
    setTabs((ts) => ts.map((t) => (t.key === activeTab && t.sessionId == null ? { ...t, sessionId } : t)))
  }

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

  // 全局快捷键（图二同款标注）：⌘K/ Ctrl+K 搜索，⌘N/ Ctrl+N 新建任务。
  // ⌘N 浏览器可能抢走（新窗口），拦不住也无碍——按钮仍在侧栏。
  useEffect(() => {
    const onKey = (e) => {
      if (!(e.metaKey || e.ctrlKey)) return
      if (e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setSearchOpen(true)
      } else if (e.key.toLowerCase() === 'n') {
        e.preventDefault()
        newChat()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  })

  const toggleAccess = async () => {
    try {
      await api.setAccess(!accessFull)
      await refreshConfig()
    } catch { /* 静默：状态条会在下次刷新时对齐 */ }
  }

  const handlePermissionChange = async (mode) => {
    try {
      await api.setPermissionMode(mode)
      await refreshConfig()
    } catch { /* 静默：下次刷新对齐 */ }
  }
  const handleModelChange = async (name) => {
    try {
      await api.switchModel(name)
      await refreshConfig()
    } catch { /* 静默：下次刷新对齐 */ }
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

  // 新建任务（侧栏入口 / 标签栏 ＋ / 快捷键 ⌘N 三处共用）
  const newChat = () => {
    setRail('home')
    const tab = { key: `chat-${Date.now()}`, title: '新聊天', sessionId: null }
    setTabs((ts) => [...ts, tab])
    setActiveTab(tab.key)
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
  // 当前会话的上下文占用（最后轮输入 token ÷ 模型窗口 1M）：composer 的"上下文 %"
  // 注意：必须在 showChat 之后计算（要用它判断当前是否在聊天里）
  const contextPercent = (() => {
    const sid = showChat ? activeTabObj?.sessionId : null
    if (sid == null) return null
    const s = sessions.find((x) => x.id === sid)
    return s?.prompt_tokens != null ? s.prompt_tokens / 1_000_000 : null
  })()

  const modelLabel = config?.models?.find((m) => m.name === config?.active_model)?.model || '…'

  return (
    <div className={`app codex-app ${sideCollapsed ? 'side-collapsed' : ''}`}
         onClick={() => setNotifOpen(false)}>
      <IconRail active={rail} onNavigate={setRail} onOpenSettings={() => setSettingsOpen(true)} />

      {!sideCollapsed && (
        <Sidebar
          sessions={sessions}
          activeSessionId={showChat ? activeTabObj?.sessionId : null}
          onOpenSession={openSessionReplay}
          onNewChat={newChat}
          onOpenSettings={() => setSettingsOpen(true)}
          onOpenSearch={() => setSearchOpen(true)}
          onOpenNotifications={() => setNotifOpen(true)}
          onOpenPlugins={() => { setCustomizeOpen(true); setRail('none') }}
          onToggleCollapse={toggleSide}
          runningIds={runningIds}
        />
      )}
      {sideCollapsed && (
        <button className="icon-btn sidebar-expand" title="展开侧栏" onClick={toggleSide}>
          <PanelIcon size={15} />
        </button>
      )}

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
            onNew={newChat}
          />
          <div className="spacer" />
          <button className="icon-btn" title="工具坞：文件树 / 终端"
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
                    onRunningChange={handleRunning}
                    onInitialConsumed={() => consumeInitial(activeTab)}
                    onSessionCreated={handleSessionCreated}
                    contextPercent={contextPercent}
                    permissionMode={config?.permission_mode ?? 'confirm'}
                    onPermissionChange={handlePermissionChange}
                    models={config?.models ?? []}
                    activeModel={config?.active_model ?? ''}
                    onModelChange={handleModelChange}
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
                    onCommandResult={(userText, result) => openChat(userText, result)}
                    permissionMode={config?.permission_mode ?? 'confirm'}
                    onPermissionChange={handlePermissionChange}
                    models={config?.models ?? []}
                    activeModel={config?.active_model ?? ''}
                    onModelChange={handleModelChange} />
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
              permissionMode={config?.permission_mode ?? 'confirm'}
              onPermissionChange={handlePermissionChange}
              onClose={() => setSettingsOpen(false)}
              onOpenPlugins={() => { setSettingsOpen(false); setCustomizeOpen(true) }}
            />
            <button className="icon-btn fullpage-close" onClick={() => setSettingsOpen(false)}>✕</button>
          </div>
        )}

        {/* 底部状态条已随 M9 精简移除：模型/权限收进输入卡，设置入口在侧栏齿轮 */}
      </main>

      {toolPanel && <RightDock onClose={() => setToolPanel(false)} />}

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
