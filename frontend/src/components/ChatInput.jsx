import { useEffect, useRef, useState } from 'react'
import { COMMANDS, api } from '../api.js'
import { PlusIcon, ShieldIcon, ChevronDownIcon, CheckIcon, XSmallIcon, FileIcon } from './Icon.jsx'

// 三处复用的输入卡（M9 重构为图四形态）：工作台底部 / 会话底部。
// 底部工具行全部集中在对话框内：
//   ＋上传（真实落盘 output/uploads/）｜权限三档（只读/变更前确认/完全访问）
//   ｜上下文 %｜模型切换｜发送。
// 上传的附件以 chip 显示，发送时以"[已上传: …]"并入消息文本。
// "/" 唤起命令面板（↑↓ 选择、Enter 执行）逻辑不变。

const PERMISSION_LABELS = {
  readonly: '只读',
  confirm: '变更前确认',
  full: '完全访问',
}
const PERMISSION_HINTS = {
  readonly: '写类工具（扫官网/识别/存材料）一律拒绝，agent 只能查不能改',
  confirm: '写类工具执行前需确认；网页聊天无法弹确认，会自动拦截（终端 sai 可交互确认）',
  full: '全部工具自动放行，无需确认',
}
// 模型上下文窗口（token）：与官方页对齐（deepseek-flash 1M）。切换模型时如有差异再配置化
const CONTEXT_WINDOW = 1_000_000

export default function ChatInput({ onSend, onCommandResult, busy = false,
                                    centered = false, placeholder = '描述任务或提问…',
                                    contextPercent = null,
                                    permissionMode = 'confirm', onPermissionChange,
                                    models = [], activeModel = '', onModelChange }) {
  const [text, setText] = useState('')
  const [cmdIndex, setCmdIndex] = useState(0)
  const [paletteClosed, setPaletteClosed] = useState(false)
  const [attachments, setAttachments] = useState([])   // [{name}]
  const [uploading, setUploading] = useState(false)
  const [permOpen, setPermOpen] = useState(false)
  const [modelOpen, setModelOpen] = useState(false)
  const wrapRef = useRef(null)
  const fileRef = useRef(null)

  const paletteOpen = text.startsWith('/') && !paletteClosed
  const matches = paletteOpen
    ? COMMANDS.filter((c) =>
        c.cmd.includes(text) || c.desc.includes(text.slice(1)))
    : []

  useEffect(() => setCmdIndex(0), [text])

  // 点击输入卡外部时收起命令面板与两个下拉
  useEffect(() => {
    const onDocClick = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setPaletteClosed(true)
        setPermOpen(false)
        setModelOpen(false)
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
    let trimmed = text.trim()
    if (!trimmed && !attachments.length) return
    if (attachments.length) {
      // 附件以可读方式并入消息：文件真实在 output/uploads/，agent 与用户都能追溯
      const lines = attachments.map((a) => `[已上传: ${a.name}]`).join('\n')
      trimmed = trimmed ? `${trimmed}\n${lines}` : lines
    }
    setText('')
    setAttachments([])
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
    if (e.key === 'Escape') { setPaletteClosed(true); setPermOpen(false); setModelOpen(false) }
  }

  const pickFiles = () => fileRef.current?.click()
  const onFilesPicked = async (e) => {
    const files = [...(e.target.files || [])]
    e.target.value = ''   // 允许重复选同一个文件
    if (!files.length) return
    setUploading(true)
    for (const file of files) {
      try {
        const r = await api.upload(file)
        setAttachments((prev) => [...prev, { name: r.name }])
      } catch (err) {
        setAttachments((prev) => [...prev, { name: `上传失败：${err.message}`, failed: true }])
      }
    }
    setUploading(false)
  }

  const activeModelInfo = models.find((m) => m.name === activeModel)

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
        {attachments.length > 0 && (
          <div className="attach-row">
            {attachments.map((a, i) => (
              <span key={i} className={`attach-chip ${a.failed ? 'failed' : ''}`}>
                <FileIcon size={12} /> {a.name}
                <button className="attach-x" title="移除"
                        onClick={() => setAttachments((prev) => prev.filter((_, j) => j !== i))}>
                  <XSmallIcon size={10} />
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="composer-bar">
          {/* ＋ 上传：真实上传到 output/uploads/ */}
          <button className="icon-btn" title="上传文件（存到 output/uploads/）"
                  disabled={uploading} onClick={pickFiles}>
            <PlusIcon />
          </button>
          <input ref={fileRef} type="file" multiple hidden onChange={onFilesPicked} />

          {/* 权限三档（读写真实落到 config.yaml 的 permission_mode） */}
          <div className="composer-pop-wrap">
            <button className={`perm-pill mode-${permissionMode}`}
                    title={PERMISSION_HINTS[permissionMode]}
                    onClick={() => { setPermOpen(!permOpen); setModelOpen(false) }}>
              <ShieldIcon size={13} /> {PERMISSION_LABELS[permissionMode] || permissionMode}
              <ChevronDownIcon size={11} />
            </button>
            {permOpen && (
              <div className="composer-pop">
                {Object.entries(PERMISSION_LABELS).map(([mode, label]) => (
                  <button key={mode} className="cmd-item"
                          onClick={() => { onPermissionChange?.(mode); setPermOpen(false) }}>
                    <span className="perm-pop-label">{label}</span>
                    <span className="desc">{PERMISSION_HINTS[mode]}</span>
                    {permissionMode === mode && <span className="check"><CheckIcon /></span>}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="spacer" />

          {/* 上下文占用（当前会话累计输入 token ÷ 模型窗口） */}
          {contextPercent != null && (
            <span className="ctx-pill" title="当前会话已用上下文（累计输入 token ÷ 模型窗口 1M）">
              上下文 {Math.max(1, Math.round(contextPercent * 100))}%
            </span>
          )}

          {/* 模型切换（写回 config.yaml，与 CLI/设置页同一真相） */}
          <div className="composer-pop-wrap">
            <button className="model-pill" title="切换模型档案"
                    onClick={() => { setModelOpen(!modelOpen); setPermOpen(false) }}>
              <span>{activeModelInfo ? activeModelInfo.model : '…'}</span>
              <ChevronDownIcon size={11} />
            </button>
            {modelOpen && (
              <div className="composer-pop model-pop">
                {models.map((m) => (
                  <button key={m.name} className="cmd-item"
                          onClick={() => { onModelChange?.(m.name); setModelOpen(false) }}>
                    <span className="perm-pop-label">{m.model}</span>
                    <span className="desc">{m.name}{m.has_key ? '' : '（缺密钥）'}</span>
                    {m.name === activeModel && <span className="check"><CheckIcon /></span>}
                  </button>
                ))}
              </div>
            )}
          </div>

          <button className="send-btn" onClick={submit} disabled={busy || (!text.trim() && !attachments.length)}
                  title="发送（Enter）">↑</button>
        </div>
      </div>
    </div>
  )
}
