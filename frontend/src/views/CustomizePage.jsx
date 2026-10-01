import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'

// Customize 页（对应截图 5）：插件市场 + 技能清单。
// 插件 = 系统能力开关（真实写 config）；技能 = skills/ 目录真实文件。
const TABS = [
  { key: '公开', label: '公开' },
  { key: '个人', label: '个人' },
]

export default function CustomizePage({ onOpenSettings }) {
  const [nav, setNav] = useState('plugins')
  const [tab, setTab] = useState('公开')
  const [query, setQuery] = useState('')
  const [plugins, setPlugins] = useState([])
  const [skills, setSkills] = useState([])
  const [busy, setBusy] = useState('')

  const load = () => {
    api.plugins().then((r) => setPlugins(r.plugins)).catch(() => {})
    api.skills().then((r) => setSkills(r.skills)).catch(() => {})
  }
  useEffect(load, [])

  const installed = plugins.filter((p) => p.enabled)
  const categories = [...new Set(plugins.map((p) => p.category))]
  const shown = plugins.filter((p) =>
    !query || p.name.toLowerCase().includes(query.toLowerCase()))

  const toggle = async (p) => {
    if (!p.toggleable) return
    setBusy(p.id)
    try {
      await api.togglePlugin(p.id, !p.enabled)
      await load()
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="customize-root">
      <div className="settings-nav page">
        <h1 style={{ fontSize: 20, margin: '0 0 14px' }}>Customize</h1>
        <button className={`side-item ${nav === 'plugins' ? 'active' : ''}`}
                onClick={() => setNav('plugins')}>
          <span className="icon">⬡</span> 插件
        </button>
        <button className={`side-item ${nav === 'skills' ? 'active' : ''}`}
                onClick={() => setNav('skills')}>
          <span className="icon">📚</span> Skills
        </button>
        <div className="side-section">Installed</div>
        <div style={{ padding: '4px 10px', fontSize: 13, color: 'var(--text-dim)' }}>
          {installed.length ? installed.map((p) => p.name).join('、') : '暂无已安装插件'}
        </div>
      </div>

      <div className="settings-body">
        {nav === 'plugins' && (
          <>
            <div className="plugins-head">
              <h1 className="sec-title" style={{ marginBottom: 6 }}>插件</h1>
              <div className="desc" style={{ fontSize: 13.5, color: 'var(--text-dim)' }}>
                连接能力插件，让助手在你的工作流中协同作战（安装状态真实写回 config.yaml）
              </div>
              <input className="text-input plugins-search" placeholder="搜索插件"
                     value={query} onChange={(e) => setQuery(e.target.value)} />
              <button className="pill-btn" onClick={load}>↻</button>
            </div>
            <div className="seg-group" style={{ margin: '14px 0 20px' }}>
              {TABS.map((t) => (
                <button key={t.key} className={tab === t.key ? 'active' : ''}
                        onClick={() => setTab(t.key)}>{t.label}</button>
              ))}
            </div>

            {categories.map((cat) => {
              const items = shown.filter((p) => p.category === cat)
              if (!items.length) return null
              return (
                <div key={cat} style={{ marginBottom: 26 }}>
                  <div className="card-title" style={{ marginBottom: 8 }}>{cat}</div>
                  <div className="plugin-grid">
                    {items.map((p) => (
                      <div key={p.id} className="plugin-card">
                        <div className="plugin-info">
                          <div className="plugin-name">{p.name}
                            {p.enabled && <span className="plugin-on">已安装</span>}
                          </div>
                          <div className="plugin-desc">{p.desc}</div>
                        </div>
                        {p.toggleable ? (
                          <button className="plugin-add" disabled={busy === p.id}
                                  title={p.enabled ? '点击卸载' : '点击安装'}
                                  onClick={() => toggle(p)}>
                            {busy === p.id ? '…' : p.enabled ? '✓' : '＋'}
                          </button>
                        ) : (
                          <span className="plugin-cfg" title="在 config.yaml 的 push 段配置后自动启用">需配置</span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
            {!shown.length && <div className="models-empty">没有匹配的插件。</div>}
          </>
        )}

        {nav === 'skills' && (
          <>
            <h1 className="sec-title">Skills</h1>
            {skills.map((s) => (
              <div key={s.file} className="settings-row">
                <div>
                  <div className="label">{s.name}</div>
                  <div className="desc">{s.description}</div>
                </div>
                <div className="control mono">{s.file}</div>
              </div>
            ))}
            {!skills.length && <div className="models-empty">skills/ 目录为空。</div>}
          </>
        )}
      </div>
    </div>
  )
}
