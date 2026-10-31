export type User = {
  id: number;
  name: string;
  username?: string;
  online?: boolean;
  authenticated?: boolean;
};
export type Message = {
  id: number;
  user_id: number;
  name: string;
  content: string;
  attachments: string[];
  created: number;
  client_id: string;
  cards?: ChatCard[];
  hidden?: boolean;
};
export type Memory = {
  version?: number;
  key: string;
  content: string;
  sources: number[];
  manual: boolean;
  updated: number;
  lifetime?: "working" | "short" | "long";
  expires_at?: number | null;
  tentative?: boolean;
};
export type MemoryStatus = {
  active: number;
  working: number;
  short: number;
  long: number;
  maintenance: {
    last_run: number | null;
    next_due: number;
    runs: number;
    dirty: boolean;
    counts: Record<string, number>;
  } | null;
};
export type Task = {
  key: string;
  title: string;
  done: boolean;
  owner_id: number | null;
  due: number | null;
};
export type Config = {
  agent_name: string;
  prompt: string;
  active: boolean;
  wait_seconds: number;
  configured: boolean;
  model: string;
  cooldown_seconds?: number;
  context_budget?: number;
  care_group_limit?: number;
  participation_shadow?: boolean;
  memory_auto?: boolean;
  memory_short_days?: number;
  memory_review_seconds?: number;
};
export type Activity = {
  logs: { reason: string; at: number; source: number }[];
  failed: { key: string; error: string; mention: boolean }[];
};
export type Panel = "memory" | "tasks" | "settings" | "members" | null;

export type ChatCard = {
  id: string; message_id: number; kind: string; title: string; description: string;
  version: number; status: string; phase?: string; run_key?: string; amount?: string;
  items: {label: string; value: string}[];
  fields: {key: string; label: string; type: "text" | "number" | "select"; required: boolean; options: string[]}[];
  links: {label: string; url: string}[];
  steps?: {id: string; title: string; status: string}[];
  actions?: string[];
  submitted_values?: Record<string, string | number>;
  // 就医守护富卡片（仅可信后端生成）
  care?: { type: string; data: Record<string, any>; actions: string[] } | null;
};
export type AgentTask = {key: string; title: string; status: string; card_id: string; message_id: number; steps: {status: string}[]};
