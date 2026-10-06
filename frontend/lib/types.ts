// 全局类型定义（M11 TS 迁移）：与后端 FastAPI 的响应结构一一对应。

export interface SessionSummary {
  id: number;
  task_type: string;
  note: string;
  status: string; // running / completed / failed / budget_break
  started_at: string | null;
  ended_at: string | null;
  event_count: number;
  cost_yuan: number | null;
  llm_calls: number;
  prompt_tokens: number | null;
  project_key: string | null;
}

export interface ModelInfo {
  name: string;
  model: string;
  has_key: boolean;
  input_price_per_m: number;
  output_price_per_m: number;
}

export interface AppConfig {
  active_model: string;
  models: ModelInfo[];
  routing: Record<string, string>;
  budget_per_task_yuan: number | null;
  permissions: {
    permission_mode: string; // readonly / confirm / full
    confirm_tools: string[];
    unattended_deny_tools: string[];
  };
  push: { webhook: boolean; file_dir: string; smtp: boolean };
  context_trigger_ratio: number;
  access_full: boolean;
  permission_mode: string;
  features: Record<string, boolean>;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  time?: string;
  error?: boolean;
  streaming?: boolean;
  tool?: boolean;
  toolName?: string;
  toolArgs?: Record<string, unknown>;
}

export interface ProjectInfo {
  key: string;
  name: string;
  source: string; // auto / manual
  deadline: string | null;
  sessions: number;
}

export interface DeadlineItem {
  name: string;
  label: string;
  remaining: number;
  deadline: string;
  url: string;
}

export interface NotificationData {
  urgent_deadlines: { name: string; label: string; remaining: number }[];
  completed_recently: number;
}

export interface SkillInfo {
  file: string;
  name: string;
  description: string;
}

export interface PluginInfo {
  id: string;
  name: string;
  desc: string;
  category: string;
  enabled: boolean;
  toggleable: boolean;
}

export interface UsageSummary {
  range: string;
  totals?: Record<string, unknown>;
}

export type PermissionMode = "readonly" | "confirm" | "full";
