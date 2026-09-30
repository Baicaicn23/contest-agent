import { useState } from 'react'
import Logo from './Logo.jsx'

// 左下角的用户弹出菜单（对应截图 4 的两层面板）。
// 真实可用的入口：设置；其余为视觉复刻（项目没有账号体系和在线文档）。
export default function UserMenu({ onOpenSettings }) {
  const [learnMoreOpen, setLearnMoreOpen] = useState(false)
  const repoUrl = 'https://github.com/Baicaicn23/contest-agent'

  return (
    <div className="popover" style={{ left: 8, bottom: 52 }} onClick={(e) => e.stopPropagation()}>
      <div className="menu-user">
        <div className="name">momo</div>
        <div className="sub">本地模式</div>
      </div>
      <div className="menu-sep" />
      <button className="menu-item" onClick={onOpenSettings}>
        <span className="icon">⚙</span> 设置
        <span className="shortcut">⌘,</span>
      </button>
      <button className="menu-item" onClick={onOpenSettings}>
        <span className="icon">🌐</span> 语言
      </button>
      <button className="menu-item" onClick={onOpenSettings}>
        <span className="icon">⚙</span> 推理配置
      </button>
      <div className="menu-sep" />
      <a className="menu-item" href={`${repoUrl}/blob/main/CHANGELOG.md`} target="_blank" rel="noreferrer">
        <span className="icon">📋</span> 查看更新日志
      </a>
      <button className="menu-item"
              onMouseEnter={() => setLearnMoreOpen(true)}
              onClick={() => setLearnMoreOpen(!learnMoreOpen)}>
        <span className="icon">ℹ️</span> 了解更多
        <span className="chev">›</span>
      </button>
      <div className="menu-sep" />
      <button className="menu-item" title="本项目是本地单机应用，无需登录">
        <span className="icon">↪</span> 退出登录
      </button>

      {learnMoreOpen && (
        <div className="popover" style={{ left: 'calc(100% + 6px)', bottom: 150, minWidth: 250 }}>
          <a className="menu-item" href={repoUrl} target="_blank" rel="noreferrer">
            关于本项目 <span className="chev">↗</span>
          </a>
          <a className="menu-item" href={`${repoUrl}#-功能特性`} target="_blank" rel="noreferrer">
            功能一览 <span className="chev">↗</span>
          </a>
          <a className="menu-item" href={`${repoUrl}#-快速开始`} target="_blank" rel="noreferrer">
            使用教程 <span className="chev">↗</span>
          </a>
          <div className="menu-sep" />
          <button className="menu-item" onClick={onOpenSettings}>
            键盘快捷键 <span className="shortcut">⌘/</span>
          </button>
        </div>
      )}
    </div>
  )
}

export function UserBox({ onOpenSettings }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="user-box">
      {open && <UserMenu onOpenSettings={() => { setOpen(false); onOpenSettings() }} />}
      <button className="user-box-btn" onClick={() => setOpen(!open)}>
        <span className="user-logo"><Logo size={20} /></span>
        <span className="who">
          momo <span className="sub">· 本地</span>
        </span>
        <span className="chev">⌄</span>
      </button>
    </div>
  )
}
