import { useEffect, useState } from 'react'
import { api } from '../api.js'

// Settings 弹窗（截图 5）：左侧导航 + 右面板。
// 真实生效的能力：外观（亮暗主题/字号，写 localStorage）、
// 通用（切模型档案、改预算——写 config.yaml）、用量（真台账数字）。
// 其余分区为视觉占位（本项目没有对应功能，界面照摆以复刻）。
const NAV = [
  { group: '设置', items: [
    { key: 'general', icon: '⚙', label: '通用' },
    { key: 'privacy', icon: '🛡', label: '隐私', stub: true },
    { key: 'usage', icon: '📊', label: '用量' },
    { key: 'appearance', icon: '⌘', label: 'Contest Agent' },
    { key: 'cowork', icon: '≣', label: '情报站', stub: true },
    { key: 'importexport', icon: '↓', label: '导入与导出', stub: true },
  ]},
  { group: '桌面端', items: [
    { key: 'system', icon: '🖥', label: '系统', stub: true },
    { key: 'developer', icon: '🔧', label: '开发者', stub: true },
  ]},
  { group: '自定义', items: [
    { key: 'skills', icon: '📑', label: '技能' },
    { key: 'connectors', icon: '🔌', label: '连接器', stub: true },
    { key: 'plugins', icon: '🧩', label: '插件', stub: true },
  ]},
]

export default function SettingsModal({ config, onConfigChange, theme, setTheme,
                                         fontSize, setFontSize, onClose }) {
  const [section, setSection] = useState('appearance')
  const [budget, setBudgetLocal] = useState('')
  const [budgetHint, setBudgetHint] = useState('')
  const [modelPicked, setModelPicked] = useState(config?.active_model)

  useEffect(() => {
    setBudgetLocal(config?.budget_per_task_yuan ?? '')
    setModelPicked(config?.active_model)
  }, [config])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const saveBudget = async () => {
    const value = String(budget).trim()
    const yuan = value === '' || value === 'null' ? null : Number(value)
    if (yuan !== null && (Number.isNaN(yuan) || yuan < 0)) {
      setBudgetHint('预算要是非负数字，或留空表示不限')
      return
    }
    try {
      await api.setBudget(yuan)
      setBudgetHint('已保存并写回 config.yaml ✓')
      onConfigChange()
    } catch (e) {
      setBudgetHint(e.message)
    }
  }

  const switchModel = async (name) => {
    setModelPicked(name)
    try {
      await api.switchModel(name)
      onConfigChange()
    } catch (e) {
      setBudgetHint(e.message)
    }
  }

  return (
    <div className="modal-mask" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal">
        {/* 左导航 */}
        <div className="settings-nav">
          <input className="search" placeholder="搜索" />
          {NAV.map((group) => (
            <div key={group.group}>
              <div className="group-label">{group.group}</div>
              {group.items.map((item) => (
                <button key={item.key}
                        className={`side-item ${section === item.key ? 'active' : ''}`}
                        onClick={() => setSection(item.key)}>
                  <span className="icon">{item.icon.trim() || '▣'}</span> {item.label}
                </button>
              ))}
            </div>
          ))}
        </div>

        {/* 右面板 */}
        <div className="settings-body">
          <button className="icon-btn close-btn" onClick={onClose}>✕</button>

          {section === 'appearance' && (
            <>
              <h2>外观</h2>
              <div className="diff-preview">
                <div>
                  <select className="select-box" style={{ width: '100%', marginBottom: 12 }}
                          value={theme} onChange={(e) => setTheme(e.target.value)}>
                    <option value="light">亮色（Claude Light）</option>
                    <option value="dark">暗色（Claude Dark）</option>
                  </select>
                  <CodePreview dark={false} />
                </div>
                <div>
                  <select className="select-box" style={{ width: '100%', marginBottom: 12 }}
                          value={theme} onChange={(e) => setTheme(e.target.value)}>
                    <option value="dark">暗色（Claude Dark）</option>
                    <option value="light">亮色（Claude Light）</option>
                  </select>
                  <CodePreview dark />
                </div>
              </div>

              <div style={{ height: 18 }} />
              <h2>界面</h2>
              <div className="settings-row">
                <div>
                  <div className="label">界面字体</div>
                  <div className="desc">整个界面的字体——菜单、侧栏和面板。</div>
                </div>
                <div className="control seg-group">
                  <button className="active">系统</button>
                  <button>衬线</button>
                  <button>无障碍</button>
                </div>
              </div>
              <div className="settings-row">
                <div>
                  <div className="label">正文字号</div>
                  <div className="desc">会话正文的文字大小（立即生效并记住）。</div>
                </div>
                <div className="control seg-group">
                  {[['small', '小'], ['medium', '中'], ['large', '大']].map(([key, label]) => (
                    <button key={key} className={fontSize === key ? 'active' : ''}
                            onClick={() => setFontSize(key)}>{label}</button>
                  ))}
                </div>
              </div>
            </>
          )}

          {section === 'general' && config && (
            <>
              <h2>通用</h2>
              <div className="settings-row">
                <div>
                  <div className="label">模型档案</div>
                  <div className="desc">当前生效：{config.active_model}。切换会写回 config.yaml，对 CLI 同样生效。</div>
                </div>
                <div className="control">
                  <select className="select-box" value={modelPicked}
                          onChange={(e) => switchModel(e.target.value)}>
                    {config.models.map((m) => (
                      <option key={m.name} value={m.name}>
                        {m.name}（{m.model}{m.has_key ? '' : '，缺密钥'}）
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="settings-row">
                <div>
                  <div className="label">单任务预算上限（元）</div>
                  <div className="desc">一次任务的花费达到上限就熔断；留空表示不限。</div>
                  {budgetHint && <div className="desc" style={{ color: 'var(--accent)' }}>{budgetHint}</div>}
                </div>
                <div className="control" style={{ display: 'flex', gap: 8 }}>
                  <input className="text-input" value={budget}
                         placeholder="如 5，留空不限"
                         onChange={(e) => setBudgetLocal(e.target.value)} />
                  <button className="save-btn" onClick={saveBudget}>保存</button>
                </div>
              </div>
              <div className="settings-row">
                <div>
                  <div className="label">按任务路由（只读）</div>
                  <div className="desc readonly-list">
                    {Object.entries(config.routing).map(([task, profile]) => (
                      <div key={task}><b>{task}</b> → {profile}</div>
                    ))}
                  </div>
                </div>
                <div className="control" />
              </div>
              <div className="settings-row">
                <div>
                  <div className="label">权限门名单（只读）</div>
                  <div className="desc readonly-list">
                    执行前确认：{config.permissions.confirm_tools.length ? config.permissions.confirm_tools.join('、') : '（无）'}<br />
                    无人值守禁用：{config.permissions.unattended_deny_tools.length ? config.permissions.unattended_deny_tools.join('、') : '（无）'}
                  </div>
                </div>
                <div className="control" />
              </div>
            </>
          )}

          {section === 'usage' && <UsageSection />}

          {section === 'skills' && (
            <>
              <h2>技能</h2>
              <div className="settings-row">
                <div>
                  <div className="label">ppt-outline</div>
                  <div className="desc">为比赛生成 PPT 大纲（/生成 命令使用）。</div>
                </div>
              </div>
              <div className="settings-row">
                <div>
                  <div className="label">proposal</div>
                  <div className="desc">生成参赛计划书。</div>
                </div>
              </div>
              <div className="settings-row">
                <div>
                  <div className="label">study-path</div>
                  <div className="desc">生成带真实引用的备考学习路径（/备考 命令使用）。</div>
                </div>
              </div>
            </>
          )}

          {['privacy', 'cowork', 'importexport', 'system', 'developer', 'connectors', 'plugins']
            .includes(section) && (
            <>
              <h2>{NAV.flatMap((g) => g.items).find((i) => i.key === section)?.label}</h2>
              <div className="models-empty">此分区为界面复刻的占位——本项目暂无对应功能。</div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function UsageSection() {
  const [data, setData] = useState(null)
  useEffect(() => { api.usageSummary('all').then(setData).catch(() => {}) }, [])
  if (!data) return <><h2>用量</h2><div className="models-empty">加载中…</div></>
  return (
    <>
      <h2>用量</h2>
      <div className="settings-row">
        <div>
          <div className="label">全部用量的真实数字</div>
          <div className="desc readonly-list">
            会话 {data.sessions} 个 ｜ 消息 {data.messages} 条 ｜
            总 token {data.total_tokens.toLocaleString()} ｜ 活跃 {data.active_days} 天
            <br />{data.fun_fact}
          </div>
        </div>
      </div>
    </>
  )
}

// Settings 里的代码 diff 预览（对应截图 5 的装饰块，内容固定）
function CodePreview({ dark }) {
  return (
    <div className="diff-code" style={dark ? { background: '#161615' } : undefined}>
      <div><span className="ln">1</span><span className="kw">function</span> <span className="fn">greet</span>(name: <span className="kw">string</span>) {'{'}</div>
      <div className="del"><span className="ln">2</span>-  <span className="kw">return</span> <span className="str">"Hello, "</span> + name;</div>
      <div className="add"><span className="ln">2</span>+  <span className="kw">return</span> <span className="str">`Hello, {'${'}name{'}'}!`</span>;</div>
      <div><span className="ln">3</span>{'}'}</div>
    </div>
  )
}
