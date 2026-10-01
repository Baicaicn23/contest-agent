import { useEffect, useState } from 'react'
import { api } from '../api.js'
import ChatInput from '../components/ChatInput.jsx'
import ProjectChip from '../components/ProjectChip.jsx'
import Logo from '../components/Logo.jsx'

// Codex 式首页（截图 1）：云图标 + "你想让我们在 {项目} 中构建什么?" +
// 大输入卡 + chips 行（项目/本地/分支）+ 截止临近 + 点子。
export default function HomeView({ userName, project, onProjectChange, branch,
                                   accessFull, onToggleAccess, modelLabel,
                                   onSend, onCommand, onCommandResult, className = '' }) {
  const [deadlines, setDeadlines] = useState([])

  useEffect(() => {
    api.deadlines().then((r) => setDeadlines(r.deadlines || [])).catch(() => {})
  }, [])

  return (
    <div className={`home-root ${className}`}>
      <div className="home-scroll">
        <div className="home-hero">
          <div className="cloud-icon">
            <span className="cloud-glyph">{'>_'}</span>
          </div>
          <h1 className="hero-question">
            你想让我们在 <span className="hero-project">{project ? project.name : '比赛情报'}</span> 中构建什么？
          </h1>
        </div>

        {deadlines.length > 0 && (
          <div className="home-deadlines">
            <div className="ideas-title">截止临近</div>
            {deadlines.slice(0, 4).map((d) => (
              <a key={d.url} className="idea-row" href={d.url} target="_blank" rel="noreferrer">
                <span className={`idea-icon ddl-dot l${d.remaining <= 1 ? 3 : d.remaining <= 3 ? 2 : 1}`} />
                <span style={{ flex: 1 }}>
                  {d.name}
                  <span style={{ color: 'var(--text-dim)', marginLeft: 8, fontSize: 13 }}>{d.label}</span>
                </span>
                <span style={{ color: 'var(--text-faint)', fontSize: 12.5 }}>{d.deadline}</span>
              </a>
            ))}
          </div>
        )}

        <div className="ideas">
          <div className="ideas-title">给你几个点子</div>
          <button className="idea-row" onClick={() => onCommand('识别')}>
            <span className="idea-icon txt-badge">识别</span> 识别最新通知
          </button>
          <button className="idea-row" onClick={() => onCommand('生成')}>
            <span className="idea-icon txt-badge">材料</span> 为最近的比赛生成 PPT
          </button>
          <button className="idea-row" onClick={() => onCommand('账单')}>
            <span className="idea-icon txt-badge">账单</span> 看看今天花了多少钱
          </button>
        </div>
      </div>

      <div className="composer-wrap" style={{ position: 'relative' }}>
        <div className="chips-row">
          <ProjectChip selected={project} onSelect={onProjectChange} />
          <button className="pill-btn">本地</button>
          <button className="pill-btn" title="当前 git 分支">⑂ {branch}</button>
          <div className="spacer" />
          <button className={`pill-btn ${accessFull ? 'pill-warn' : ''}`}
                  title={accessFull ? '完全访问已开启：权限门全放行' : '开启后权限门全放行（写回 config.yaml）'}
                  onClick={onToggleAccess}>
            {accessFull ? '完全访问（开）' : '受限访问'}
          </button>
          <button className="pill-btn" title="当前模型（点击去设置切换）">{modelLabel}</button>
        </div>
        <ChatInput
          centered
          placeholder="随心输入"
          onSend={(text) => onSend(text, project)}
          onCommandResult={(cmd, result, original) =>
            onCommandResult?.(original || cmd.cmd, result)}
        />
        <div className="under-chips">
          <button className="pill-btn">＋</button>
          <span style={{ fontSize: 12.5, color: 'var(--text-faint)', marginLeft: 'auto' }}>
            {userName} · 本地
          </span>
        </div>
      </div>
    </div>
  )
}
