import { useEffect, useState } from 'react'
import { api } from '../api.js'

// 右侧工具分屏面板（对应截图 3 的"工具/文件"）：output/ 真实文件列表 + 点开预览。
export default function ToolPanel({ onClose }) {
  const [files, setFiles] = useState([])
  const [preview, setPreview] = useState(null)

  useEffect(() => {
    api.files().then((r) => setFiles(r.files)).catch(() => {})
  }, [])

  const open = async (name) => {
    try {
      const r = await api.fileContent(name)
      setPreview(r)
    } catch (e) {
      setPreview({ name, content: `注意：${e.message}` })
    }
  }

  // Esc 关闭：焦点停在文件列表按钮上时按 Esc 也要能收起面板。
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <aside className="tool-panel">
      <div className="tool-panel-head">
        <button className="icon-btn close-btn-tl" title="关闭（Esc）" onClick={onClose}>✕</button>
        <span style={{ fontWeight: 600, fontSize: 14 }}>工具</span>
      </div>
      <div className="tool-panel-section">文件（output/）</div>
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {files.length === 0 && (
          <div style={{ padding: 10, fontSize: 13, color: 'var(--text-dim)' }}>
            还没有产物。生成材料或跑一次报告就会出现。
          </div>
        )}
        {files.map((f) => (
          <button key={f.name} className={`side-item ${preview?.name === f.name ? 'active' : ''}`}
                  onClick={() => open(f.name)}
                  style={{ fontSize: 12.5 }}>
            <span className="title">{f.name}</span>
          </button>
        ))}
      </div>
      {preview && (
        <div style={{ borderTop: '1px solid var(--border-soft)', padding: 10, maxHeight: '45%', overflow: 'auto' }}>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>{preview.name}</div>
          <pre style={{ fontSize: 11.5, whiteSpace: 'pre-wrap', wordBreak: 'break-all',
                        color: 'var(--text-dim)', margin: 0 }}>{preview.content}</pre>
        </div>
      )}
    </aside>
  )
}
