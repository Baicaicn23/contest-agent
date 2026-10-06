"use client";

// 应用框架（M11，TeachX AppShell 的移植）：侧栏 + 主区。
// 侧栏可折叠（localStorage 记忆）；全局状态 Provider 挂在这里，
// 页面切换（工作台 ↔ 聊天）不卸载它，流式回答因此跨页面不断线。
import { useEffect, useState } from "react";
import { PanelLeft } from "lucide-react";
import { AppStateProvider } from "@/lib/app-state";
import { Sidebar } from "@/components/sidebar";

export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(
    () => typeof window !== "undefined" && localStorage.getItem("ca-side-collapsed") === "1",
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        setCollapsed((c) => {
          localStorage.setItem("ca-side-collapsed", c ? "0" : "1");
          return !c;
        });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const toggle = () =>
    setCollapsed((c) => {
      localStorage.setItem("ca-side-collapsed", c ? "0" : "1");
      return !c;
    });

  return (
    <AppStateProvider>
      <div className="flex h-dvh overflow-hidden bg-background">
        {collapsed ? (
          <button
            onClick={toggle}
            title="展开侧栏（⌘B）"
            className="fixed left-3 top-3 z-50 flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-card text-muted-foreground shadow-sm transition-colors hover:bg-muted"
          >
            <PanelLeft size={15} strokeWidth={1.7} />
          </button>
        ) : (
          <Sidebar onCollapse={toggle} />
        )}
        <main className="flex min-w-0 flex-1 flex-col overflow-hidden">{children}</main>
      </div>
    </AppStateProvider>
  );
}
