"use client";

// 日程页：临近截止列表（紧迫度色点 + 原文链接）。
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { DeadlineItem } from "@/lib/types";

const dotColor = (r: number) =>
  r <= 1 ? "bg-[#d92d20]" : r <= 3 ? "bg-[#e5940f]" : r <= 7 ? "bg-[#d4b106]" : "bg-muted";

export default function DeadlinesPage() {
  const [items, setItems] = useState<DeadlineItem[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.deadlines()
      .then((d) => setItems(d.deadlines))
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-8 py-6">
      <h1 className="font-serif text-xl font-medium">截止日程</h1>
      {error && <div className="mt-4 text-[13.5px] text-destructive">注意：{error}</div>}
      {!items && !error && <div className="mt-4 text-[13.5px] text-muted-foreground">加载中…</div>}
      {items && items.length === 0 && (
        <div className="mt-4 text-[13.5px] text-muted-foreground">未来 30 天没有临近截止的比赛。</div>
      )}
      <div className="mt-5 flex max-w-[860px] flex-col">
        {items?.map((d) => (
          <a key={d.url} href={d.url} target="_blank" rel="noreferrer"
             className="flex items-center gap-3 rounded-xl px-3 py-3 text-[14px] transition-colors hover:bg-muted">
            <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${dotColor(d.remaining)}`} />
            <span className="flex-1 truncate">
              {d.name}
              <span className="ml-2 text-[12.5px] text-muted-foreground">{d.label}</span>
            </span>
            <span className="text-[12.5px] text-muted-foreground">{d.deadline}</span>
          </a>
        ))}
      </div>
    </div>
  );
}
