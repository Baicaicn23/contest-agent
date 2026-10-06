// 全局应用状态（M11：TeachX 的 ChatStateAdapter 模式）——
// config / sessions / 聊天运行时状态全部收进一个 Provider，
// 页面切换（工作台 ↔ 聊天）不卸载它，流式回答因此跨页面不断线。
"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { api, streamChat, type ChatFrame, type SessionDetail } from "./api";
import type {
  AppConfig,
  ChatMessage,
  SessionSummary,
  PermissionMode,
} from "./types";

interface AppState {
  config: AppConfig | null;
  refreshConfig: () => Promise<void>;

  sessions: SessionSummary[];
  refreshSessions: () => Promise<void>;

  runningIds: Set<number>;
  markRunning: (id: number, running: boolean) => void;

  // 聊天运行时：跨页面存活（工作台发送 → 路由切到 /chat，流不断）
  currentSessionId: number | null;
  messages: ChatMessage[];
  isStreaming: boolean;
  startChat: () => void;                       // 回到空白新会话
  openSession: (id: number) => Promise<void>;  // 打开历史会话（回放/续聊）
  sendMessage: (text: string) => Promise<void>;

  permissionMode: string;
  changePermissionMode: (mode: PermissionMode) => Promise<void>;
  switchModel: (name: string) => Promise<void>;

  desktopNotify: boolean;
  toggleDesktopNotify: () => Promise<void>;
}

const Ctx = createContext<AppState | null>(null);

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp 必须在 <AppStateProvider> 内使用");
  return v;
}

function nowHM(): string {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

const TASK_LABELS: Record<string, string> = {
  chat: "对话", identify: "识别", watch: "盯梢",
  generate: "生成", study_path: "备考", eval: "评测",
};

// 存档事件 → 消息列表（回放用），规则沿袭 M4 实现
function eventsToMessages(events: SessionDetail["events"]): ChatMessage[] {
  const out: ChatMessage[] = [];
  for (const e of events) {
    const p = e.payload || {};
    if (e.kind === "user_input") {
      out.push({ role: "user", content: String(p.text ?? ""), time: hmOf(e.created_at) });
    } else if (e.kind === "result") {
      if ("final_text" in p) {
        out.push({ role: "assistant", content: String(p.final_text ?? ""), time: hmOf(e.created_at) });
      } else {
        const mark = p.is_competition ? "[比赛]" : p.from_memory ? "[记忆命中]" : "[非比赛]";
        out.push({
          role: "assistant",
          content: `${mark}｜${String(p.title ?? "")}（${p.llm_called ? "LLM" : "没动用 LLM"}）`,
          time: hmOf(e.created_at),
        });
      }
    } else if (e.kind === "tool_call") {
      out.push({
        role: "assistant", tool: true, toolName: String(p.tool ?? ""),
        toolArgs: (p.args as Record<string, unknown>) ?? {}, content: String(p.result ?? ""),
      });
    } else if (e.kind === "error") {
      out.push({ role: "assistant", content: `注意：${String(p.error ?? "")}`, error: true, time: hmOf(e.created_at) });
    }
  }
  return out;
}

function hmOf(iso: string | null): string | undefined {
  if (!iso) return undefined;
  const d = new Date(iso);
  return isNaN(d.getTime()) ? undefined : `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function AppStateProvider({ children }: { children: React.ReactNode }) {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [runningIds, setRunningIds] = useState<Set<number>>(new Set());

  const [currentSessionId, setCurrentSessionId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);

  const [desktopNotify, setDesktopNotify] = useState(
    () => typeof window !== "undefined" && localStorage.getItem("ca-desktop-notify") === "1",
  );

  const refreshConfig = useCallback(async () => {
    try {
      setConfig(await api.config());
    } catch {
      /* 服务不可达时保持上次状态 */
    }
  }, []);

  const refreshSessions = useCallback(async () => {
    try {
      setSessions((await api.sessions(30)).sessions);
    } catch {
      /* 静默：下一轮轮询对齐 */
    }
  }, []);

  useEffect(() => {
    void refreshConfig();
    void refreshSessions();
    const timer = setInterval(() => void refreshSessions(), 15_000);
    return () => clearInterval(timer);
  }, [refreshConfig, refreshSessions]);

  const markRunning = useCallback((id: number, running: boolean) => {
    setRunningIds((prev) => {
      const next = new Set(prev);
      if (running) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  // ---------- 聊天运行时 ----------

  const startChat = useCallback(() => {
    setCurrentSessionId(null);
    setMessages([]);
  }, []);

  const openSession = useCallback(async (id: number) => {
    setCurrentSessionId(id);
    if (id === currentSessionId && messages.length) return; // 已是当前会话
    try {
      const detail = await api.sessionDetail(id);
      if (detail.session.task_type !== "chat") {
        setMessages(eventsToMessages(detail.events));
      } else {
        const cached = messages;
        setMessages(cached.length ? cached : eventsToMessages(detail.events));
      }
    } catch (e) {
      setMessages([{ role: "assistant", content: `注意：${(e as Error).message}`, error: true }]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentSessionId, messages]);

  const sendMessage = useCallback(
    async (text: string) => {
      if (isStreaming) return;
      setError0("");
      setMessages((m) => [
        ...m,
        { role: "user", content: text, time: nowHM() },
        { role: "assistant", content: "", streaming: true },
      ]);
      setIsStreaming(true);
      let sid = currentSessionId;
      const patchLast = (patch: Partial<ChatMessage>) =>
        setMessages((m) => {
          const copy = [...m];
          copy[copy.length - 1] = { ...copy[copy.length - 1], ...patch };
          return copy;
        });
      const insertTool = (name: string) =>
        setMessages((m) => {
          const copy = [...m];
          copy.splice(copy.length - 1, 0, {
            role: "assistant", tool: true, toolName: name, content: "正在调用工具…",
          });
          return copy;
        });
      try {
        await streamChat({
          sessionId: sid,
          message: text,
          onEvent: (f: ChatFrame) => {
            if (f.type === "session") {
              sid = f.session_id;
              setCurrentSessionId(f.session_id);
              markRunning(f.session_id, true);
              void refreshSessions();
            } else if (f.type === "token") {
              setMessages((m) => {
                const copy = [...m];
                const last = copy[copy.length - 1];
                copy[copy.length - 1] = { ...last, content: last.content + f.text };
                return copy;
              });
            } else if (f.type === "tool") {
              insertTool(f.name);
            } else if (f.type === "done") {
              // done 一到就解除"运行中"（SSE 尾部偶尔挂起，不等流关闭）
              if (sid != null) markRunning(sid, false);
              patchLast({ content: f.reply, streaming: false, time: nowHM() });
            }
          },
        });
      } catch (e) {
        patchLast({ content: `注意：${(e as Error).message}`, error: true, streaming: false });
      } finally {
        setIsStreaming(false);
        if (sid != null) markRunning(sid, false);
        void refreshSessions();
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [currentSessionId, isStreaming, markRunning, refreshSessions],
  );

  function setError0(_: string) {
    /* 预留：错误走消息流渲染 */
  }

  // ---------- 配置操作 ----------

  const changePermissionMode = useCallback(
    async (mode: PermissionMode) => {
      try {
        await api.setPermissionMode(mode);
        await refreshConfig();
      } catch {
        /* 静默 */
      }
    },
    [refreshConfig],
  );

  const switchModel = useCallback(
    async (name: string) => {
      try {
        await api.switchModel(name);
        await refreshConfig();
      } catch {
        /* 静默 */
      }
    },
    [refreshConfig],
  );

  const toggleDesktopNotify = useCallback(async () => {
    if (!desktopNotify) {
      if (!("Notification" in window)) {
        alert("这个浏览器不支持桌面通知。");
        return;
      }
      let permission = Notification.permission;
      if (permission === "default") permission = await Notification.requestPermission();
      if (permission !== "granted") {
        alert("通知权限被拒绝。可以在浏览器地址栏左侧的站点设置里重新允许。");
        return;
      }
      localStorage.setItem("ca-desktop-notify", "1");
      setDesktopNotify(true);
      try {
        const n = await api.notifications();
        const seen = new Set(JSON.parse(localStorage.getItem("ca-notified") || "[]"));
        for (const d of n.urgent_deadlines || []) seen.add(`${d.name}|${d.label}`);
        localStorage.setItem("ca-notified", JSON.stringify([...seen]));
      } catch {
        /* 下次轮询再标 */
      }
    } else {
      localStorage.setItem("ca-desktop-notify", "0");
      setDesktopNotify(false);
    }
  }, [desktopNotify]);

  // 桌面提醒轮询：60 秒一次，只弹 localStorage 没见过的增量
  useEffect(() => {
    if (!desktopNotify) return;
    const check = async () => {
      try {
        const n = await api.notifications();
        const seen = new Set(JSON.parse(localStorage.getItem("ca-notified") || "[]"));
        const fresh = (n.urgent_deadlines || []).filter((d) => !seen.has(`${d.name}|${d.label}`));
        for (const d of fresh) {
          new Notification("比赛截止提醒", { body: `${d.name} — ${d.label}` });
          seen.add(`${d.name}|${d.label}`);
        }
        if (fresh.length) localStorage.setItem("ca-notified", JSON.stringify([...seen]));
      } catch {
        /* 下轮 */
      }
    };
    void check();
    const timer = setInterval(() => void check(), 60_000);
    return () => clearInterval(timer);
  }, [desktopNotify]);

  const permissionMode = config?.permission_mode ?? "confirm";

  const value = useMemo<AppState>(
    () => ({
      config, refreshConfig,
      sessions, refreshSessions,
      runningIds, markRunning,
      currentSessionId, messages, isStreaming, startChat, openSession, sendMessage,
      permissionMode, changePermissionMode, switchModel,
      desktopNotify, toggleDesktopNotify,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [config, sessions, runningIds, currentSessionId, messages, isStreaming, desktopNotify],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export { TASK_LABELS };
