// ============ 后端 API 封装 ============
// 所有对 FastAPI 的请求都从这里走。路径全部是相对路径：
// 开发时由 Vite 代理转发到 8000 端口，生产构建后与后端同源。

async function jfetch(path, options = {}) {
  const resp = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!resp.ok) {
    let detail = `请求失败（${resp.status}）`
    try {
      const body = await resp.json()
      if (body.detail) detail = body.detail
    } catch { /* 非 JSON 响应就用默认提示 */ }
    throw new Error(detail)
  }
  return resp.json()
}

export const api = {
  // Overview 面板
  usageSummary: (range) => jfetch(`/api/usage/summary?range=${range}`),

  // 配置（读脱敏视图 / 写档案与预算）
  config: () => jfetch('/api/config'),
  switchModel: (name) =>
    jfetch('/api/config/model', { method: 'POST', body: JSON.stringify({ name }) }),
  setBudget: (yuan) =>
    jfetch('/api/config/budget', { method: 'POST', body: JSON.stringify({ yuan }) }),

  // 会话与轨迹
  sessions: (limit = 30) => jfetch(`/sessions?limit=${limit}`),
  sessionDetail: (id) => jfetch(`/sessions/${id}`),
  closeChat: (sessionId) =>
    jfetch('/api/chat/close', { method: 'POST', body: JSON.stringify({ session_id: sessionId }) }),

  // 任务类
  scan: (limit = 10) => jfetch('/scan', { method: 'POST', body: JSON.stringify({ limit }) }),
  identify: (limit = 3) => jfetch('/identify', { method: 'POST', body: JSON.stringify({ limit }) }),
  generate: (skill = 'ppt-outline', competition = null) =>
    jfetch('/generate', { method: 'POST', body: JSON.stringify({ skill, competition }) }),
  studyPath: (competition = null) =>
    jfetch('/study-path', { method: 'POST', body: JSON.stringify({ competition }) }),
  cost: (query = '') => jfetch(`/cost${query}`),
  report: () => jfetch('/report'),

  chatClose: (sessionId) =>
    jfetch('/api/chat/close', { method: 'POST', body: JSON.stringify({ session_id: sessionId }) }),
}

// 自由对话：POST /api/chat 的响应是 SSE 流（每帧 `data: {json}\n\n`）。
// EventSource 只支持 GET，所以用 fetch + ReadableStream 手工解析——
// 这是业界对"POST + 流式"的标准做法。
export async function streamChat({ sessionId, message, onEvent }) {
  const resp = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
  })
  if (!resp.ok) {
    let detail = `请求失败（${resp.status}）`
    try { detail = (await resp.json()).detail || detail } catch { /* 保持默认 */ }
    throw new Error(detail)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // 帧与帧以空行分隔；粘包时留半帧在 buffer 里下次拼
    const frames = buffer.split('\n\n')
    buffer = frames.pop()
    for (const frame of frames) {
      const line = frame.trim()
      if (!line.startsWith('data: ')) continue
      try {
        onEvent(JSON.parse(line.slice(6)))
      } catch { /* 跳过解析失败的帧 */ }
    }
  }
}

// / 命令面板：前端把斜杠命令翻译成对后端的一次调用，
// 结果统一转成"助手消息文本"渲染进对话流。
export const COMMANDS = [
  {
    cmd: '/识别',
    desc: '扫描并识别最新通知（多次 LLM 调用，约 30 秒）',
    placeholder: '/识别',
    run: async () => {
      const r = await api.identify(5)
      const lines = [`共扫描 ${r.count} 条通知，新增卡片 ${r.last_sync?.new ?? 0} 张：`, '']
      for (const o of r.outcomes) {
        const mark = o.is_competition ? '✅ 比赛' : (o.from_memory ? '💾 记忆' : '❌ 非比赛')
        lines.push(`- ${mark} | ${o.title}`)
        if (o.card) lines.push(`  ${o.card.name}（${o.card.type}，截止 ${o.card.deadline ?? '见通知'}）`)
      }
      if (r.budget_error) lines.push('', `⚠️ ${r.budget_error}`)
      return lines.join('\n')
    },
  },
  {
    cmd: '/扫描',
    desc: '只扫描通知列表，不花 LLM',
    run: async () => {
      const r = await api.scan(10)
      const lines = [`扫描到 ${r.count} 条通知（新增 ${r.sync?.new ?? 0} 条）：`, '']
      for (const n of r.notices.slice(0, 8)) lines.push(`- [${(n.published_at || '').slice(0, 10)}] ${n.title}`)
      return lines.join('\n')
    },
  },
  {
    cmd: '/生成',
    desc: '为最近的比赛生成 PPT 大纲 + .pptx 文件（30-90 秒）',
    run: async () => {
      const r = await api.generate('ppt-outline')
      const pptx = r.pptx_file ? `\n\n📊 幻灯片已导出：output/${r.pptx_file}（可用 PowerPoint/WPS 打开）` : ''
      const hint = r.pptx_hint ? `\n\n⚠️ ${r.pptx_hint}` : ''
      return `工具调用 ${r.tool_trace.length} 次，${r.success ? '完成 ✅' : '失败：' + r.error}${pptx}${hint}\n\n${r.final_text}`
    },
  },
  {
    cmd: '/备考',
    desc: '生成备考学习路径（联网搜索 + 引用校验）',
    run: async () => {
      const r = await api.studyPath(null)
      const ok = r.citations.filter((c) => c.ok).length
      return `引用校验 ${ok}/${r.citations.length} 通过，${r.success ? '完成 ✅' : '失败：' + (r.error || '仍有失效链接')}\n\n${r.final_text}`
    },
  },
  {
    cmd: '/账单',
    desc: '看看今天的 LLM 花费',
    run: async () => {
      const r = await api.cost('?today=true')
      const t = r.total
      if (!t || t.calls === 0) return '今天还没有任何 LLM 调用。'
      const cost = t.cost_yuan == null ? '费用未知（未配单价）' : `¥${t.cost_yuan.toFixed(4)}`
      const byTask = Object.entries(r.by_task)
        .map(([k, v]) => `  - ${k}：${v.calls} 次${v.cost_yuan != null ? `，¥${v.cost_yuan.toFixed(4)}` : ''}`)
        .join('\n')
      return `今天共 ${t.calls} 次调用，${cost}\n按任务：\n${byTask}`
    },
  },
  {
    cmd: '/报告',
    desc: '渲染比赛情报报告',
    run: async () => (await api.report()),
  },
]
