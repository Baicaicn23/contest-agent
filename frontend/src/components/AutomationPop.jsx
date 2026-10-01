import { useState } from 'react'
import { api } from '../api.js'

// "自动化"弹层（侧栏操作区入口）：盯梢能力的真实状态与手动触发。
// 真实数据：sessions 里 task_type=watch 的最近一条 = 上次定时盯梢；
// "立即扫描"调 POST /scan（只扫通知列表，不花 LLM，秒回）；
// 真正的定时识别+推送由 sai watch + 系统 cron 接管（弹层里给出接入命令）。
export default function AutomationPop({ sessions, onClose }) {
  const [scanning, setScanning] = useState(false)
  const [result, setResult] = useState(null)
  const lastWatch = sessions.find((s) => s.task_type === 'watch')

  const scanNow = async () => {
    setScanning(true)
    setResult(null)
    try {
      const r = await api.scan(10)
      setResult(`扫描完成：${r.count} 条通知，新增 ${r.sync?.new ?? 0} 条。`)
    } catch (e) {
      setResult(`注意：${e.message}`)
    } finally {
      setScanning(false)
    }
  }

  return (
    <div className="popover automation-pop" onClick={(e) => e.stopPropagation()}>
      <div className="menu-user">
        <div className="name">自动化</div>
        <div className="sub">定时盯梢与手动触发</div>
      </div>
      <div className="menu-sep" />
      <div className="auto-row">
        <span className="auto-label">上次定时盯梢</span>
        <span className="auto-value">
          {lastWatch ? `${lastWatch.status === 'completed' ? '正常' : lastWatch.status} · ${relTime(lastWatch.started_at)}前` : '还没跑过'}
        </span>
      </div>
      <button className="menu-item" onClick={scanNow} disabled={scanning}>
        <span className="icon">{scanning ? '…' : '扫'}</span>
        {scanning ? '正在扫描通知…' : '立即扫描通知（不花 LLM）'}
      </button>
      {result && (
        <div className="auto-result">{result}</div>
      )}
      <div className="menu-sep" />
      <div className="auto-hint">
        定时识别 + 推送由系统 cron 接管，接入一行：
        <code className="mono">*/30 * * * * cd 项目目录 &amp;&amp; uv run sai watch</code>
      </div>
      <div className="menu-sep" />
      <button className="menu-item" onClick={onClose}>关闭</button>
    </div>
  )
}

// 与 Sidebar 的 relTime 同口径（这里就近复制一份，避免循环依赖）
function relTime(iso) {
  if (!iso) return ''
  const diff = Date.now() - new Date(iso).getTime()
  if (Number.isNaN(diff)) return ''
  const m = Math.floor(diff / 60000)
  if (m < 60) return `${m}分`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}小时`
  return `${Math.floor(h / 24)}天`
}
