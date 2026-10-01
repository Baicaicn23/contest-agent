import { useEffect, useRef, useState } from 'react'
import { COMMANDS } from '../api.js'

// 三处复用的输入卡：工作台底部 / 情报站居中 / 会话底部。
// 职责：文本输入、Enter 发送、"/" 唤起命令面板（↑↓ 选择、Enter 执行）。
// 命令的执行结果通过 onCommandResult(命令, 结果文本) 交回父组件渲染；
// 普通消息通过 onSend(文本) 交回父组件（聊天气泡 or 新会话）。
export default function ChatInput({ onSend, onCommandResult, busy = false,
                                    centered = false, placeholder = '描述任务或提问…' }) {
  const [text, setText] = useState('')
  const [cmdIndex, setCmdIndex] = useState(0)
  const [paletteClosed, setPaletteClosed] = useState(false)
  const wrapRef = useRef(null)

  const paletteOpen = text.startsWith('/') && !paletteClosed
  const matches = paletteOpen
    ? COMMANDS.filter((c) =>
        c.cmd.includes(text) || c.desc.includes(text.slice(1)))
    : []

  useEffect(() => setCmdIndex(0), [text])

  // 点击输入卡外部时收起命令面板
  useEffect(() => {
    const onDocClick = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setPaletteClosed(true)
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  const runCommand = async (cmd) => {
    const original = text
    setText('')
    setPaletteClosed(false)
    try {
      const result = await cmd.run()
      onCommandResult?.(cmd, result, original)
    } catch (error) {
      onCommandResult?.(cmd, `注意：${error.message}`, original)
    }
  }

  const submit = async () => {
    if (busy) return
    if (paletteOpen && matches.length > 0) {
      await runCommand(matches[Math.min(cmdIndex, matches.length - 1)])
      return
    }
    const trimmed = text.trim()
    if (!trimmed) return
    setText('')
    setPaletteClosed(false)
    onSend?.(trimmed)
  }

  const onKeyDown = (e) => {
    if (paletteOpen && matches.length > 0) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setCmdIndex((i) => (i + 1) % matches.length); return }
      if (e.key === 'ArrowUp') { e.preventDefault(); setCmdIndex((i) => (i - 1 + matches.length) % matches.length); return }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
    if (e.key === 'Escape') setPaletteClosed(true)
  }

  return (
    <div className={centered ? 'composer-wrap center' : 'composer-wrap'} ref={wrapRef}
         style={centered ? { width: 'min(720px, 86%)', position: 'relative' } : { position: 'relative' }}>
      {paletteOpen && (
        <div className="cmd-palette">
          {matches.length === 0 && (
            <div style={{ padding: '10px 14px', fontSize: 13, color: 'var(--text-dim)' }}>
              没有匹配的命令。可用：{COMMANDS.map((c) => c.cmd).join(' ')}
            </div>
          )}
          {matches.map((c, i) => (
            <button key={c.cmd}
                    className={`cmd-item ${i === Math.min(cmdIndex, matches.length - 1) ? 'highlight' : ''}`}
                    onClick={() => runCommand(c)}>
              <span className="cmd">{c.cmd}</span>
              <span className="desc">{c.desc}</span>
            </button>
          ))}
        </div>
      )}
      <div className={`composer ${centered ? 'centered' : ''}`}>
        <textarea
          value={text}
          rows={centered ? 3 : 1}
          placeholder={placeholder}
          onChange={(e) => { setText(e.target.value); setPaletteClosed(false) }}
          onKeyDown={onKeyDown}
          autoFocus={centered}
        />
        <div className="composer-bar">
          <button className="pill-btn" title="附件（视觉占位）">＋</button>
          <div className="spacer" />
          {centered && <span style={{ fontSize: 12.5, color: 'var(--text-dim)' }}>标准</span>}
          <button className="send-btn" onClick={submit} disabled={busy || !text.trim()}
                  title="发送（Enter）">↑</button>
        </div>
      </div>
    </div>
  )
}
