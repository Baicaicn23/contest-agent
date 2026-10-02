// 消息渲染：把轻量 Markdown 解析成 React 元素（M10 升级）。
// 块级：fenced 代码块 / 表格 / 标题 / 引用 / 水平线；行内：粗体、行内码；
// 行级：bullet / ordered 列表。
// 刻意不引 Markdown 库、不走 dangerouslySetInnerHTML——逐段解析成
// React 元素天然免疫注入；流式渲染中未闭合的 ``` 也容错（当代码块收尾）。
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

// ---------- 块级解析：content → [{type, ...}] ----------

function parseBlocks(text) {
  const lines = String(text).split('\n')
  const blocks = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]

    // fenced 代码块：``` 开头（可带语言名）。未闭合 = 吃到文末（流式中途的正常形态）
    if (/^\s*```/.test(line)) {
      const lang = line.replace(/^\s*```/, '').trim()
      const buf = []
      i += 1
      while (i < lines.length && !/^\s*```/.test(lines[i])) {
        buf.push(lines[i]); i += 1
      }
      i += 1   // 跳过闭合 ```；没有闭合时这里越界也无妨
      blocks.push({ type: 'code', lang, text: buf.join('\n') })
      continue
    }

    // 表格：连续的 | a | b | 行（下一道工序再区分表头/分隔行）
    if (/^\s*\|.+\|\s*$/.test(line)) {
      const rows = []
      while (i < lines.length && /^\s*\|.+\|\s*$/.test(lines[i])) {
        rows.push(lines[i]); i += 1
      }
      blocks.push({ type: 'table', rows })
      continue
    }

    // 标题 #/##/###（消息里最多三级）
    const heading = line.match(/^\s*(#{1,3})\s+(.*)$/)
    if (heading) {
      blocks.push({ type: 'heading', level: heading[1].length, text: heading[2] })
      i += 1; continue
    }

    // 水平线
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
      blocks.push({ type: 'hr' }); i += 1; continue
    }

    // 引用：连续的 > 行
    if (/^\s*>\s?/.test(line)) {
      const buf = []
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*>\s?/, '')); i += 1
      }
      blocks.push({ type: 'quote', text: buf.join('\n') })
      continue
    }

    // 普通文本段：连续的非空、非块级行；空行 = 段落分隔
    const buf = []
    while (i < lines.length && lines[i].trim() !== ''
           && !/^\s*(```|\||#{1,3}\s|>|-{3,}|\*{3,})/.test(lines[i])) {
      buf.push(lines[i]); i += 1
    }
    if (buf.length) blocks.push({ type: 'text', lines: buf })
    else i += 1   // 空行
  }
  return blocks
}

// 普通文本段：逐行处理 bullet / ordered / 普通（沿袭原实现）
function renderTextLines(lines, keyPrefix) {
  return lines.map((line, i) => {
    const bullet = line.match(/^\s*[-•]\s+(.*)$/)
    const numbered = line.match(/^\s*(\d+)\.\s+(.*)$/)
    if (bullet) {
      return <div key={`${keyPrefix}${i}`} style={{ paddingLeft: 14 }}>• {renderInline(bullet[1], `${keyPrefix}${i}-`)}</div>
    }
    if (numbered) {
      return <div key={`${keyPrefix}${i}`} style={{ paddingLeft: 14 }}>{numbered[1]}. {renderInline(numbered[2], `${keyPrefix}${i}-`)}</div>
    }
    return <div key={`${keyPrefix}${i}`}>{renderInline(line, `${keyPrefix}${i}-`) || '\u00A0'}</div>
  })
}

// 表格渲染：第二行是 |---|:---:| 分隔行时视为表头；单元格复用行内渲染
function renderTable(rows, keyPrefix) {
  const cells = (row) => row.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim())
  const header = cells(rows[0])
  const hasSep = rows.length >= 2 && /^[\s:|-]+$/.test(rows[1])
  const bodyRows = rows.slice(hasSep ? 2 : 1)
  return (
    <div className="md-table-wrap" key={keyPrefix}>
      <table className="md-table">
        <thead>
          <tr>{header.map((c, j) => <th key={j}>{renderInline(c, `${keyPrefix}h${j}-`)}</th>)}</tr>
        </thead>
        <tbody>
          {bodyRows.map((row, ri) => {
            const cs = cells(row)
            return (
              <tr key={ri}>
                {header.map((_, j) => <td key={j}>{renderInline(cs[j] ?? '', `${keyPrefix}${ri}-${j}-`)}</td>)}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// 消息气泡/正文：user 用气泡；assistant 平铺正文（块级 Markdown）。
export default function MsgBubble({ role, content, time, error = false }) {
  const isUser = role === 'user'
  const blocks = parseBlocks(content)

  const body = (
    <div className={isUser ? 'bubble' : 'content'} style={error ? { color: '#c0503a' } : undefined}>
      {blocks.map((b, i) => {
        switch (b.type) {
          case 'code':
            return (
              <pre key={i} className="md-code">
                {b.lang && <span className="md-code-lang">{b.lang}</span>}
                <code>{b.text}</code>
              </pre>
            )
          case 'table':
            return renderTable(b.rows, `t${i}-`)
          case 'heading': {
            const Tag = `h${Math.min(b.level + 2, 5)}`   // # → h3，消息里不抢页面标题
            return <Tag key={i} className={`md-h md-h${b.level}`}>{renderInline(b.text, `h${i}-`)}</Tag>
          }
          case 'hr':
            return <hr key={i} className="md-hr" />
          case 'quote':
            return (
              <blockquote key={i} className="md-quote">
                {b.text.split('\n').map((l, j) => <div key={j}>{renderInline(l, `q${i}-${j}-`) || '\u00A0'}</div>)}
              </blockquote>
            )
          default:
            return <div key={i} className="md-text">{renderTextLines(b.lines, `x${i}-`)}</div>
        }
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
      <summary>工具调用：{name || '未知'}({argText})</summary>
      <div className="tool-body">{String(result || '').slice(0, 600)}</div>
    </details>
  )
}
