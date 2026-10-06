"use client";

// 插件页：能力开关（真实写 config features 段）+ Skills 清单。
import { useCallback, useEffect, useState } from "react";
import { Check, Plus } from "lucide-react";
import { api } from "@/lib/api";
import type { PluginInfo, SkillInfo } from "@/lib/types";

export default function PluginsPage() {
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [busy, setBusy] = useState("");

  const load = useCallback(() => {
    api.plugins().then((r) => setPlugins(r.plugins)).catch(() => {});
    api.skills().then((r) => setSkills(r.skills)).catch(() => {});
  }, []);
  useEffect(load, [load]);

  const toggle = async (p: PluginInfo) => {
    if (!p.toggleable) return;
    setBusy(p.id);
    try {
      await api.togglePlugin(p.id, !p.enabled);
      load();
    } finally {
      setBusy("");
    }
  };

  const categories = [...new Set(plugins.map((p) => p.category))];

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-8 py-6">
      <h1 className="font-serif text-xl font-medium">插件</h1>
      <p className="mt-1 text-[13px] text-muted-foreground">
        能力开关真实写回 config.yaml；推送通道类插件需要在 config 配置后自动启用。
      </p>

      {categories.map((cat) => (
        <div key={cat} className="mt-7 max-w-[860px]">
          <h2 className="mb-2 text-[13px] font-medium text-muted-foreground">{cat}</h2>
          <div className="rounded-2xl border border-border">
            {plugins.filter((p) => p.category === cat).map((p) => (
              <div key={p.id} className="flex items-center gap-4 border-b border-border/60 px-5 py-3.5 last:border-b-0">
                <div className="flex-1">
                  <div className="flex items-center gap-2 text-[14px] font-medium">
                    {p.name}
                    {p.enabled && (
                      <span className="rounded-full border border-[#237a4b]/40 px-2 text-[10.5px] text-[#237a4b]">已安装</span>
                    )}
                  </div>
                  <div className="mt-0.5 text-[12.5px] text-muted-foreground">{p.desc}</div>
                </div>
                {p.toggleable ? (
                  <button onClick={() => void toggle(p)} disabled={busy === p.id}
                          title={p.enabled ? "点击卸载" : "点击安装"}
                          className={`flex h-8 w-8 items-center justify-center rounded-full border transition-colors ${
                            p.enabled
                              ? "border-[#237a4b]/40 text-[#237a4b] hover:bg-[#237a4b]/10"
                              : "border-border text-muted-foreground hover:bg-muted"}`}>
                    {busy === p.id ? "…" : p.enabled ? <Check size={14} /> : <Plus size={14} />}
                  </button>
                ) : (
                  <span className="text-[11.5px] text-muted-foreground/70">需配置</span>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}

      <div className="mt-7 max-w-[860px]">
        <h2 className="mb-2 text-[13px] font-medium text-muted-foreground">Skills</h2>
        <div className="rounded-2xl border border-border">
          {skills.map((s) => (
            <div key={s.file} className="flex items-center gap-4 border-b border-border/60 px-5 py-3 last:border-b-0">
              <div className="flex-1">
                <div className="text-[14px] font-medium">{s.name}</div>
                <div className="text-[12.5px] text-muted-foreground">{s.description}</div>
              </div>
              <span className="font-mono text-[11.5px] text-muted-foreground">{s.file}</span>
            </div>
          ))}
          {!skills.length && <div className="px-5 py-3 text-[13px] text-muted-foreground">skills/ 目录为空。</div>}
        </div>
      </div>
    </div>
  );
}
