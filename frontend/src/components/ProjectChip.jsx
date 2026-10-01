import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

// 项目选择 chip + popover（对应截图 2）：搜索项目 / 选中打勾 / 新建项目 /
// 不在项目中工作。选中后，该 tab 发出的首条消息会自动把会话绑到项目。
export default function ProjectChip({ selected, onSelect, sessionReady }) {
  const [open, setOpen] = useState(false)
  const [projects, setProjects] = useState([])
  const [query, setQuery] = useState('')
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const wrapRef = useRef(null)

  useEffect(() => {
    api.projects().then((r) => setProjects(r.projects)).catch(() => {})
  }, [open])

  useEffect(() => {
    const onDoc = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const matches = projects.filter((p) => p.name.toLowerCase().includes(query.toLowerCase()))

  const choose = (p) => { onSelect(p); setOpen(false) }
  const create = async () => {
    if (!newName.trim()) return
    try {
      const p = await api.createProject(newName.trim())
      setProjects((ps) => [{ key: p.key, name: p.name, deadline: null }, ...ps])
      onSelect(p)
    } catch { /* 新建失败保持面板开着 */ }
    setNewName(''); setCreating(false)
  }

  return (
    <div className="chip-wrap" ref={wrapRef} style={{ position: 'relative' }}>
      <button className={`pill-btn ${selected ? 'pill-active' : ''}`}
              onClick={() => setOpen(!open)}>
        <span>▤</span> {selected ? selected.name : '项目'}
      </button>
      {open && (
        <div className="cmd-palette project-palette">
          <input className="palette-search" placeholder="搜索项目"
                 value={query} onChange={(e) => setQuery(e.target.value)}
                 onKeyDown={(e) => e.key === 'Escape' && setOpen(false)} />
          <div className="palette-list">
            {matches.map((p) => (
              <button key={p.key} className="cmd-item" onClick={() => choose(p)}>
                <span>▤</span> {p.name}
                <span className="desc">{p.sessions ? `${p.sessions} 会话` : ''}</span>
                {selected?.key === p.key && <span className="check">✓</span>}
              </button>
            ))}
            {!matches.length && !creating && (
              <div style={{ padding: '8px 14px', fontSize: 12.5, color: 'var(--text-faint)' }}>
                没有匹配的项目
              </div>
            )}
          </div>
          <div className="menu-sep" />
          {creating ? (
            <div style={{ padding: '6px 10px', display: 'flex', gap: 6 }}>
              <input className="palette-search" autoFocus placeholder="项目名称"
                     value={newName}
                     onChange={(e) => setNewName(e.target.value)}
                     onKeyDown={(e) => e.key === 'Enter' && create()} />
              <button className="save-btn" style={{ padding: '4px 10px' }}
                      onClick={create}>建</button>
            </div>
          ) : (
            <button className="cmd-item" onClick={() => setCreating(true)}>
              <span>＋</span> 新建项目
            </button>
          )}
          <div className="menu-sep" />
          <button className="cmd-item" onClick={() => { onSelect(null); setOpen(false) }}>
            <span>✕</span> 不在项目中工作
          </button>
        </div>
      )}
    </div>
  )
}
