// 后端 API 客户端（M11 TS 移植自旧 api.js）：全部相对路径，
// 生产环境与 FastAPI 同源（uv run sai serve 托管 out/）。

async function jfetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    let detail = `请求失败（${resp.status}）`;
    try {
      const body = await resp.json();
      if (body.detail) detail = body.detail;
    } catch {
      /* 非 JSON 响应就用默认提示 */
    }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

export interface SessionFrame {
  type: "session";
  session_id: number;
}
export interface TokenFrame {
  type: "token";
  text: string;
}
export interface ToolFrame {
  type: "tool";
  name: string;
}
export interface DoneFrame {
  type: "done";
  reply: string;
  error?: string;
}
export type ChatFrame = SessionFrame | TokenFrame | ToolFrame | DoneFrame;

/** 聊天 SSE：POST /api/chat 的响应是 `data: {json}` 帧流。
 * EventSource 只支持 GET，所以用 fetch + ReadableStream 手工解析——
 * POST + 流式的业界标准做法（Claude/Codex 同款）。 */
export async function streamChat(
  opts: { sessionId: number | null; message: string; onEvent: (f: ChatFrame) => void },
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: opts.message, session_id: opts.sessionId }),
    signal,
  });
  if (!resp.ok || !resp.body) {
    let detail = `请求失败（${resp.status}）`;
    try {
      detail = (await resp.json()).detail || detail;
    } catch {
      /* 保持默认 */
    }
    throw new Error(detail);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.trim();
      if (!line.startsWith("data: ")) continue;
      try {
        opts.onEvent(JSON.parse(line.slice(6)) as ChatFrame);
      } catch {
        /* 跳过解析失败的帧 */
      }
    }
  }
}

export interface SessionDetail {
  session: { id: number; task_type: string; note: string; status: string };
  events: {
    seq: number;
    kind: string;
    payload: Record<string, unknown>;
    created_at: string | null;
  }[];
}

export const api = {
  health: () => jfetch<{ status: string }>("/health"),

  config: () => jfetch<import("./types").AppConfig>("/api/config"),
  switchModel: (name: string) =>
    jfetch("/api/config/model", { method: "POST", body: JSON.stringify({ name }) }),
  setBudget: (yuan: number | null) =>
    jfetch("/api/config/budget", { method: "POST", body: JSON.stringify({ yuan }) }),
  setPermissionMode: (mode: string) =>
    jfetch("/api/config/permission-mode", { method: "POST", body: JSON.stringify({ mode }) }),

  sessions: (limit = 30) => jfetch<{ count: number; sessions: import("./types").SessionSummary[] }>(`/sessions?limit=${limit}`),
  sessionDetail: (id: number) => jfetch<SessionDetail>(`/sessions/${id}`),

  projects: () => jfetch<{ count: number; projects: import("./types").ProjectInfo[] }>("/api/projects"),
  createProject: (name: string) =>
    jfetch("/api/projects", { method: "POST", body: JSON.stringify({ name }) }),
  deleteProject: (key: string) =>
    jfetch<{ deleted: string; unbound_sessions: number }>(`/api/projects/${encodeURIComponent(key)}`, { method: "DELETE" }),
  bindSession: (sessionId: number, projectKey: string) =>
    jfetch("/api/projects/bind", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, project_key: projectKey }),
    }),

  search: (q: string) => jfetch(`/api/search?q=${encodeURIComponent(q)}`),
  notifications: () => jfetch<import("./types").NotificationData>("/api/notifications"),
  deadlines: () => jfetch<{ count: number; deadlines: import("./types").DeadlineItem[] }>("/api/deadlines"),
  skills: () => jfetch<{ count: number; skills: import("./types").SkillInfo[] }>("/api/skills"),
  plugins: () => jfetch<{ count: number; installed_count: number; plugins: import("./types").PluginInfo[] }>("/api/plugins"),
  togglePlugin: (id: string, enabled: boolean) =>
    jfetch(`/api/plugins/${id}/toggle`, { method: "POST", body: JSON.stringify({ enabled }) }),
  gitBranch: () => jfetch<{ branch: string }>("/api/git/branch"),
  usageSummary: (range = "all") => jfetch<Record<string, unknown>>(`/api/usage/summary?range=${range}`),

  upload: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const resp = await fetch("/api/upload", { method: "POST", body: form });
    if (!resp.ok) {
      let detail = `上传失败（${resp.status}）`;
      try {
        detail = (await resp.json()).detail || detail;
      } catch {
        /* 保持默认 */
      }
      throw new Error(detail);
    }
    return resp.json() as Promise<{ name: string; size: number }>;
  },

  identify: (limit = 3) => jfetch("/identify", { method: "POST", body: JSON.stringify({ limit }) }),
  scan: (limit = 10) => jfetch("/scan", { method: "POST", body: JSON.stringify({ limit }) }),
  cost: (query = "") => jfetch(`/cost${query}`),
  report: () => jfetch<string>("/report"),
};

export interface SlashCommand {
  cmd: string;
  desc: string;
  run: () => Promise<string>;
}

// / 命令面板：前端把斜杠命令翻译成对后端的一次调用
export const COMMANDS: SlashCommand[] = [
  {
    cmd: "/识别",
    desc: "扫描并识别最新通知（多次 LLM 调用，约 30 秒）",
    run: async () => {
      const r = await api.identify(5) as {
        count: number;
        last_sync?: { new?: number };
        outcomes: { is_competition: boolean; from_memory: boolean; title: string; card?: { name: string; type: string; deadline: string | null } }[];
        budget_error?: string;
      };
      const lines = [`共扫描 ${r.count} 条通知，新增卡片 ${r.last_sync?.new ?? 0} 张：`, ""];
      for (const o of r.outcomes) {
        const mark = o.is_competition ? "[比赛]" : o.from_memory ? "[记忆命中]" : "[非比赛]";
        lines.push(`- ${mark} | ${o.title}`);
        if (o.card) lines.push(`  ${o.card.name}（${o.card.type}，截止 ${o.card.deadline ?? "见通知"}）`);
      }
      if (r.budget_error) lines.push("", `注意：${r.budget_error}`);
      return lines.join("\n");
    },
  },
  {
    cmd: "/扫描",
    desc: "只扫描通知列表，不花 LLM",
    run: async () => {
      const r = await api.scan(10) as { count: number; sync?: { new?: number }; notices: { published_at: string | null; title: string }[] };
      const lines = [`扫描到 ${r.count} 条通知（新增 ${r.sync?.new ?? 0} 条）：`, ""];
      for (const n of r.notices.slice(0, 8)) lines.push(`- [${(n.published_at || "").slice(0, 10)}] ${n.title}`);
      return lines.join("\n");
    },
  },
  {
    cmd: "/账单",
    desc: "看看今天的 LLM 花费",
    run: async () => {
      const r = await api.cost("?today=true") as {
        total?: { calls: number; cost_yuan: number | null };
        by_task: Record<string, { calls: number; cost_yuan: number | null }>;
      };
      const t = r.total;
      if (!t || t.calls === 0) return "今天还没有任何 LLM 调用。";
      const cost = t.cost_yuan == null ? "费用未知（未配单价）" : `¥${t.cost_yuan.toFixed(4)}`;
      const byTask = Object.entries(r.by_task)
        .map(([k, v]) => `  - ${k}：${v.calls} 次${v.cost_yuan != null ? `，¥${v.cost_yuan.toFixed(4)}` : ""}`)
        .join("\n");
      return `今天共 ${t.calls} 次调用，${cost}\n按任务：\n${byTask}`;
    },
  },
];
