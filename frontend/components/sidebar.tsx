"use client";

// 侧栏（TeachX WorkspaceSidebar 形态）：logo + 折叠钮 → 快捷操作 → 导航 →
// 会话列表（运行中转圈、任务徽章、相对时间、未归类/按项目分组）→ 底部用户盒。
import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  Home, BarChart3, CalendarClock, LayoutGrid, Settings,
  SquarePen, Trash2, Bell, Search, Loader2,
} from "lucide-react";
import { useApp } from "@/lib/app-state";
import { api } from "@/lib/api";
import { relTime } from "@/lib/format";
import type { SessionSummary } from "@/lib/types";

const NAV = [
  { href: "/", label: "工作台", icon: Home },
  { href: "/stats", label: "统计", icon: BarChart3 },
  { href: "/deadlines", label: "日程", icon: CalendarClock },
  { href: "/plugins", label: "插件", icon: LayoutGrid },
  { href: "/settings", label: "设置", icon: Settings },
];

const TASK_LABELS_CN: Record<string, string> = {
  chat: "对话", identify: "识别", watch: "盯梢",
  generate: "生成", study_path: "备考", eval: "评测",
};

export function Sidebar({ onCollapse }: { onCollapse: () => void }) {
  const router = useRouter();
  const pathname = usePathname();
  const { sessions, runningIds, currentSessionId, startChat } = useApp();
  const [projectNames, setProjectNames] = useState<Record<string, string>>({});
  const [notifOpen, setNotifOpen] = useState(false);
  const [notifData, setNotifData] = useState<{ urgent: { name: string; label: string }[]; done: number } | null>(null);

  // 项目名映射（会话按 project_key 分组显示用）；路由变化时顺带刷新会话数据
  useEffect(() => {
    api.projects().then((r) => {
      const map: Record<string, string> = {};
      for (const p of r.projects) map[p.key] = p.name;
      setProjectNames(map);
    }).catch(() => {});
  }, [pathname]);

  const isRunning = (s: SessionSummary) => runningIds.has(s.id) || s.status === "running";

  const owned = sessions.filter((s) => s.project_key);
  const loose = sessions.filter((s) => !s.project_key);
  const groupedKeys = [...new Set(owned.map((s) => s.project_key ?? ""))].filter(Boolean);

  const handleNewChat = useCallback(() => {
    startChat();
    router.push("/chat");
  }, [router, startChat]);

  const handleOpenSession = useCallback(
    (s: SessionSummary) => {
      router.push(`/chat?session=${s.id}`);
    },
    [router],
  );

  const navBase =
    "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-[7px] text-[13.5px] transition-colors";

  return (
    <aside className="flex h-dvh w-[232px] shrink-0 flex-col border-r border-border bg-[#f7f7f5]">
      {/* logo 行 */}
      <div className="flex items-center justify-between px-3 pb-2 pt-3">
        <span className="flex items-center gap-1.5 font-semibold tracking-tight">
          <span className="flex h-5 w-5 items-center justify-center rounded bg-primary font-serif text-[11px] text-primary-foreground">
            C
          </span>
          Contest Agent
        </span>
        <button
          onClick={onCollapse}
          title="收起侧栏（⌘B）"
          className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
            <rect x="3.5" y="4.5" width="17" height="15" rx="2.5" />
            <path d="M9.5 4.5v15" />
          </svg>
        </button>
      </div>

      {/* 快捷操作行：新聊天 / 通知 / 搜索 */}
      <div className="relative flex items-center gap-1 px-3 pb-2">
        <button
          onClick={handleNewChat}
          title="新聊天（⌘N）"
          className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <SquarePen size={15} strokeWidth={1.7} />
        </button>
        <div className="relative">
          <button
            title="通知"
            onClick={async () => {
              const next = !notifOpen;
              setNotifOpen(next);
              if (next) {
                try {
                  const n = await api.notifications();
                  setNotifData({ urgent: n.urgent_deadlines ?? [], done: n.completed_recently });
                } catch {
                  /* 静默 */
                }
              }
            }}
            className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <Bell size={15} strokeWidth={1.7} />
            {notifData && notifData.urgent.length > 0 && (
              <span className="absolute -right-0.5 -top-0.5 flex h-3.5 min-w-[14px] items-center justify-center rounded-full bg-destructive px-1 text-[9px] font-medium text-white">
                {notifData.urgent.length}
              </span>
            )}
          </button>
          {notifOpen && (
            <div
              className="fixed left-[244px] top-12 z-50 w-72 rounded-xl border border-border bg-card p-2 shadow-[0_8px_30px_rgba(13,13,13,0.12)]"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="px-2 py-1 text-[13px] font-semibold">通知</div>
              <div className="my-1 h-px bg-border" />
              {!notifData && <div className="px-2 py-2 text-[12.5px] text-muted-foreground">加载中…</div>}
              {notifData && notifData.urgent.length === 0 && (
                <div className="px-2 py-2 text-[12.5px] text-muted-foreground">
                  没有紧急截止。近 24h 完成 {notifData.done} 个任务。
                </div>
              )}
              {notifData?.urgent.map((d) => (
                <div key={d.name} className="px-2 py-1.5 text-[12.5px]">
                  <div>{d.name}</div>
                  <div className="text-[11px] text-muted-foreground">{d.label}</div>
                </div>
              ))}
              <div className="my-1 h-px bg-border" />
              <button
                className="w-full rounded-md px-2 py-1.5 text-left text-[12.5px] transition-colors hover:bg-muted"
                onClick={() => {
                  setNotifOpen(false);
                  router.push("/deadlines");
                }}
              >
                查看全部截止日程
              </button>
            </div>
          )}
        </div>
        <button
          title="全局搜索（会话列表即历史索引；/ 唤起命令）"
          className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <Search size={15} strokeWidth={1.7} />
        </button>
      </div>

      {/* 导航 */}
      <nav className="flex flex-col gap-0.5 px-3">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = pathname === href;
          return (
            <button
              key={href}
              onClick={() => router.push(href)}
              className={`${navBase} ${active ? "bg-muted font-medium text-foreground" : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"}`}
            >
              <Icon className="h-[17px] w-[17px] shrink-0" strokeWidth={1.7} /> {label}
            </button>
          );
        })}
      </nav>

      {/* 会话列表 */}
      <div className="mt-4 flex items-center justify-between px-4">
        <span className="text-[12px] font-medium text-muted-foreground">对话</span>
        <button onClick={handleNewChat} title="新聊天"
                className="text-muted-foreground transition-colors hover:text-foreground">
          <SquarePen size={13} strokeWidth={1.7} />
        </button>
      </div>
      <div className="mt-1 flex-1 overflow-y-auto px-3 pb-2">
        {!sessions.length && (
          <div className="px-2 py-3 text-[12.5px] text-muted-foreground">
            还没有会话。识别比赛或直接聊天。
          </div>
        )}
        {groupedKeys.map((key) => (
          <div key={key} className="mb-2">
            <div className="mb-0.5 mt-1 px-2 text-[12px] font-medium text-foreground/80">
              {projectNames[key] ?? key}
            </div>
            <SessionRows sessions={owned.filter((s) => s.project_key === key)}
                         runningIds={runningIds} currentSessionId={currentSessionId}
                         onOpen={handleOpenSession} projectNames={projectNames} />
          </div>
        ))}
        {loose.length > 0 && (
          <div className="mb-1 mt-3 px-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground/70">
            未归类
          </div>
        )}
        <SessionRows sessions={loose} runningIds={runningIds} currentSessionId={currentSessionId}
                     onOpen={handleOpenSession} projectNames={projectNames} />
      </div>

      {/* 底部用户盒 */}
      <div className="border-t border-border p-3">
        <button
          onClick={() => router.push("/settings")}
          className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-[13px] transition-colors hover:bg-muted"
        >
          <span className="flex h-[22px] w-[22px] items-center justify-center rounded-full bg-primary text-[10.5px] font-semibold text-primary-foreground">
            M
          </span>
          <span className="flex-1 text-left">momo</span>
          <span className="rounded-full border border-border px-1.5 text-[10.5px] text-muted-foreground">本地</span>
        </button>
      </div>
    </aside>
  );
}

function SessionRows({ sessions, runningIds, currentSessionId, onOpen, projectNames: _pn }: {
  sessions: SessionSummary[];
  runningIds: Set<number>;
  currentSessionId: number | null;
  onOpen: (s: SessionSummary) => void;
  projectNames: Record<string, string>;
}) {
  if (!sessions.length) return null;
  return (
    <div className="flex flex-col gap-0.5">
      {sessions.map((s) => {
        const running = runningIds.has(s.id) || s.status === "running";
        const active = currentSessionId === s.id;
        return (
          <button
            key={s.id}
            onClick={() => onOpen(s)}
            className={`group flex w-full items-center gap-2 rounded-lg px-2.5 py-[7px] text-left text-[13px] transition-colors ${
              active ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
            }`}
          >
            {running ? (
              <Loader2 size={12} className="shrink-0 animate-spin text-primary" />
            ) : (
              <span className="shrink-0 rounded border border-border px-1 text-[10px] leading-[15px] text-muted-foreground">
                {TASK_LABELS_CN[s.task_type] || s.task_type}
              </span>
            )}
            <span className="flex-1 truncate">{s.note || `#${s.id}`}</span>
            {!running && s.started_at && (
              <span className="shrink-0 text-[11px] text-muted-foreground/70">{relTime(s.started_at)}</span>
            )}
            {!running && (
              <span
                role="button"
                title="删除会话（接口未开放）"
                onClick={(e) => {
                  e.stopPropagation();
                  alert("会话删除接口尚未开放（后续版本提供）。");
                }}
                className="hidden shrink-0 text-muted-foreground/50 transition-colors hover:text-destructive group-hover:block"
              >
                <Trash2 size={12} />
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
