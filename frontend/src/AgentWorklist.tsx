import React, { useCallback, useEffect, useState } from "react";
import { Clock, ListTodo, RefreshCw } from "lucide-react";
import { api, base } from "./api";
import { Empty } from "./components";

type Task = { key: string; title: string; status: string; source?: number; updated: number; deadline?: number; error?: string };
type Reminder = { key: string; content: string; at: number; status: string; clock?: string; weekdays?: number[]; timezone: string; channel: string; source?: number; start?: string; end?: string; detail?: string };
type Worklist = { tasks: Task[]; reminders: Reminder[] };
const labels: Record<string, string> = {
  pending: "待处理", queued: "排队中", running: "执行中", waiting: "等待跟进",
  waiting_input: "待补充信息", waiting_authorization: "待确认", failed: "执行失败",
  reply_failed: "回复失败", done: "已完成", succeeded: "已完成", cancelled: "已取消",
  resolved: "已处理", active: "待提醒", completed: "已调度", expired: "已过期", paused: "已暂停",
};
const activeTasks = new Set(["pending", "queued", "running", "waiting", "waiting_input", "waiting_authorization", "failed", "reply_failed"]);
const stamp = (at: number) => new Date(at * 1000).toLocaleString("zh-CN", {
  timeZone: "Asia/Shanghai", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
});

export default function AgentWorklist({ onSource }: { onSource: (id: number) => void }) {
  const [data, setData] = useState<Worklist | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("all");
  const [history, setHistory] = useState(true);
  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const result = await api<Worklist>(base + "/agent/worklist", { signal });
      if (!signal?.aborted) { setData(result); setError(""); }
    } catch (e) { if (!signal?.aborted) setError((e as Error).message); }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      await load(controller.signal);
      if (!controller.signal.aborted) timer = setTimeout(poll, 3000);
    }
    poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [load]);
  const tasks = (data?.tasks || []).filter(t => history || activeTasks.has(t.status));
  const reminders = (data?.reminders || []).filter(r => history || r.status === "active" || r.status === "paused");
  return <section className="agent-worklist" aria-label="Agent 待办与定时任务">
    <p className="panel-intro">小艺在当前聊天中处理的任务和已创建的定时提醒。时间按北京时间显示，服务运行时自动执行。</p>
    <div className="worklist-toolbar">
      <label><input type="checkbox" checked={history} onChange={e => setHistory(e.target.checked)} />显示历史记录</label>
      <button onClick={() => load()} aria-label="刷新待办清单"><RefreshCw size={15} />刷新</button>
    </div>
    <nav className="worklist-tabs" aria-label="待办类型">
      <button className={tab === "all" ? "selected" : ""} onClick={() => setTab("all")}><ListTodo size={16} />全部任务与提醒</button>
      <button className={tab === "tasks" ? "selected" : ""} onClick={() => setTab("tasks")}><ListTodo size={16} />Agent 待办 <span>{data?.tasks.filter(t => activeTasks.has(t.status)).length ?? 0}</span></button>
      <button className={tab === "reminders" ? "selected" : ""} onClick={() => setTab("reminders")}><Clock size={16} />定时任务 <span>{data?.reminders.filter(r => r.status === "active").length ?? 0}</span></button>
    </nav>
    {error && <p className="monitor-error" role="alert">{error}，请刷新重试{data ? "；下方保留上次数据。" : "。"}</p>}
    {!data && !error && <p role="status">正在加载待办清单…</p>}
    {data && (tab === "tasks" || tab === "all") && <>
      {tasks.map(t => <article className="worklist-card" key={t.key}>
        <span className={"status-tag " + t.status}>{labels[t.status] || t.status}</span>
        <p>{t.title}</p>
        {t.error && <p className="monitor-error">{t.error}</p>}
        <small>{t.deadline ? "跟进时间：" + stamp(t.deadline) : "更新：" + stamp(t.updated)}</small>
        {t.source && <button className="worklist-source" onClick={() => onSource(t.source!)}>查看聊天</button>}
      </article>)}
      {!tasks.length && <Empty icon={<ListTodo />} text="暂无 Agent 待办" detail={history ? "尚无任务记录。" : "小艺接受任务后，会在这里显示处理进度。"} />}
    </>}
    {data && (tab === "reminders" || tab === "all") && <>
      {reminders.map(r => <article className="worklist-card" key={r.key}>
        <span className={"status-tag " + r.status}>{labels[r.status] || r.status}</span>
        <time>{r.at ? stamp(r.at) : "尚未设置执行时间"}</time>
        <p>{r.content}</p>
        {r.detail && <small>{r.detail}</small>}
        {r.start && <small>计划日期：{r.start} 至 {r.end || "长期"}</small>}
        <small>{r.channel === "group" ? "群内提醒" : "个人提醒"}{r.clock ? ` · ${r.weekdays?.length && r.weekdays.length < 7 ? "每周" + r.weekdays.map(d => "一二三四五六日"[d]).join("、") : "每天"} ${r.clock}（${r.timezone}）` : " · 单次提醒"}</small>
        {r.source && <button className="worklist-source" onClick={() => onSource(r.source!)}>查看聊天</button>}
      </article>)}
      {!reminders.length && <Empty icon={<Clock />} text="暂无定时任务" detail={history ? "尚无提醒记录。" : "当前聊天中成功保存的提醒会显示在这里。"} />}
    </>}
  </section>;
}
