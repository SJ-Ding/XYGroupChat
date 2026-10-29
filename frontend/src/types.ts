export type User = {
  id: number;
  name: string;
  username?: string;
  online?: boolean;
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
};
export type Activity = {
  logs: { reason: string; at: number; source: number }[];
  failed: { key: string; error: string; mention: boolean }[];
};
export type Panel = "memory" | "tasks" | "settings" | "members" | null;
