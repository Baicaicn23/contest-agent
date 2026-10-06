"use client";

// 会话页：顶部细条（标题 + 图标组）+ 消息流 + composer。
// ?session=N 查询参数决定打开哪个会话（静态导出不支持 [sessionId] 段）。
import { Suspense, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { useApp } from "@/lib/app-state";
import { MessageList } from "@/components/message-list";
import { ChatComposer } from "@/components/chat-composer";

function ChatInner() {
  const params = useSearchParams();
  const sessionId = params.get("session");
  const { openSession, messages, currentSessionId, sessions } = useApp();

  // 路由带会话号 → 打开它（回放 or 续聊）
  useEffect(() => {
    const id = sessionId ? Number(sessionId) : null;
    if (id != null && !Number.isNaN(id) && id !== currentSessionId) {
      void openSession(id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const summary = sessions.find((s) => s.id === currentSessionId);
  const title = summary
    ? summary.note || `${summary.task_type} #${summary.id}`
    : currentSessionId != null
      ? `会话 #${currentSessionId}`
      : "New chat";

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* 顶部细条（TeachX 同款：左标题 + 右图标组） */}
      <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border px-5">
        <h1 className="font-serif text-[15px] font-medium">{title}</h1>
        <span className="rounded-full border border-border px-2 py-0.5 text-[10.5px] text-muted-foreground">
          {summary ? summary.task_type : "chat"}
        </span>
        <div className="flex-1" />
        <span className="text-[11.5px] text-muted-foreground/60">
          {summary?.status === "running" ? "生成中…" : ""}
        </span>
      </div>

      <MessageList />

      <div className="shrink-0 px-6 pb-4">
        <div className="mx-auto max-w-[760px]">
          <ChatComposer compact />
        </div>
      </div>
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense fallback={<div className="flex-1" />}>
      <ChatInner />
    </Suspense>
  );
}
