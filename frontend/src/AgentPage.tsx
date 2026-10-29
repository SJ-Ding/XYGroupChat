import React, { useCallback, useEffect, useState } from "react";
import {
  Bot,
  RefreshCw,
  Settings,
  ArrowLeft,
  Activity,
  Clock,
  CheckCircle,
  AlertCircle,
} from "lucide-react";
import { api, base, post } from "./api";

type Execution = {
  key: string;
  source: number;
  phase: string;
  started: number;
};
type Job = {
  key: string;
  source: number;
  preview: string;
  status: string;
  mention: boolean;
  updated: number;
  error?: string;
};
type Demand = {
  key: string;
  source: number;
  text: string;
  target?: string;
  status: string;
  deadline: number;
  candidate?: string;
  version: number;
  error?: string;
};
type Status = {
  server_time: number;
  name: string;
  scheduler: {
    state: string;
    started_at: number | null;
    heartbeat: number | null;
    error: string | null;
  };
  model: { name: string; configured: boolean };
  behavior: {
    active: boolean;
    wait_seconds: number;
    version: number;
    blocked: boolean;
  };
  counts: {
    running: number;
    pending: number;
    done: number;
    failed: number;
    observing: number;
  };
  executions: Execution[];
  jobs: Job[];
  demands: Demand[];
  logs: { reason: string; source: number | null; at: number }[];
  skills: { name: string; description: string; writes: boolean }[];
  tool_runs: { key: string; name: string; at: number; result: string }[];
  reminders: { key: string; content: string; at: number }[];
};
const labels: Record<string, string> = {
  pending: "排队中",
  running: "执行中",
  done: "已完成",
  failed: "失败",
  waiting: "观察中",
  sent: "已跟进",
  resolved: "已回应",
  cancelled: "已取消",
  analyzing: "分析聊天",
  replying: "生成回复",
  candidate: "预生成候选回复",
  summarizing: "检查历史摘要",
  starting: "启动中",
  stopped: "已停止",
  degraded: "运行异常",
};
const stamp = (t: number | null) =>
  t
    ? new Date(t * 1000).toLocaleString("zh-CN", {
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "暂无";
export default function AgentPage({
  onBack,
  onSettings,
  onSource,
}: {
  onBack: () => void;
  onSettings: () => void;
  onSource: (id: number) => void;
}) {
  const [data, setData] = useState<Status | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false),
    [retrying, setRetrying] = useState<string | null>(null),
    [tab, setTab] = useState("jobs");
  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const status = await api<Status>(base + "/agent/status", { signal });
      if (!signal?.aborted) {
        setData(status);
        setError("");
      }
    } catch (e) {
      if (!signal?.aborted) setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      await load(controller.signal);
      if (!controller.signal.aborted) timer = setTimeout(poll, 2000);
    }
    poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [load]);
  async function refresh() {
    setLoading(true);
    await load();
    setLoading(false);
  }
  async function retry(key: string) {
    setRetrying(key);
    try {
      await api(base + "/retry/" + encodeURIComponent(key), post({}));
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRetrying(null);
    }
  }
  const state = data?.scheduler.state;
  const overall =
    state !== "running"
      ? labels[state || "starting"]
      : data!.executions.length
        ? "正在执行"
        : data!.behavior.blocked
          ? "需要处理失败任务"
          : data!.counts.observing
            ? "正在观察聊天"
            : "空闲待命";
  return (
    <section className="agent-page">
      <header className="agent-page-header">
        <div>
          <span className="agent-page-icon">
            <Bot size={25} />
          </span>
          <div>
            <h1>Agent 运行状态</h1>
            <p>{data?.name || "小忆"} · 家庭助手</p>
          </div>
        </div>
        <div>
          <button className="secondary" onClick={onBack}>
            <ArrowLeft size={16} />
            <span>返回聊天</span>
          </button>
          <button className="secondary" onClick={onSettings}>
            <Settings size={16} />
            <span>设置</span>
          </button>
        </div>
      </header>
      <div className="agent-page-body">
        <div className="agent-monitor-toolbar">
          <span>
            <i
              className={
                "dot " + (state === "running" && !error ? "online" : "")
              }
            />
            {error ? "状态连接中断" : overall || "加载中…"}
          </span>
          <button onClick={refresh} disabled={loading}>
            <RefreshCw size={15} className={loading ? "spin" : ""} />
            刷新
          </button>
          <small>
            每 2 秒自动刷新 · {data ? stamp(data.server_time) : "正在获取状态"}
          </small>
        </div>
        {error && (
          <div role="alert" className="monitor-alert">
            状态获取失败：{error}。
            {data ? "以下为上次成功获取的数据。" : "请稍后刷新重试。"}
          </div>
        )}
        {!data && !error && (
          <div className="monitor-empty">正在读取 Agent 状态…</div>
        )}
        {data && (
          <>
            <div className="monitor-metrics">
              {[
                [Activity, "当前执行", data.counts.running],
                [Clock, "排队任务", data.counts.pending],
                [Bot, "观察需求", data.counts.observing],
                [AlertCircle, "失败任务", data.counts.failed],
                [CheckCircle, "已完成", data.counts.done],
              ].map(([Icon, label, value]) => {
                const C = Icon as typeof Bot;
                return (
                  <div key={String(label)}>
                    <C size={18} />
                    <span>{String(label)}</span>
                    <strong>{String(value)}</strong>
                  </div>
                );
              })}
            </div>
            <div className="monitor-health">
              <div>
                <strong>后台调度器</strong>
                <p>
                  {state === "running" ? "运行中" : labels[state || "starting"]}{" "}
                  · 心跳 {stamp(data.scheduler.heartbeat)}
                </p>
                <small>
                  启动于 {stamp(data.scheduler.started_at)}
                  {data.scheduler.error ? " · " + data.scheduler.error : ""}
                </small>
              </div>
              <div>
                <strong>{data.model.name}</strong>
                <p>
                  {data.model.configured
                    ? "模型密钥已配置"
                    : "尚未配置模型密钥"}
                </p>
                <small>此处显示配置状态，不代表模型连接探测结果</small>
              </div>
              <div>
                <strong>
                  自主跟进{data.behavior.active ? "已开启" : "已关闭"}
                </strong>
                <p>
                  观察 {data.behavior.wait_seconds} 秒 · 配置 v
                  {data.behavior.version}
                </p>
                <small>先生成候选，再等待发送；全天启用</small>
              </div>
            </div>
            {data.behavior.blocked && (
              <div className="monitor-alert">
                存在尚未成功分析的聊天，自主跟进暂缓。请在任务列表中重试失败任务。
              </div>
            )}
            {data.executions.length > 0 && (
              <section className="monitor-section">
                <h2>正在进行</h2>
                {data.executions.map((x, i) => (
                  <div className="monitor-row" key={x.key + ":" + i}>
                    <span className="status-tag running">
                      {labels[x.phase] || x.phase}
                    </span>
                    <span>开始于 {stamp(x.started)}</span>
                    <button onClick={() => onSource(x.source)}>
                      查看来源消息 #{x.source}
                    </button>
                  </div>
                ))}
              </section>
            )}
            <nav className="monitor-tabs" aria-label="运行记录">
              {[
                ["jobs", "处理任务"],
                ["demands", "主动跟进"],
                ["logs", "决策记录"],
                ["skills", "Skill 与提醒"],
              ].map(([key, label]) => (
                <button
                  key={key}
                  className={tab === key ? "selected" : ""}
                  onClick={() => setTab(key)}
                >
                  {label}
                </button>
              ))}
            </nav>
            {tab === "jobs" && (
              <section className="monitor-section">
                <h2>
                  处理任务 <small>优先展示待处理与失败任务，最多 30 条</small>
                </h2>
                {!data.jobs.length && (
                  <p className="monitor-empty">
                    暂无处理任务，家人发送消息后会显示在这里。
                  </p>
                )}
                {data.jobs.map((j) => (
                  <article className="monitor-job" key={j.key}>
                    <div>
                      <span className={"status-tag " + j.status}>
                        {labels[j.status] || j.status}
                      </span>
                      <span>
                        {j.mention ? "@ 提及回复" : "聊天分析与记忆提取"}
                      </span>
                      <small>{stamp(j.updated)}</small>
                    </div>
                    <p>{j.preview || "图片消息"}</p>
                    {j.error && <p className="monitor-error">{j.error}</p>}
                    <footer>
                      <button onClick={() => onSource(j.source)}>
                        来源消息 #{j.source}
                      </button>
                      {j.status === "failed" && (
                        <button
                          disabled={retrying !== null}
                          onClick={() => retry(j.key)}
                        >
                          <RefreshCw size={14} />
                          {retrying === j.key ? "正在重试…" : "重试任务"}
                        </button>
                      )}
                    </footer>
                  </article>
                ))}
              </section>
            )}
            {tab === "demands" && (
              <section className="monitor-section">
                <h2>
                  主动跟进 <small>候选内容只在满足发送条件后才进入群聊</small>
                </h2>
                {!data.demands.length && (
                  <p className="monitor-empty">暂无识别到的跟进需求。</p>
                )}
                {data.demands.map((d) => (
                  <article className="monitor-job" key={d.key}>
                    <div>
                      <span className={"status-tag " + d.status}>
                        {labels[d.status] || d.status}
                      </span>
                      <span>{d.target || "家庭成员"}</span>
                      <small>版本 {d.version}</small>
                    </div>
                    <p>{d.text}</p>
                    {d.status === "waiting" && (
                      <p className="field-help">
                        {d.deadline > data.server_time
                          ? `距离最早发送约 ${Math.ceil(d.deadline - data.server_time)} 秒`
                          : "观察窗口已结束，等待生成或发送前核验"}{" "}
                        ·{" "}
                        {d.candidate
                          ? "候选已生成，尚未发送"
                          : "候选生成中或等待生成"}
                      </p>
                    )}
                    {d.candidate && (
                      <details>
                        <summary>查看候选回复</summary>
                        <p className="monitor-candidate">{d.candidate}</p>
                      </details>
                    )}
                    {d.error && <p className="monitor-error">{d.error}</p>}
                    <footer>
                      <button onClick={() => onSource(d.source)}>
                        查看来源消息 #{d.source}
                      </button>
                      {d.status === "failed" && (
                        <button
                          disabled={retrying !== null}
                          onClick={() => retry("demand:" + d.key)}
                        >
                          重试生成
                        </button>
                      )}
                    </footer>
                  </article>
                ))}
              </section>
            )}
            {tab === "logs" && (
              <section className="monitor-section">
                <h2>
                  最近决策 <small>最多 40 条</small>
                </h2>
                {!data.logs.length && (
                  <p className="monitor-empty">暂无决策记录。</p>
                )}
                {data.logs.map((l, i) => (
                  <div className="monitor-log" key={l.at + ":" + i}>
                    <time>{stamp(l.at)}</time>
                    <p>{l.reason}</p>
                    {l.source && (
                      <button onClick={() => onSource(l.source!)}>
                        查看来源
                      </button>
                    )}
                  </div>
                ))}
              </section>
            )}
            {tab === "skills" && (
              <section className="monitor-section">
                <h2>已加载 Skill</h2>
                <div className="monitor-skills">
                  {data.skills.map((s) => (
                    <div key={s.name}>
                      <strong>{s.name}</strong>
                      <span className="status-tag">
                        {s.writes ? "包含写入能力" : "只读"}
                      </span>
                      <p>{s.description}</p>
                    </div>
                  ))}
                </div>
                <h2>待发送提醒</h2>
                {!data.reminders.length && (
                  <p className="monitor-empty">暂无待发送的群内提醒。</p>
                )}
                {data.reminders.map((r) => (
                  <div className="monitor-log" key={r.key}>
                    <time>{stamp(r.at)}</time>
                    <p>{r.content}</p>
                  </div>
                ))}
                <h2>最近 Skill 执行</h2>
                {!data.tool_runs.length && (
                  <p className="monitor-empty">暂无 Skill 执行记录。</p>
                )}
                {data.tool_runs.map((r) => (
                  <details className="monitor-tool" key={r.key}>
                    <summary>
                      {r.name} · {stamp(r.at)}
                    </summary>
                    <pre>{r.result}</pre>
                  </details>
                ))}
              </section>
            )}
          </>
        )}
      </div>
    </section>
  );
}
