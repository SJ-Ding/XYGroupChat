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
};
export type Memory = {
  key: string;
  content: string;
  sources: number[];
  manual: boolean;
  updated: number;
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
};
export type Activity = {
  logs: { reason: string; at: number; source: number }[];
  failed: { key: string; error: string; mention: boolean }[];
};
export type Panel = "memory" | "tasks" | "settings" | "members" | null;
