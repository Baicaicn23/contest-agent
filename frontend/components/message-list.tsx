"use client";

// 消息流：user 右气泡 / assistant 左正文（Markdown 块渲染）/ 工具折叠块。
// 自动滚底：消息数组变化时滚到最新。
import { useEffect, useRef } from "react";
import { ChevronDown } from "lucide-react";
import { useApp } from "@/lib/app-state";
import { Markdown } from "@/lib/markdown";

export function MessageList() {
  const { messages, isStreaming } = useApp();
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  return (
    <div className="relative min-h-0 flex-1">
      <div ref={scrollRef} className="h-full overflow-y-auto px-6 pb-4 pt-2">
        {!messages.length && (
          <div className="pt-24 text-center text-[13.5px] text-muted-foreground">
            说点什么吧。输入 / 可以唤起命令面板。
          </div>
        )}
        {messages.map((m, i) =>
          m.tool ? (
            <details key={i} className="group my-2 max-w-[680px] overflow-hidden rounded-xl border border-border">
              <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-[12.5px] text-muted-foreground transition-colors hover:bg-muted">
                <ChevronDown size={12} className="transition-transform group-open:rotate-90" />
                工具调用：{m.toolName ?? "未知"}
              </summary>
              <div className="whitespace-pre-wrap break-all px-3 pb-2.5 font-mono text-[11.5px] text-muted-foreground">
                {String(m.content ?? "").slice(0, 600)}
              </div>
            </details>
          ) : m.role === "user" ? (
            <div key={i} className="my-4 flex flex-col items-end">
              <div className="max-w-[72%] whitespace-pre-wrap break-words rounded-3xl bg-muted px-4 py-2.5 text-[15px] leading-relaxed">
                {m.content}
              </div>
              {m.time && <div className="mt-1 text-[11.5px] text-muted-foreground/70">{m.time}</div>}
            </div>
          ) : (
            <div key={i} className="my-4 flex flex-col items-start">
              <div className={`max-w-full whitespace-pre-wrap break-words text-[15px] leading-[1.75] ${
                m.error ? "text-destructive" : ""}`}>
                {m.content ? <Markdown content={m.content} /> : m.streaming ? <StreamingDots /> : "\u00A0"}
              </div>
              {m.time && <div className="mt-1 text-[11.5px] text-muted-foreground/70">{m.time}</div>}
            </div>
          ),
        )}
        {isStreaming && <div className="pb-2" />}
      </div>
      <ScrollBottomBtn target={scrollRef} />
    </div>
  );
}

function StreamingDots() {
  return <span className="inline-block animate-pulse text-primary">▍</span>;
}

function ScrollBottomBtn({ target }: { target: React.RefObject<HTMLDivElement | null> }) {
  return (
    <button
      onClick={() => { if (target.current) target.current.scrollTop = target.current.scrollHeight; }}
      title="回到底部"
      className="absolute bottom-3 right-5 flex h-8 w-8 items-center justify-center rounded-full border border-border bg-card text-muted-foreground shadow-sm transition-colors hover:bg-muted"
    >
      <ChevronDown size={15} />
    </button>
  );
}
