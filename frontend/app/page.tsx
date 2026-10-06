"use client";

// 工作台首页（TeachX 聊天主页形态）：serif 时段问候 + 居中大输入卡 + 建议行。
// 发送即发起流式（状态在 AppStateProvider 里跨页面存活），会话落地后自动
// 路由到 /chat?session=N。
import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Sparkles } from "lucide-react";
import { ChatComposer } from "@/components/chat-composer";
import { useApp } from "@/lib/app-state";
import { greeting } from "@/lib/format";

function HomeInner() {
  const router = useRouter();
  const params = useSearchParams();
  const { currentSessionId, startChat } = useApp();

  // 会话落地（session 帧回写 currentSessionId）→ 路由切到 /chat，
  // 流式状态在 Provider 里，切页不断线。
  useEffect(() => {
    if (currentSessionId != null) {
      router.replace(`/chat?session=${currentSessionId}`);
    }
  }, [currentSessionId, router]);

  // 从 /chat 点"新聊天"回来时清空运行时
  useEffect(() => {
    if (!params.get("session")) startChat();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const suggestions = ["识别最新通知", "看看今天花了多少钱", "查一下临近截止的比赛"];

  return (
    <div className="flex min-h-0 flex-1 flex-col items-center justify-center overflow-y-auto pb-[14vh]">
      <div className="flex w-full max-w-[760px] flex-col items-center px-6">
        <div className="mb-8 flex items-center gap-4">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-muted font-serif text-lg text-muted-foreground">
            {">_"}
          </span>
          <h1 className="font-serif text-[44px] font-medium leading-none tracking-tight">
            {greeting()}
          </h1>
        </div>

        <ChatComposer />

        {/* 建议行（TeachX StarterSuggestions 形态）：提示可用动作 */}
        <div className="mt-4 flex flex-wrap items-center justify-center gap-2 text-[12.5px] text-muted-foreground">
          <Sparkles size={13} />
          <span>试试：</span>
          {suggestions.map((s) => (
            <span key={s} className="rounded-full bg-muted px-2 py-0.5">{s}</span>
          ))}
          <span>（输入 / 唤起命令）</span>
        </div>
      </div>
    </div>
  );
}

export default function HomePage() {
  return (
    <Suspense fallback={<div className="flex-1" />}>
      <HomeInner />
    </Suspense>
  );
}
