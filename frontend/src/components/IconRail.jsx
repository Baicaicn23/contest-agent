// 左侧窄图标栏（Codex 式）：全应用的一级导航。
// 首页/历史(统计)/定时/更多 + 底部下载(占位)/设置。
export default function IconRail({ active, onNavigate, onOpenSettings }) {
  const items = [
    { key: 'home', icon: null, label: '工作台' },
    { key: 'stats', icon: null, label: '统计' },
    { key: 'deadlines', icon: null, label: '日程' },
    { key: 'more', icon: null, label: '更多' },
  ]
  return (
    <nav className="icon-rail">
      <div className="rail-top">
        {items.map((item) => (
          <button key={item.key}
                  className={`rail-btn ${active === item.key ? 'active' : ''}`}
                  title={item.label}
                  onClick={() => item.key !== 'more' && onNavigate(item.key)}>
            {item.label.slice(0, 2)}
          </button>
        ))}
      </div>
      <div className="rail-bottom">
        <button className="rail-btn rail-txt" title="下载（视觉占位）">下载</button>
        <button className="rail-btn rail-txt" title="设置" onClick={onOpenSettings}>设置</button>
      </div>
    </nav>
  )
}
