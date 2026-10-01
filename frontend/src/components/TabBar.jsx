import { useState } from 'react'

// 聊天标签页条（Codex 式）：多个并行会话，各自独立；＋ 新开一个。
// tabs: [{key, title, sessionId}]; activeKey 当前 tab。
export default function TabBar({ tabs, activeKey, onSelect, onClose, onNew }) {
  return (
    <div className="tab-bar">
      {tabs.map((t) => (
        <div key={t.key}
             className={`app-tab ${t.key === activeKey ? 'active' : ''}`}
             onClick={() => onSelect(t.key)}>
          <span className="tab-title">{t.title}</span>
          {tabs.length > 1 && (
            <button className="tab-close"
                    onClick={(e) => { e.stopPropagation(); onClose(t.key) }}>✕</button>
          )}
        </div>
      ))}
      <button className="tab-add" title="新标签页" onClick={onNew}>＋</button>
    </div>
  )
}

// 多标签状态管理的小工具：App 里用 useTabs() 驱动 TabBar。
export function useTabs(initial) {
  const [tabs, setTabs] = useState([initial])
  const [activeKey, setActiveKey] = useState(initial.key)

  const openTab = (tab) => {
    setTabs((ts) => (ts.some((t) => t.key === tab.key) ? ts : [...ts, tab]))
    setActiveKey(tab.key)
  }
  const closeTab = (key) => {
    setTabs((ts) => {
      const rest = ts.filter((t) => t.key !== key)
      if (key === activeKey && rest.length) setActiveKey(rest[rest.length - 1].key)
      if (!rest.length) {
        const fresh = { key: `tab-${Date.now()}`, title: '新聊天', sessionId: null }
        setTabs([fresh]); setActiveKey(fresh.key)
      }
      return rest
    })
  }
  return { tabs, activeKey, openTab, closeTab, setActiveKey }
}
