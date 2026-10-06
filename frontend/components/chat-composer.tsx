"use client";

// 输入卡（图四形态的 TS 移植）：textarea + 工具行
// ＋上传 / 权限三档▾ / 上下文 % / 模型切换▾ / 发送。
// 状态全部来自 AppStateProvider（config/sessions），不在组件里重复拉取。
import { useEffect, useRef, useState } from "react";
import { Plus, Shield, ChevronDown, Check, X, Paperclip, ArrowUp } from "lucide-react";
import { useApp } from "@/lib/app-state";
import type { PermissionMode } from "@/lib/types";
import { api, COMMANDS } from "@/lib/api";

const PERMISSION_LABELS: Record<string, string> = {
  readonly: "只读",
  confirm: "变更前确认",
  full: "完全访问",
};
const PERMISSION_HINTS: Record<string, string> = {
  readonly: "写类工具（扫官网/识别/存材料）一律拒绝，agent 只能查不能改",
  confirm: "写类工具执行前需确认；网页聊天无法弹确认，会自动拦截（终端 sai 可交互确认）",
  full: "全部工具自动放行，无需确认",
};
// 模型上下文窗口（token）：与官方页对齐（deepseek-flash 1M）
const CONTEXT_WINDOW = 1_000_000;

export function ChatComposer({ compact = false }: { compact?: boolean }) {
  const {
    config, sendMessage, isStreaming,
    currentSessionId, sessions,
    permissionMode, changePermissionMode, switchModel,
  } = useApp();

  const [text, setText] = useState("");
  const [paletteClosed, setPaletteClosed] = useState(false);
  const [cmdIndex, setCmdIndex] = useState(0);
  const [permOpen, setPermOpen] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const [attachments, setAttachments] = useState<{ name: string; failed?: boolean }[]>([]);
  const [uploading, setUploading] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const paletteOpen = text.startsWith("/") && !paletteClosed;
  const matches = paletteOpen
    ? COMMANDS.filter((c) => c.cmd.includes(text) || c.desc.includes(text.slice(1)))
    : [];

  useEffect(() => setCmdIndex(0), [text]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setPaletteClosed(true);
        setPermOpen(false);
        setModelOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const submit = async () => {
    if (isStreaming) return;
    if (paletteOpen && matches.length > 0) {
      const cmd = matches[Math.min(cmdIndex, matches.length - 1)];
      setText("");
      setPaletteClosed(false);
      const result = await cmd.run().catch((e: Error) => `注意：${e.message}`);
      // 命令结果并入消息流：作为 user(命令)/assistant(结果) 一轮
      await sendMessage(`${cmd.cmd}\n${result}`);
      return;
    }
    let trimmed = text.trim();
    if (!trimmed && !attachments.length) return;
    if (attachments.length) {
      const lines = attachments.map((a) => `[已上传: ${a.name}]`).join("\n");
      trimmed = trimmed ? `${trimmed}\n${lines}` : lines;
    }
    setText("");
    setAttachments([]);
    await sendMessage(trimmed);
  };

  const onFilesPicked = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = [...(e.target.files ?? [])];
    e.target.value = "";
    if (!files.length) return;
    setUploading(true);
    for (const f of files) {
      try {
        const r = await api.upload(f);
        setAttachments((prev) => [...prev, { name: r.name }]);
      } catch (err) {
        setAttachments((prev) => [...prev, { name: `上传失败：${(err as Error).message}`, failed: true }]);
      }
    }
    setUploading(false);
  };

  const contextPercent = (() => {
    if (currentSessionId == null) return null;
    const s = sessions.find((x) => x.id === currentSessionId);
    return s?.prompt_tokens != null ? s.prompt_tokens / CONTEXT_WINDOW : null;
  })();

  const models = config?.models ?? [];
  const activeModel = config?.active_model ?? "";

  return (
    <div ref={wrapRef} className="relative w-full">
      {paletteOpen && (
        <div className="absolute bottom-[calc(100%+8px)] left-0 z-30 w-full min-w-[320px] overflow-hidden rounded-xl border border-border bg-card shadow-[0_8px_30px_rgba(13,13,13,0.12)]">
          {matches.length === 0 && (
            <div className="px-3.5 py-2.5 text-[13px] text-muted-foreground">
              没有匹配的命令。可用：{COMMANDS.map((c) => c.cmd).join(" ")}
            </div>
          )}
          {matches.map((c, i) => (
            <button key={c.cmd}
                    onClick={() => void runCmd(c)}
                    className={`flex w-full items-baseline gap-2.5 px-3.5 py-2.5 text-left text-[13px] transition-colors hover:bg-muted ${
                      i === Math.min(cmdIndex, matches.length - 1) ? "bg-muted" : ""}`}>
              <span className="font-mono text-primary">{c.cmd}</span>
              <span className="text-[12px] text-muted-foreground">{c.desc}</span>
            </button>
          ))}
        </div>
      )}

      <div className={`rounded-3xl border border-border bg-card px-4 pb-2.5 pt-3.5 shadow-[0_4px_24px_rgba(13,13,13,0.06)] ${
        centered() ? "shadow-[0_10px_40px_rgba(13,13,13,0.08)]" : ""}`}>
        <textarea
          value={text}
          rows={compact ? 1 : 3}
          placeholder="How can I help you today？"
          className="w-full resize-none border-none bg-transparent text-[15px] leading-relaxed text-foreground outline-none placeholder:text-muted-foreground"
          onChange={(e) => {
            setText(e.target.value);
            setPaletteClosed(false);
          }}
          onKeyDown={(e) => {
            if (paletteOpen && matches.length > 0) {
              if (e.key === "ArrowDown") { e.preventDefault(); setCmdIndex((i) => (i + 1) % matches.length); return; }
              if (e.key === "ArrowUp") { e.preventDefault(); setCmdIndex((i) => (i - 1 + matches.length) % matches.length); return; }
            }
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void submit();
            }
            if (e.key === "Escape") { setPaletteClosed(true); setPermOpen(false); setModelOpen(false); }
          }}
        />

        {attachments.length > 0 && (
          <div className="mb-1.5 flex flex-wrap gap-1.5">
            {attachments.map((a, i) => (
              <span key={i} className={`inline-flex max-w-[260px] items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] ${
                a.failed ? "bg-destructive/10 text-destructive" : "bg-muted text-muted-foreground"}`}>
                <Paperclip size={11} />
                <span className="truncate">{a.name}</span>
                <button title="移除" className="rounded-full p-0.5 hover:bg-accent"
                        onClick={() => setAttachments((prev) => prev.filter((_, j) => j !== i))}>
                  <X size={10} />
                </button>
              </span>
            ))}
          </div>
        )}

        <div className="mt-1.5 flex items-center gap-1.5">
          {/* ＋ 上传 */}
          <button disabled={uploading} onClick={() => fileRef.current?.click()}
                  title="上传文件（存到 output/uploads/）"
                  className="flex h-8 w-8 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
            <Plus size={17} strokeWidth={1.7} />
          </button>
          <input ref={fileRef} type="file" multiple hidden onChange={onFilesPicked} />

          {/* 权限三档 */}
          <div className="relative">
            <button title={PERMISSION_HINTS[permissionMode]}
                    onClick={() => { setPermOpen(!permOpen); setModelOpen(false); }}
                    className={`flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-[12.5px] transition-colors hover:bg-muted ${
                      permissionMode === "full" ? "text-primary" : "text-muted-foreground"}`}>
              <Shield size={13} strokeWidth={1.7} />
              {PERMISSION_LABELS[permissionMode] ?? permissionMode}
              <ChevronDown size={11} />
            </button>
            {permOpen && (
              <div className="absolute bottom-[calc(100%+8px)] left-0 z-30 min-w-[300px] overflow-hidden rounded-xl border border-border bg-card shadow-[0_8px_30px_rgba(13,13,13,0.12)]">
                {Object.entries(PERMISSION_LABELS).map(([mode, label]) => (
                  <button key={mode}
                          onClick={() => { void changePermissionMode(mode as PermissionMode); setPermOpen(false); }}
                          className="flex w-full items-center gap-2 px-3.5 py-2.5 text-left text-[13px] transition-colors hover:bg-muted">
                    <span className="shrink-0 font-medium">{label}</span>
                    <span className="flex-1 text-[11.5px] text-muted-foreground">{PERMISSION_HINTS[mode]}</span>
                    {permissionMode === mode && <Check size={13} className="shrink-0 text-primary" />}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="flex-1" />

          {contextPercent != null && (
            <span className="whitespace-nowrap px-1 text-[12px] text-muted-foreground" title="当前会话已用上下文（最后轮输入 token ÷ 模型窗口 1M）">
              上下文 {Math.max(1, Math.round(contextPercent * 100))}%
            </span>
          )}

          {/* 模型切换 */}
          <div className="relative">
            <button onClick={() => { setModelOpen(!modelOpen); setPermOpen(false); }}
                    title="切换模型档案"
                    className="flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-[12.5px] text-muted-foreground transition-colors hover:bg-muted">
              {models.find((m) => m.name === activeModel)?.model ?? "…"}
              <ChevronDown size={11} />
            </button>
            {modelOpen && (
              <div className="absolute bottom-[calc(100%+8px)] right-0 z-30 min-w-[260px] overflow-hidden rounded-xl border border-border bg-card shadow-[0_8px_30px_rgba(13,13,13,0.12)]">
                {models.map((m) => (
                  <button key={m.name}
                          onClick={() => { void switchModel(m.name); setModelOpen(false); }}
                          className="flex w-full items-center gap-2 px-3.5 py-2.5 text-left text-[13px] transition-colors hover:bg-muted">
                    <span className="shrink-0 font-medium">{m.model}</span>
                    <span className="flex-1 text-[11.5px] text-muted-foreground">
                      {m.name}{m.has_key ? "" : "（缺密钥）"}
                    </span>
                    {m.name === activeModel && <Check size={13} className="shrink-0 text-primary" />}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* 发送 */}
          <button
            onClick={() => void submit()}
            disabled={isStreaming || (!text.trim() && !attachments.length)}
            title="发送（Enter）"
            className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-primary-foreground transition-all hover:opacity-90 disabled:cursor-default disabled:bg-muted disabled:text-muted-foreground"
          >
            <ArrowUp size={16} strokeWidth={2} />
          </button>
        </div>
      </div>
    </div>
  );

  function centered() {
    return false; // 居中形态的加重视觉由页面容器控制
  }

  async function runCmd(c: (typeof COMMANDS)[number]) {
    setText("");
    setPaletteClosed(false);
    const result = await c.run().catch((e: Error) => `注意：${e.message}`);
    await sendMessage(`${c.cmd}\n${result}`);
  }
}
