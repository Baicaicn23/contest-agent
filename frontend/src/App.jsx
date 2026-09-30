import { useEffect, useState } from 'react'
import { api } from './api.js'
import Sidebar from './components/Sidebar.jsx'
import CodeHome from './views/CodeHome.jsx'
import CoworkHome from './views/CoworkHome.jsx'
import ChatView from './views/ChatView.jsx'
import SettingsModal from './components/SettingsModal.jsx'

// 应用外壳：管"全局状态"，把界面拆给三个视图组件。
// 全局状态有四类：模式（情报站/工作台）、当前视图（首页/某个会话）、
// 配置（模型档案等，Settings 面板可改）、主题与字号（localStorage 持久化）。
// 注意：故意不引入 react-router——"视图切换"用一个 state 就够了，
// 浏览器路由对这个单页工具是多余的依赖。

const THEME_KEY = 'ca-theme'
const FS_KEY = 'ca-fontsize'

export default function App() {
  const [mode, setMode] = useState('code')
  const [view, setView] = useState({ type: 'home' })
  const [config, setConfig] = useState(null)
  const [sessions, setSessions] = useState([])
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [theme, setTheme] = useState(() => localStorage.getItem(THEME_KEY) || 'light')
  const [fontSize, setFontSize] = useState(() => localStorage.getItem(FS_KEY) || 'medium')

  // 主题/字号写进 <html> 的 data 属性 → tokens.css 的变量整体切换
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem(THEME_KEY, theme)
  }, [theme])
  useEffect(() => {
    document.documentElement.dataset.fs = fontSize
    localStorage.setItem(FS_KEY, fontSize)
  }, [fontSize])

  const refreshConfig = () => api.config().then(setConfig).catch(() => {})
  const refreshSessions = () => api.sessions(30).then((r) => setSessions(r.sessions)).catch(() => {})

  useEffect(() => {
    refreshConfig()
    refreshSessions()
  }, [])

  const openSession = async (session) => {
    setView({ type: 'chat', sessionId: session.id, title: session.note || `会话 #${session.id}` })
  }
  const newChat = () => setView({ type: 'chat', sessionId: null, title: '新会话', nonce: Date.now() })
  const goHome = () => setView({ type: 'home' })

  const activeModel = config?.models?.find((m) => m.name === config?.active_model)
  const modelLabel = activeModel ? activeModel.model : '…'

  return (
    <div className="app"
         onClick={() => document.body.dispatchEvent(new Event('click-outside'))}>
      <Sidebar
        mode={mode}
        onModeChange={(m) => { setMode(m); goHome() }}
        sessions={sessions}
        activeSessionId={view.type === 'chat' ? view.sessionId : null}
        onOpenSession={openSession}
        onNewChat={() => { setMode('code'); newChat() }}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <main className="main">
        {view.type === 'chat' ? (
          <ChatView key={view.nonce ?? view.sessionId}
                    sessionId={view.sessionId}
                    title={view.title}
                    initialUser={view.initialUser}
                    initialAssistant={view.initialAssistant}
                    onSessionsChanged={refreshSessions} />
        ) : mode === 'code' ? (
          <CodeHome userName="momo"
                    onOpenChat={(firstText, assistantText) => {
                      setMode('code')
                      setView({ type: 'chat', sessionId: null, title: '新会话', nonce: Date.now(),
                                initialUser: firstText, initialAssistant: assistantText })
                    }} />
        ) : (
          <CoworkHome userName="momo"
                      onOpenChat={(userText, assistantText) => {
                        setMode('code')
                        setView({ type: 'chat', sessionId: null, title: '新会话', nonce: Date.now(),
                                  initialUser: userText, initialAssistant: assistantText })
                      }} />
        )}

        {/* 底部状态条：左侧入库策略，右侧当前模型（点击进设置切换） */}
        <div className="statusbar">
          <button className="pill-btn" onClick={() => setSettingsOpen(true)}>
            自动入库 <span>＋</span>
          </button>
          <div className="spacer" />
          {config?.budget_per_task_yuan != null && (
            <span>预算 {config.budget_per_task_yuan} 元/任务</span>
          )}
          <button className="model-pill" onClick={() => setSettingsOpen(true)}
                  title="点击切换模型档案">
            <span>{modelLabel}</span>
            <span className={`dot ${activeModel?.has_key ? 'ok' : ''}`} />
          </button>
        </div>
      </main>

      {settingsOpen && (
        <SettingsModal
          config={config}
          onConfigChange={refreshConfig}
          theme={theme} setTheme={setTheme}
          fontSize={fontSize} setFontSize={setFontSize}
          onClose={() => setSettingsOpen(false)}
        />
      )}
    </div>
  )
}
