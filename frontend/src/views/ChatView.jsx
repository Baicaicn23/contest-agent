import { useEffect, useRef, useState } from 'react'
import { api, streamChat } from '../api.js'
import ChatInput from '../components/ChatInput.jsx'
import MsgBubble, { ToolBlock } from '../components/MsgBubble.jsx'

// 会话视图：两个用途共用一个组件——
// 1) 自由聊天（新会话或继续 chat 会话）：逐字流式；
// 2) 轨迹回放（点侧栏的识别/生成等任务会话）：把 M2 存档的事件翻译成消息流，只读。
// 翻译规则：user_input → 右气泡；result → 助手正文；tool_call → 可折叠块；
// error → 红色助手消息。task_type 是 chat 的会话可以继续聊，其余只读。
export default function ChatView({ sessionId, title, initialUser, initialAssistant,
                                   onSessionsChanged, bindProjectKey, projectName,
                                   onCloseTab, className = '' }) {
  const [messages, setMessages] = useState([])   // {role, content, time?, tool?}
  const [chatSessionId, setChatSessionId] = useState(sessionId)  // null = 首发后由服务端分配
  const [taskType, setTaskType] = useState(sessionId ? null : 'chat')
  const [loaded, setLoaded] = useState(sessionId == null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const scrollRef = useRef(null)
  const sentInitial = useRef(false)

  const isReplay = sessionId != null && taskType !== 'chat'

  // 回放/续聊：加载历史会话的事件
  useEffect(() => {
    if (sessionId == null) return
    api.sessionDetail(sessionId).then(({ session, events }) => {
      setTaskType(session.task_type)
      setMessages(eventsToMessages(events))
      setLoaded(true)
    }).catch((e) => { setError(e.message); setLoaded(true) })
  }, [sessionId])

  // 首页带话进来：assistantText 有值 = 命令结果直接铺；否则当作第一条用户消息自动发送
  useEffect(() => {
    if (sessionId != null || sentInitial.current) return
    if (initialAssistant != null) {
      sentInitial.current = true
      setMessages([
        { role: 'user', content: initialUser },
        { role: 'assistant', content: initialAssistant },
      ])
      setLoaded(true)
    } else if (initialUser != null) {
      sentInitial.current = true
      setLoaded(true)
      send(initialUser)
    }
  }, [sessionId, initialUser, initialAssistant])

  // 消息变化自动滚到底部
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages])

  const appendMessage = (msg) => setMessages((m) => [...m, msg])

  const send = async (text) => {
    setError('')
    setBusy(true)
    appendMessage({ role: 'user', content: text, time: now() })
    appendMessage({ role: 'assistant', content: '', streaming: true })
    try {
      let currentSession = chatSessionId
      await streamChat({
        sessionId: currentSession,
        message: text,
        onEvent: (ev) => {
          if (ev.type === 'session') {
            currentSession = ev.session_id
            setChatSessionId(ev.session_id)
          } else if (ev.type === 'token') {
            setMessages((m) => {
              const copy = [...m]
              copy[copy.length - 1].content += ev.text
              return copy
            })
          } else if (ev.type === 'tool') {
            // agent 发起工具调用：插到流式回复前面（消息顺序 = 实际发生顺序）
            setMessages((m) => {
              const copy = [...m]
              copy.splice(copy.length - 1, 0, {
                role: 'assistant', tool: true, toolName: ev.name,
                content: '正在调用工具…',
              })
              return copy
            })
          } else if (ev.type === 'done') {
            setMessages((m) => {
              const copy = [...m]
              copy[copy.length - 1] = { role: 'assistant', content: ev.reply, time: now() }
              return copy
            })
            // 首页选了项目：会话落地后自动归属到该项目（M5）
            if (bindProjectKey && currentSession) {
              api.bindSession(currentSession, bindProjectKey).catch(() => {})
            }
          } else if (ev.type === 'error') {
            setMessages((m) => {
              const copy = [...m]
              copy[copy.length - 1] = { role: 'assistant', content: `注意：${ev.error}`, error: true }
              return copy
            })
          }
        },
      })
    } catch (e) {
      setMessages((m) => {
        const copy = [...m]
        copy[copy.length - 1] = { role: 'assistant', content: `注意：${e.message}`, error: true }
        return copy
      })
    } finally {
      setBusy(false)
      onSessionsChanged?.()
    }
  }

  const inputDisabled = busy || !loaded || (isReplay ?? false)

  return (
    <div className={className}
         style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      {/* 会话头：标题 + 任务类型 chip + 右侧图标组 */}
      <div className="chat-head">
        <span className="title">{title || '新会话'}</span>
        <span className="chat-chip">{taskType ? TASK_LABELS[taskType] || taskType : '对话'}</span>
        <div className="spacer" />
        <button className="icon-btn" title="回到底部" onClick={() => {
          if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
        }}>⤓</button>
      </div>

      {/* 消息滚动区 */}
      <div className="chat-scroll" ref={scrollRef} style={{ flex: 1, overflowY: 'auto' }}>
        {!loaded && <div style={{ color: 'var(--text-dim)', padding: 20 }}>加载中…</div>}
        {loaded && messages.length === 0 && (
          <div style={{ color: 'var(--text-faint)', padding: 20, textAlign: 'center', marginTop: 60 }}>
            {isReplay ? '这个会话没有留下事件。' : '说点什么吧。输入 / 可以唤起命令面板。'}
          </div>
        )}
        {messages.map((m, i) => (
          m.tool
            ? <ToolBlock key={i} name={m.toolName} args={m.toolArgs} result={m.content} />
            : <MsgBubble key={i} role={m.role} content={m.content} time={m.time} error={m.error} />
        ))}
        {error && <MsgBubble role="assistant" content={`注意：${error}`} error />}
      </div>

      {/* 输入区：回放只读 */}
      {isReplay ? (
        <div className="composer-wrap">
          <div className="composer">
            <textarea rows={1} disabled
              placeholder="回放模式：这是历史任务的轨迹，不可继续输入"
              style={{ color: 'var(--text-faint)' }} />
          </div>
        </div>
      ) : (
        <ChatInput
          placeholder={busy ? '对方正在输入…' : '输入消息，/ 唤起命令'}
          busy={busy}
          onSend={send}
          onCommandResult={(cmd, result, original) => {
            appendMessage({ role: 'user', content: original || cmd.cmd, time: now() })
            appendMessage({ role: 'assistant', content: result, time: now() })
          }}
        />
      )}
    </div>
  )
}

const TASK_LABELS = {
  chat: '对话', identify: '识别', watch: '盯梢',
  generate: '生成材料', study_path: '备考路径', eval: '评测',
}

function now() {
  const d = new Date()
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

// 存档事件 → 消息列表（回放用）。规则见组件顶部注释。
function eventsToMessages(events) {
  const messages = []
  for (const e of events) {
    const p = e.payload || {}
    if (e.kind === 'user_input') {
      messages.push({ role: 'user', content: p.text || '', time: hm(e.created_at) })
    } else if (e.kind === 'result') {
      if ('final_text' in p) {
        messages.push({ role: 'assistant', content: p.final_text || '', time: hm(e.created_at) })
      } else {
        const mark = p.is_competition ? '[比赛]' : (p.from_memory ? '[记忆命中]' : '[非比赛]')
        const src = p.llm_called ? 'LLM' : '没动用 LLM'
        messages.push({ role: 'assistant', content: `${mark}｜${p.title || ''}（${src}）`, time: hm(e.created_at) })
      }
    } else if (e.kind === 'tool_call') {
      messages.push({ role: 'assistant', tool: true, toolName: p.tool, toolArgs: p.args, content: p.result })
    } else if (e.kind === 'error') {
      messages.push({ role: 'assistant', content: `注意：${p.error || ''}`, error: true, time: hm(e.created_at) })
    }
    // model_call / compression 不单独成消息：token 细节看台账，轨迹以内容为主
  }
  return messages
}

function hm(iso) {
  if (!iso) return undefined
  const d = new Date(iso)
  return isNaN(d) ? undefined
    : `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
