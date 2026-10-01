// 左侧窄图标栏（Codex 式）：全应用的一级导航。
// 首页/历史(统计)/定时/更多 + 底部下载(占位)/设置。
export default function IconRail({ active, onNavigate, onOpenSettings }) {
  const items = [
    { key: 'home', icon: '⌂', title: '工作台' },
    { key: 'stats', icon: '◔', title: '统计' },
    { key: 'deadlines', icon: '⏰', title: '截止日程' },
    { key: 'more', icon: '…', title: '更多（视觉占位）' },
  ]
  return (
    <nav className="icon-rail">
      <div className="rail-top">
        {items.map((item) => (
          <button key={item.key}
                  className={`rail-btn ${active === item.key ? 'active' : ''}`}
                  title={item.title}
                  onClick={() => item.key !== 'more' && onNavigate(item.key)}>
            {item.icon}
          </button>
        ))}
      </div>
      <div className="rail-bottom">
        <button className="rail-btn" title="下载（视觉占位）">⬇</button>
        <button className="rail-btn" title="设置" onClick={onOpenSettings}>⚙</button>
      </div>
    </nav>
  )
}
