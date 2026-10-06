"use client";

// 统计页：真实成本台账聚合（Overview 用量卡 + Models 明细）。
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface UsageData {
  range: string;
  total?: { calls: number; input_tokens: number; output_tokens: number; cost_yuan: number | null };
  by_task?: Record<string, { calls: number; input_tokens: number; output_tokens: number; cost_yuan: number | null }>;
  by_model?: Record<string, { calls: number; input_tokens: number; output_tokens: number; cost_yuan: number | null }>;
}

const fmtYuan = (v: number | null | undefined) =>
  v == null ? "—" : `¥${v.toFixed(4)}`;

export default function StatsPage() {
  const [data, setData] = useState<UsageData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.usageSummary("all").then((d) => setData(d as unknown as UsageData)).catch((e) => setError(e.message));
  }, []);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-8 py-6">
      <h1 className="font-serif text-xl font-medium">统计</h1>
      {error && <div className="mt-4 text-[13.5px] text-destructive">注意：{error}</div>}
      {!data && !error && <div className="mt-4 text-[13.5px] text-muted-foreground">加载中…</div>}
      {data?.total && (
        <>
          <div className="mt-5 grid max-w-[860px] grid-cols-3 gap-3">
            <Cell label="LLM 调用" value={`${data.total.calls} 次`} />
            <Cell label="输入 / 输出 token" value={`${data.total.input_tokens} / ${data.total.output_tokens}`} />
            <Cell label="总花费" value={fmtYuan(data.total.cost_yuan)} />
          </div>

          <h2 className="mb-2 mt-8 text-[13px] font-medium text-muted-foreground">按任务</h2>
          <Table
            rows={Object.entries(data.by_task ?? {}).map(([k, v]) => [k, `${v.calls} 次`, fmtYuan(v.cost_yuan)])}
            head={["任务", "调用", "花费"]}
          />

          <h2 className="mb-2 mt-8 text-[13px] font-medium text-muted-foreground">按模型</h2>
          <Table
            rows={Object.entries(data.by_model ?? {}).map(([k, v]) => [k, `${v.calls} 次`, fmtYuan(v.cost_yuan)])}
            head={["模型", "调用", "花费"]}
          />
        </>
      )}
    </div>
  );
}

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-muted p-4">
      <div className="text-[12.5px] text-muted-foreground">{label}</div>
      <div className="mt-1 text-[19px] font-semibold">{value}</div>
    </div>
  );
}

function Table({ head, rows }: { head: string[]; rows: string[][] }) {
  if (!rows.length) return <div className="text-[13px] text-muted-foreground">暂无数据。</div>;
  return (
    <table className="w-full max-w-[860px] border-collapse text-[13.5px]">
      <thead>
        <tr>{head.map((h) => <th key={h} className="border-b border-border px-3 py-2 text-left font-normal text-muted-foreground">{h}</th>)}</tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            {r.map((c, j) => <td key={j} className="border-b border-border/60 px-3 py-2">{c}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
