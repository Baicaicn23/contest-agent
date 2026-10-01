import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

// 右侧工具坞（M7，图二需求）：可开合的悬浮面板，两个 tab——
//   文件树：output/ 的真实目录树（GET /api/tree），点文件预览前 2000 字；
//   终端：  在项目根目录执行命令（POST /api/terminal，30s 超时 + 10KB 截断在服务端）。
// 关闭钮左上（M6 规范）+ Esc 关闭；面板本体从右滑入（panel-in-right 动画）。
export default function RightDock({ onClose }) {
  const [tab, setTab] = useState('tree')
  const [tree, setTree] = useState(null)
  const [preview, setPreview] = useState(null)

  useEffect(() => {
    api.tree().then(setTree).catch(() => setTree({ root: 'output', children: [] }))
  }, [])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const openFile = async (path) => {
    try {
      setPreview(await api.fileContent(path))
    } catch (e) {
      setPreview({ name: path, content: `注意：${e.message}` })
    }
  }

  return (
    <aside className="tool-panel dock">
      <button className="icon-btn close-btn-tl" title="关闭（Esc）" onClick={onClose}>✕</button>
      <div className="tool-panel-head">
        <div className="dock-tabs">
          <button className={`dock-tab ${tab === 'tree' ? 'active' : ''}`}
                  onClick={() => setTab('tree')}>文件树</button>
          <button className={`dock-tab ${tab === 'term' ? 'active' : ''}`}
                  onClick={() => setTab('term')}>终端</button>
        </div>
      </div>

      {tab === 'tree' && (
        <div className="dock-tree">
          <div className="tool-panel-section">output/（生成产物）</div>
          <div className="dock-tree-scroll">
            {tree?.children?.map((node) => (
              <TreeNode key={node.name} node={node} path={node.name} depth={0}
                        onPreview={openFile} />
            ))}
            {tree && !tree.children.length && (
              <div className="tree-empty">还没有产物。生成材料或跑一次报告就会出现。</div>
            )}
          </div>
          {preview && (
            <div className="dock-preview">
              <div className="dock-preview-head">
                <span>{preview.name}</span>
                <button className="icon-btn" title="收起预览"
                        onClick={() => setPreview(null)}>✕</button>
              </div>
              <pre>{preview.content}</pre>
            </div>
          )}
        </div>
      )}

      {tab === 'term' && <TerminalPane />}
    </aside>
  )
}

// 文件树节点：目录可折叠（默认展开），文件点击预览。
function TreeNode({ node, path, depth, onPreview }) {
  const [open, setOpen] = useState(depth < 2)   // 前两层默认展开
  if (node.type === 'file') {
    return (
      <button className="tree-file" style={{ paddingLeft: 10 + depth * 14 }}
              title={`预览 ${path}`}
              onClick={() => onPreview(path)}>
        <span className="tree-file-mark" /> {node.name}
      </button>
    )
  }
  return (
    <>
      <button className="tree-dir" style={{ paddingLeft: 6 + depth * 14 }}
              onClick={() => setOpen(!open)}>
        <span className={`tree-chev ${open ? 'down' : ''}`}>▸</span> {node.name}
      </button>
      <div className={`tree-kids ${open ? 'open' : ''}`}>
        <div className="tree-kids-inner">
          {node.children.map((child) => (
            <TreeNode key={child.name} node={child} path={`${path}/${child.name}`}
                      depth={depth + 1} onPreview={onPreview} />
          ))}
        </div>
      </div>
    </>
  )
}

// 终端面板：命令历史 + 输入行。历史只存在前端内存（刷新即清，像一次性会话）。
function TerminalPane() {
  const [lines, setLines] = useState([])
  const [input, setInput] = useState('')
  const [running, setRunning] = useState(false)
  const scrollRef = useRef(null)

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [lines])

  const run = async () => {
    const command = input.trim()
    if (!command || running) return
    setInput('')
    setRunning(true)
    // 先放一条"运行中"占位，完成后原位替换成结果（避免占位+结果两行重复）
    setLines((ls) => [...ls, { cmd: command, pending: true }])
    try {
      const r = await api.terminal(command)
      setLines((ls) => {
        const copy = [...ls]
        copy[copy.length - 1] = { cmd: command, output: r.output, exit: r.exit_code, ms: r.duration_ms }
        return copy
      })
    } catch (e) {
      setLines((ls) => {
        const copy = [...ls]
        copy[copy.length - 1] = { cmd: command, output: `注意：${e.message}`, exit: -1 }
        return copy
      })
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="dock-term">
      <div className="dock-term-hint">项目根目录执行 · 30 秒超时 · 输出截断 10KB</div>
      <div className="dock-term-scroll" ref={scrollRef}>
        {lines.length === 0 && (
          <div className="tree-empty">输入命令回车执行，比如：ls output、uv run pytest -q</div>
        )}
        {lines.map((l, i) => (
          <div key={i} className="term-entry">
            <div className="term-cmd"><span className="term-dollar">$</span> {l.cmd}</div>
            {l.pending && <div className="term-meta">运行中…</div>}
            {l.output != null && (
              <pre className={`term-out ${l.exit !== 0 ? 'err' : ''}`}>{l.output || '（无输出）'}</pre>
            )}
            {l.ms != null && <div className="term-meta">exit {l.exit} · {l.ms}ms</div>}
          </div>
        ))}
      </div>
      <div className="dock-term-input">
        <span className="term-dollar">$</span>
        <input value={input} placeholder="输入命令…"
               onChange={(e) => setInput(e.target.value)}
               onKeyDown={(e) => { if (e.key === 'Enter') run() }} />
      </div>
    </div>
  )
}
