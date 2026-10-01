import { useEffect, useState } from 'react'
import { api } from '../api.js'
import UsageCard from '../components/UsageCard.jsx'

// 设置全页（对应截图 4）：左导航分组 + 右面板卡片。
// 真实生效：权限两卡（完全访问总闸，写 config）、通用（模型档案/预算）、
// 外观（主题/字号）、用量（真台账）。其余分区为视觉占位。
const NAV = [
  { group: '个人', items: [
    { key: 'general', icon: '', label: '常规' },
    { key: 'import', icon: '', label: '导入', stub: true },
    { key: 'appearance', icon: '', label: '外观' },
    { key: 'voice', icon: '', label: '语音', stub: true },
    { key: 'config', icon: '', label: '配置' },
    { key: 'personalize', icon: '', label: '个性化', stub: true },
    { key: 'mini', icon: '', label: 'Mini 与虚拟宠物', stub: true },
    { key: 'shortcuts', icon: '', label: '键盘快捷键', stub: true },
  ]},
  { group: '集成', items: [
    { key: 'plugins', icon: '', label: '插件' },
    { key: 'computer', icon: '', label: '电脑操控', stub: true },
    { key: 'browser', icon: '', label: '浏览器', stub: true },
  ]},
  { group: '编码', items: [
    { key: 'hooks', icon: '', label: '钩子', stub: true },
    { key: 'git', icon: '', label: 'Git' },
    { key: 'env', icon: '', label: '环境', stub: true },
  ]},
]

export default function SettingsPage({ config, onConfigChange, theme, setTheme,
                                        fontSize, setFontSize, accessFull,
                                        onToggleAccess, onClose, onOpenPlugins }) {
  const [section, setSection] = useState('general')
  const [budget, setBudgetLocal] = useState('')
  const [hint, setHint] = useState('')

  useEffect(() => setBudgetLocal(config?.budget_per_task_yuan ?? ''), [config])
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const saveBudget = async () => {
    const v = String(budget).trim()
    const yuan = v === '' || v === 'null' ? null : Number(v)
    if (yuan !== null && (Number.isNaN(yuan) || yuan < 0)) {
      setHint('预算要是非负数字，或留空表示不限'); return
    }
    try { await api.setBudget(yuan); setHint('已保存 ✓'); onConfigChange() }
    catch (e) { setHint(e.message) }
  }

  return (
    <div className="settings-page">
      <div className="settings-page-head">
        {/* 关闭钮在 App 壳层的 fullpage-close（左上角统一规格），这里不再放第二个 */}
        <h1>设置</h1>
      </div>
      <div className="settings-page-body">
        <div className="settings-nav page">
          <input className="search" placeholder="搜索" />
          {NAV.map((g) => (
            <div key={g.group}>
              <div className="group-label">{g.group}</div>
              {g.items.map((item) => (
                <button key={item.key}
                        className={`side-item ${section === item.key ? 'active' : ''}`}
                        onClick={() => setSection(item.key)}>
                  <span className="icon">{item.icon}</span> {item.label}
                </button>
              ))}
            </div>
          ))}
        </div>

        <div className="settings-body">
          {section === 'general' && config && (
            <>
              <h1 className="sec-title">常规</h1>
              <div className="card-block">
                <div className="card-title">权限</div>
                <div className="settings-row">
                  <div>
                    <div className="label">默认权限</div>
                    <div className="desc">默认情况下，助手可以读取和编辑其工作空间中的文件。需要时，它可以请求额外访问权限。</div>
                  </div>
                  <div className="control">
                    <Toggle on={!config.access_full}
                            onChange={(on) => onToggleAccess(!on)} />
                  </div>
                </div>
                <div className="settings-row">
                  <div>
                    <div className="label">完全访问权限</div>
                    <div className="desc">开启后，它无需你的批准即可执行全部工具，并访问网络。这会显著增加费用与误操作的风险。</div>
                  </div>
                  <div className="control">
                    <Toggle on={config.access_full}
                            onChange={(on) => onToggleAccess(on)} />
                  </div>
                </div>
              </div>
              <div className="card-title" style={{ marginTop: 26 }}>常规</div>
              <div className="card-block">
                <div className="settings-row">
                  <div>
                    <div className="label">单任务预算上限（元）</div>
                    <div className="desc">一次任务花费达到上限就熔断；留空不限。{hint && <span style={{ color: 'var(--accent)' }}> {hint}</span>}</div>
                  </div>
                  <div className="control" style={{ display: 'flex', gap: 8 }}>
                    <input className="text-input" value={budget} placeholder="留空不限"
                           onChange={(e) => setBudgetLocal(e.target.value)} />
                    <button className="save-btn" onClick={saveBudget}>保存</button>
                  </div>
                </div>
                <div className="settings-row">
                  <div>
                    <div className="label">模型档案</div>
                    <div className="desc">当前生效：{config.active_model}。切换写回 config.yaml，CLI 同样生效。</div>
                  </div>
                  <div className="control">
                    <select className="select-box" value={config.active_model}
                            onChange={async (e) => {
                              await api.switchModel(e.target.value); onConfigChange()
                            }}>
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
                    <div className="label">输出目录</div>
                    <div className="desc">生成的材料与报告默认存放的位置。</div>
                  </div>
                  <div className="control mono">output/</div>
                </div>
                <div className="settings-row">
                  <div>
                    <div className="label">语言</div>
                    <div className="desc">应用界面语言</div>
                  </div>
                  <div className="control">
                    <select className="select-box"><option>自动检测</option><option>中文</option></select>
                  </div>
                </div>
              </div>
            </>
          )}

          {section === 'appearance' && (
            <>
              <h1 className="sec-title">外观</h1>
              <div className="settings-row">
                <div>
                  <div className="label">主题</div>
                  <div className="desc">亮色 / 暗色（立即生效并记住）。</div>
                </div>
                <div className="control">
                  <select className="select-box" value={theme}
                          onChange={(e) => setTheme(e.target.value)}>
                    <option value="light">亮色</option>
                    <option value="dark">暗色</option>
                  </select>
                </div>
              </div>
              <div className="settings-row">
                <div>
                  <div className="label">正文字号</div>
                  <div className="desc">会话正文的文字大小。</div>
                </div>
                <div className="control seg-group">
                  {[['small', '小'], ['medium', '中'], ['large', '大']].map(([k, l]) => (
                    <button key={k} className={fontSize === k ? 'active' : ''}
                            onClick={() => setFontSize(k)}>{l}</button>
                  ))}
                </div>
              </div>
            </>
          )}

          {section === 'usage' && (
            <>
              <h1 className="sec-title">用量</h1>
              <UsageCard />
            </>
          )}

          {section === 'git' && config && (
            <>
              <h1 className="sec-title">Git</h1>
              <div className="settings-row">
                <div>
                  <div className="label">按任务路由（只读）</div>
                  <div className="desc readonly-list">
                    {Object.entries(config.routing).map(([task, profile]) => (
                      <div key={task}><b>{task}</b> → {profile}</div>
                    ))}
                  </div>
                </div>
              </div>
              <div className="settings-row">
                <div>
                  <div className="label">权限门名单（只读）</div>
                  <div className="desc readonly-list">
                    执行前确认：{config.permissions.confirm_tools.length ? config.permissions.confirm_tools.join('、') : '（无）'}<br />
                    无人值守禁用：{config.permissions.unattended_deny_tools.length ? config.permissions.unattended_deny_tools.join('、') : '（无）'}
                  </div>
                </div>
              </div>
            </>
          )}

          {section === 'plugins' && (
            <>
              <h1 className="sec-title">插件</h1>
              <div className="settings-row">
                <div>
                  <div className="label">能力插件管理在 Customize 页</div>
                  <div className="desc">截止守望 / 评测 / 盯梢 / PPT 导出 / 推送通道的安装开关都在那边（真实写回 config.yaml）。</div>
                </div>
                <div className="control">
                  <button className="save-btn" onClick={() => onOpenPlugins()}>前往插件市场</button>
                </div>
              </div>
            </>
          )}

          {['import', 'voice', 'personalize', 'mini', 'shortcuts', 'computer', 'browser', 'env']
            .includes(section) && (
            <>
              <h1 className="sec-title">{NAV.flatMap((g) => g.items).find((i) => i.key === section)?.label}</h1>
              <div className="models-empty">此分区为界面复刻的占位——本项目暂无对应功能。</div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// 橙色开关（对应截图 4 的 toggle 控件）
export function Toggle({ on, onChange }) {
  return (
    <button className={`toggle ${on ? 'on' : ''}`} onClick={() => onChange(!on)}
            role="switch" aria-checked={on}>
      <span className="knob" />
    </button>
  )
}
