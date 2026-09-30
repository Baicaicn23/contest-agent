import { useEffect, useState } from 'react'
import Logo from '../components/Logo.jsx'
import ChatInput from '../components/ChatInput.jsx'
import { api, COMMANDS } from '../api.js'

// 情报站首页（截图 3）：serif 大字问候 + 居中大输入卡 + "给你几个点子"。
// 点子的行为：直接执行对应命令，跳到会话页展示结果。
const IDEAS = [
  { icon: '🕷', label: '识别最新通知', cmd: '/识别' },
  { icon: '📝', label: '生成参赛材料', cmd: '/生成' },
  { icon: '📚', label: '生成备考路径', cmd: '/备考' },
  { icon: '💰', label: '看看今天花了多少钱', cmd: '/账单' },
]

export default function CoworkHome({ userName, onOpenChat }) {
  const [deadlines, setDeadlines] = useState([])

  // 截止守望（方向①）：把临近截止的比赛顶到最显眼的位置
  useEffect(() => {
    api.deadlines().then((r) => setDeadlines(r.deadlines || [])).catch(() => {})
  }, [])

  const runIdea = async (cmdText) => {
    const cmd = COMMANDS.find((c) => c.cmd === cmdText)
    if (!cmd) return
    try {
      const result = await cmd.run()
      onOpenChat(cmdText, result)
    } catch (error) {
      onOpenChat(cmdText, `⚠️ ${error.message}`)
    }
  }

  return (
    <div className="cowork-hero">
      <div className="hero-title">
        <Logo size={46} className="logo" />
        <h1 className="greeting-serif">你来了，{userName}！</h1>
      </div>

      <div className="hero-input-wrap">
        <ChatInput
          centered
          placeholder="今天我能帮你做什么？"
          onSend={(text) => onOpenChat(text)}
          onCommandResult={(cmd, result, original) => onOpenChat(original || cmd.cmd, result)}
        />
        <div className="under-chips">
          <button className="pill-btn">▤ 项目或文件夹</button>
        </div>
      </div>

      {deadlines.length > 0 && (
        <div className="ideas" style={{ marginTop: 0, marginBottom: 32 }}>
          <div className="ideas-title">⏰ 截止临近</div>
          {deadlines.slice(0, 5).map((d) => (
            <a key={d.url} className="idea-row" href={d.url} target="_blank" rel="noreferrer">
              <span className="idea-icon" style={d.urgent ? { color: 'var(--accent)', borderColor: 'var(--accent)' } : undefined}>
                {d.remaining === 0 ? '🔴' : d.remaining === 1 ? '🟠' : d.remaining <= 3 ? '🟡' : '🔵'}
              </span>
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
        {IDEAS.map((idea) => (
          <button key={idea.cmd} className="idea-row" onClick={() => runIdea(idea.cmd)}>
            <span className="idea-icon">{idea.icon}</span>
            {idea.label}
          </button>
        ))}
      </div>
    </div>
  )
}
