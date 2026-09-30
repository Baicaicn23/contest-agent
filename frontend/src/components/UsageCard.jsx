import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'

// Overview 用量卡（截图 1 中央的大卡）：Overview/模型 两个标签页，
// 全部/30天/7天 范围切换，六张统计卡 + 18 周热力图 + 趣味文案。
// 数据来自 GET /api/usage/summary——全部是成本台账的真实聚合。
const RANGES = [
  { key: 'all', label: '全部' },
  { key: '30d', label: '30 天' },
  { key: '7d', label: '7 天' },
]

export default function UsageCard() {
  const [tab, setTab] = useState('overview')
  const [range, setRange] = useState('all')
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.usageSummary(range).then(setData).catch((e) => setError(e.message))
  }, [range])

  return (
    <div className="usage-card">
      <div className="usage-head">
        <button className={`tab-btn ${tab === 'overview' ? 'active' : ''}`}
                onClick={() => setTab('overview')}>概览</button>
        <button className={`tab-btn ${tab === 'models' ? 'active' : ''}`}
                onClick={() => setTab('models')}>模型</button>
        <div className="spacer" />
        {RANGES.map((r) => (
          <button key={r.key}
                  className={`range-btn ${range === r.key ? 'active' : ''}`}
                  onClick={() => setRange(r.key)}>{r.label}</button>
        ))}
      </div>

      {error && <div className="models-empty">加载失败：{error}</div>}
      {!error && !data && <div className="models-empty">加载中…</div>}

      {data && tab === 'overview' && (
        <>
          <div className="stat-grid">
            <Stat label="会话" value={data.sessions} />
            <Stat label="消息" value={data.messages} />
            <Stat label="总 token" value={fmtTokens(data.total_tokens)} />
            <Stat label="活跃天数" value={data.active_days} />
            <Stat label="高峰时段" value={data.peak_hour != null ? `${data.peak_hour} 点` : '—'} />
            <Stat label="常用模型" value={data.favorite_model || '—'} />
          </div>
          <Heatmap daily={data.daily} />
          <p className="fun-fact">{data.fun_fact}</p>
        </>
      )}

      {data && tab === 'models' && (
        Object.keys(data.by_model).length > 0 ? (
          <table className="models-table">
            <thead>
              <tr><th>模型</th><th>token 用量</th><th>占比</th></tr>
            </thead>
            <tbody>
              {Object.entries(data.by_model).map(([model, tokens]) => (
                <tr key={model}>
                  <td>{model}</td>
                  <td>{fmtTokens(tokens)}</td>
                  <td>{data.total_tokens ? `${Math.round((tokens / data.total_tokens) * 100)}%` : '0%'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="models-empty">还没有任何模型用量。跑一次识别或对话就有了。</div>
        )
      )}
    </div>
  )
}

function Stat({ label, value }) {
  return (
    <div className="stat-cell">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
    </div>
  )
}

function fmtTokens(n) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

// 18 周 × 7 天的热力图（对应截图的灰格子 + 一格亮色）。
// 数据只有"有用量的日子"，这里补齐成完整网格：从本周往回推 18 周，
// 每列一周（周一到周日），今天的列之后的格子留空。
function Heatmap({ daily }) {
  const grid = useMemo(() => {
    const byDate = Object.fromEntries((daily || []).map((d) => [d.date, d.tokens]))
    const max = Math.max(1, ...(daily || []).map((d) => d.tokens))
    const today = new Date()
    const monday = new Date(today)
    monday.setDate(today.getDate() - ((today.getDay() + 6) % 7)) // 本周一

    const weeks = []
    for (let w = 17; w >= 0; w--) {
      const days = []
      for (let d = 0; d < 7; d++) {
        const day = new Date(monday)
        day.setDate(monday.getDate() - w * 7 + d)
        const key = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`
        const tokens = byDate[key]
        const future = day > today
        const level = future ? null
          : tokens == null ? 0
          : tokens < max * 0.34 ? 1
          : tokens < max * 0.67 ? 2
          : 3
        days.push({ key, level, tokens })
      }
      weeks.push(days)
    }
    return weeks
  }, [daily])

  return (
    <div className="heat-grid" title="每日 token 用量">
      {grid.map((week, wi) =>
        week.map((day, di) => (
          <div key={`${wi}-${di}`}
               className={`heat-cell ${day.level ? `l${day.level}` : ''} ${day.level === null ? 'future' : ''}`}
               style={day.level === null ? { visibility: 'hidden' } : undefined}
               title={day.tokens != null ? `${day.key}：${day.tokens} token` : day.key} />
        ))
      )}
    </div>
  )
}
