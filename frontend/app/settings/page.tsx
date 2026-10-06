"use client";

// 设置页：模型档案 / 单任务预算 / 三档权限 / 桌面通知 / 路由只读 / 输出目录。
// 与 composer 的权限选择同一真相（permission_mode）。
import { useEffect, useState } from "react";
import { useApp } from "@/lib/app-state";
import { api } from "@/lib/api";

const MODE_LABELS: Record<string, string> = {
  readonly: "只读",
  confirm: "变更前确认",
  full: "完全访问",
};

export default function SettingsPage() {
  const { config, refreshConfig, permissionMode, changePermissionMode, desktopNotify, toggleDesktopNotify } = useApp();
  const [budget, setBudget] = useState<string>("");
  const [hint, setHint] = useState("");

  useEffect(() => {
    setBudget(config?.budget_per_task_yuan?.toString() ?? "");
  }, [config]);

  const saveBudget = async () => {
    const v = budget.trim();
    const yuan = v === "" || v === "null" ? null : Number(v);
    if (yuan !== null && (Number.isNaN(yuan) || yuan < 0)) {
      setHint("预算要是非负数字，或留空表示不限");
      return;
    }
    try {
      await api.setBudget(yuan);
      setHint("已保存 ✓");
      await refreshConfig();
    } catch (e) {
      setHint((e as Error).message);
    }
  };

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-8 py-6">
      <h1 className="font-serif text-xl font-medium">设置</h1>

      <Section title="常规">
        <Row label="模型档案" desc="当前生效：切换写回 config.yaml，CLI 同样生效。">
          <select
            className="w-[300px] rounded-lg border border-border bg-card px-3 py-2 text-[13.5px] outline-none transition-colors focus:border-ring"
            value={config?.active_model ?? ""}
            onChange={async (e) => {
              await api.switchModel(e.target.value);
              await refreshConfig();
            }}
          >
            {(config?.models ?? []).map((m) => (
              <option key={m.name} value={m.name}>
                {m.name}（{m.model}{m.has_key ? "" : "，缺密钥"}）
              </option>
            ))}
          </select>
        </Row>
        <Row label="单任务预算上限（元）" desc={`一次任务花费达到上限就熔断；留空不限。${hint}`}>
          <div className="flex gap-2">
            <input
              className="w-[220px] rounded-lg border border-border bg-card px-3 py-2 text-[13.5px] outline-none transition-colors focus:border-ring"
              value={budget} placeholder="留空不限"
              onChange={(e) => setBudget(e.target.value)}
            />
            <button onClick={() => void saveBudget()}
                    className="rounded-lg bg-primary px-4 py-2 text-[13.5px] text-primary-foreground transition-opacity hover:opacity-90">
              保存
            </button>
          </div>
        </Row>
        <Row label="输出目录" desc="生成的材料与报告默认存放的位置。">
          <span className="font-mono text-[13px] text-muted-foreground">output/</span>
        </Row>
      </Section>

      <Section title="权限">
        <Row label="三档权限" desc="只读：写类工具一律拒绝；变更前确认：写类工具执行前需要确认（网页聊天无法弹窗，会自动拦截）；完全访问：全部工具自动放行。与输入卡上的选择同一真相。">
          <div className="flex rounded-xl bg-muted p-1">
            {Object.entries(MODE_LABELS).map(([mode, label]) => (
              <button key={mode}
                      onClick={() => void changePermissionMode(mode as "readonly" | "confirm" | "full")}
                      className={`rounded-lg px-4 py-1.5 text-[13px] transition-colors ${
                        permissionMode === mode ? "bg-card font-medium shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>
                {label}
              </button>
            ))}
          </div>
        </Row>
        <Row label="桌面截止提醒" desc="比赛进入警报窗口时弹系统通知（60 秒轮询，只报新增）。">
          <button onClick={() => void toggleDesktopNotify()}
                  className={`relative h-6 w-11 rounded-full transition-colors ${desktopNotify ? "bg-primary" : "bg-border"}`}
                  role="switch" aria-checked={desktopNotify}>
            <span className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
              desktopNotify ? "translate-x-5" : ""}`} />
          </button>
        </Row>
      </Section>

      <Section title="路由（只读）">
        <div className="text-[13.5px] leading-[2] text-muted-foreground">
          {Object.entries(config?.routing ?? {}).map(([task, profile]) => (
            <div key={task}><b className="font-medium text-foreground">{task}</b> → {profile}</div>
          ))}
        </div>
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-8 max-w-[860px]">
      <h2 className="mb-2 text-[15px] font-semibold">{title}</h2>
      <div className="rounded-2xl border border-border">{children}</div>
    </div>
  );
}

function Row({ label, desc, children }: { label: string; desc: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-6 border-b border-border/60 px-5 py-4 last:border-b-0">
      <div>
        <div className="text-[14px] font-medium">{label}</div>
        <div className="mt-1 max-w-[420px] text-[12.5px] leading-relaxed text-muted-foreground">{desc}</div>
      </div>
      <div className="shrink-0 pt-1">{children}</div>
    </div>
  );
}
