// 家人帮 · 就医守护前端接口
import { useEffect, useRef, useState } from "react";
import { api, post } from "../api";

export type Level = "good" | "warn" | "bad" | "info" | "muted";

export type CareMember = {
  login: string; id: number; name: string; real_name: string; age: number; role: string;
  conditions: string[]; allergies: string[]; tag: string; level: Level; note: string;
  adherence: { title: string; taken: number; total: number; rate: number | null; missed: string[] } | null;
  plan: { title: string; type: string; taken: number; total: number; rate: number | null }[];
};
export type Dashboard = {
  clock: { ts: number; label: string; day: number };
  members: CareMember[];
  profile: { content: string; domain: string; type: string | null; subject: string }[];
  upcoming: { at: number; label: string; kind: string; when: string; paid?: boolean }[];
  week: { bookings: number; checkins: number; cards: number; emergencies: number };
};
export type TraceStep = { n: number; kind: string; label: string; detail: string; ms: number; at: number };
export type TraceTurn = { turn: string; title: string; at: number; real_at: number; ms: number; steps: TraceStep[] };
export type DemoStep = { key: string; title: string; actor: string; desc: string; next: string; done: boolean; line?: string | null };
export type DemoState = {
  clock: { ts: number; label: string; day: number; offset: number };
  steps: DemoStep[];
  model: { configured: boolean; name: string };
  amap: boolean;
  browser_headless: boolean;
  controls: { enabled: boolean; model: boolean; amap: boolean; slow: boolean };
  branches: { key: string; priority: string; title: string; actor: string; line: string }[];
  vision: string;
  model_last: { failed: boolean; at: number } | null;
  amap_last: { ok: boolean; at: number } | null;
  distance_sources: string[];
  browser_pause_ms: number;
  browser_tasks: { task_id: string; status: string; step: string; error: string | null }[];
};

export const careAct = (cardId: string, action: string, extra: Record<string, unknown> = {}) =>
  api(`/api/care/cards/${encodeURIComponent(cardId)}/act`, post({ action, ...extra }));

/** 订阅后端 WebSocket 事件（由 Chat 转发到 window）。 */
export function useXyEvents(handler: (e: { type: string }) => void) {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    const fn = (e: Event) => ref.current((e as CustomEvent).detail);
    addEventListener("xy-event", fn);
    return () => removeEventListener("xy-event", fn);
  }, []);
}

/** 定时 + 事件触发刷新的数据钩子（事件触发做 400ms 合并）。 */
export function useLive<T>(path: string, types: string[], interval = 15000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const load = () =>
    api<T>(path)
      .then((d) => { setData(d); setError(""); })
      .catch((e) => setError((e as Error).message));
  useEffect(() => {
    load();
    const t = setInterval(load, interval);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);
  useXyEvents((e) => {
    if (!types.includes(e.type)) return;
    clearTimeout(timer.current);
    timer.current = setTimeout(load, 400);
  });
  return { data, error, reload: load };
}

export function speak(text: string) {
  try {
    const synth = window.speechSynthesis;
    if (!synth) return false;
    synth.cancel();
    const clean = text.replace(/[\u{1F300}-\u{1FAFF}☀-➿]/gu, "").replace(/@\S+/g, "");
    const u = new SpeechSynthesisUtterance(clean);
    u.lang = "zh-CN";
    u.rate = 0.92;
    synth.speak(u);
    return true;
  } catch {
    return false;
  }
}
