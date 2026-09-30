// 消息渲染：把文本里的轻量 Markdown（**粗体**、`行内码`）转成 React 元素。
// 刻意不用 dangerouslySetInnerHTML——逐段解析成元素，天然免疫注入。
export function renderInline(text, keyPrefix = '') {
  const parts = []
  let rest = text
  let key = 0
  // 先按行内码切（`x`），再在非代码段里处理 **粗体**
  const codeSplit = rest.split(/(`[^`]+`)/g)
  codeSplit.forEach((seg, si) => {
    if (seg.startsWith('`') && seg.endsWith('`') && seg.length > 2) {
      parts.push(<code className="inline-code" key={`${keyPrefix}-c${si}`}>{seg.slice(1, -1)}</code>)
      return
    }
    const boldSplit = seg.split(/(\*\*[^*]+\*\*)/g)
    boldSplit.forEach((b, bi) => {
      if (b.startsWith('**') && b.endsWith('**') && b.length > 4) {
        parts.push(<strong key={`${keyPrefix}-${si}-${bi}`}>{b.slice(2, -2)}</strong>)
      } else if (b) {
        parts.push(<span key={`${keyPrefix}-${si}-${bi}`}>{b}</span>)
      }
    })
  })
  return parts
}

// 消息气泡/正文：user 用气泡；assistant 平铺正文（含轻量 Markdown）。
export default function MsgBubble({ role, content, time, error = false }) {
  const isUser = role === 'user'
  const lines = String(content).split('\n')

  const body = (
    <div className={isUser ? 'bubble' : 'content'} style={error ? { color: '#c0503a' } : undefined}>
      {lines.map((line, i) => {
        const bullet = line.match(/^\s*[-•]\s+(.*)$/)
        const numbered = line.match(/^\s*(\d+)\.\s+(.*)$/)
        if (bullet) {
          return <div key={i} style={{ paddingLeft: 14 }}>• {renderInline(bullet[1], `${i}-`)}</div>
        }
        if (numbered) {
          return <div key={i} style={{ paddingLeft: 14 }}>{numbered[1]}. {renderInline(numbered[2], `${i}-`)}</div>
        }
        return <div key={i}>{renderInline(line, `${i}-`) || '\u00A0'}</div>
      })}
    </div>
  )

  return (
    <div className={`msg ${isUser ? 'user' : 'assistant'}`}>
      {body}
      {time && (
        <div className="meta">
          <span>{time}</span>
        </div>
      )}
    </div>
  )
}

// 工具调用的可折叠块（回放 agent 任务时出现，对应"透明度底线"）。
export function ToolBlock({ name, args, result }) {
  const argText = Object.entries(args || {})
    .map(([k, v]) => `${k}=${String(v).slice(0, 80)}`)
    .join(', ')
  return (
    <details className="tool-block">
      <summary>🛠 工具调用：{name || '未知'}({argText})</summary>
      <div className="tool-body">{String(result || '').slice(0, 600)}</div>
    </details>
  )
}
