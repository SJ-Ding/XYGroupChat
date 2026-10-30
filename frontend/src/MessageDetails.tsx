import React, { useEffect, useState } from "react";
import { api, base } from "./api";

type Decision = { action: string; reason: string; topic: string };
type Trace = {
  key: string;
  phase: string;
  at: number;
  status: string;
  model: string;
  latency_ms?: number;
  error?: string;
  messages: {
    role: string;
    content: unknown;
    tool_calls?: unknown;
    tool_call_id?: string;
  }[];
  response?: unknown;
  tools: unknown[];
};
type Detail = {
  source: number;
  decision: Decision | null;
  jobs: Record<string, unknown>[];
  traces: Trace[];
  logs: { key: string; at: number; reason: string }[];
  demands: unknown[];
  runs: unknown[];
};
const action: Record<string, string> = {
  reply: "立即回复",
  observe: "等待家人回应",
  silent: "保持安静",
};
const phase: Record<string, string> = {
  analysis: "意图与记忆分析",
  reply: "回复生成",
  candidate: "主动跟进候选",
};
const status: Record<string, string> = {
  running: "执行中",
  done: "完成",
  failed: "失败",
  cancelled: "中断",
};
const json = (value: unknown) => JSON.stringify(value, null, 2);
function content(value: unknown) {
  if (typeof value !== "string") return json(value);
  try {
    return json(JSON.parse(value));
  } catch {
    return value;
  }
}
const time = (at: number) => new Date(at * 1000).toLocaleString("zh-CN");
function Evidence({ title, value }: { title: string; value: unknown }) {
  return (
    <details className="debug-evidence">
      <summary>{title}</summary>
      <pre>{json(value)}</pre>
    </details>
  );
}
export default function MessageDetails({
  source: selected,
  traceKeys,
  onSource,
}: {
  source: number;
  traceKeys?: string[];
  onSource: (id: number) => void;
}) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [detailError, setDetailError] = useState("");
  useEffect(() => {
    if (selected === null) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await api<Detail>(base + `/agent/messages/${selected}`, {
          signal: controller.signal,
        });
        if (!controller.signal.aborted) {
          setDetail({
            ...result,
            traces:
              traceKeys === undefined
                ? result.traces
                : result.traces.filter((t) => traceKeys.includes(t.key)),
          });
          setDetailError("");
        }
      } catch (e) {
        if (!controller.signal.aborted) setDetailError((e as Error).message);
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 2000);
    }
    setDetail(null);
    setDetailError("");
    poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [selected, traceKeys?.join(",")]);
  return (
    <div className="debug-detail">
      {selected === null ? (
        <p className="monitor-empty">
          选择左侧消息，查看决策、上下文及执行结果。
        </p>
      ) : (
        <>
          <div className="debug-detail-heading">
            <h2>消息 #{selected}</h2>
            <button onClick={() => onSource(selected)}>定位到聊天</button>
          </div>
          {detailError && (
            <p className="monitor-alert" role="alert">
              详情获取失败：{detailError}。已有数据为上次成功结果。
            </p>
          )}
          {!detail && !detailError && (
            <p className="monitor-empty">正在读取详情…</p>
          )}
          {detail && (
            <>
              {detail.decision ? (
                <div className="debug-decision">
                  <strong>
                    {action[detail.decision.action] || detail.decision.action}
                  </strong>
                  <p>{detail.decision.reason}</p>
                  <small>话题：{detail.decision.topic || "未识别"}</small>
                </div>
              ) : (
                <p className="monitor-empty">
                  尚无参与决策，可能仍在排队、分析失败或属于旧版记录。
                </p>
              )}
              <h2>处理状态与记忆变更</h2>
              {detail.jobs.length ? (
                detail.jobs.map((job, i) => (
                  <Evidence
                    key={i}
                    title={`任务 ${job.key} · ${job.status}`}
                    value={job}
                  />
                ))
              ) : (
                <p className="field-help">暂无处理任务记录。</p>
              )}
              <h2>模型调用与实际上下文</h2>
              {!detail.traces.length && (
                <p className="monitor-empty">
                  暂无上下文快照。此功能上线后的分析与回复调用才会记录，历史上下文无法还原。
                </p>
              )}
              {detail.traces.map((trace, i) => (
                <article className="debug-trace" key={trace.key}>
                  <h3>
                    {i + 1}. {phase[trace.phase] || trace.phase}{" "}
                    <span className={"status-tag " + trace.status}>
                      {status[trace.status] || trace.status}
                    </span>
                  </h3>
                  <small>
                    {time(trace.at)} · {trace.model} ·{" "}
                    {trace.latency_ms === undefined
                      ? "等待返回"
                      : `${trace.latency_ms} ms`}
                  </small>
                  {trace.error && (
                    <p className="monitor-error">{trace.error}</p>
                  )}
                  <details className="debug-evidence">
                    <summary>
                      实际请求上下文 · {trace.messages.length} 条
                    </summary>
                    {trace.messages.map((message, index) => (
                      <div key={index}>
                        <h4>
                          {index + 1} · {message.role}
                        </h4>
                        <pre>{content(message.content)}</pre>
                        {(message.tool_calls || message.tool_call_id) && (
                          <Evidence title="工具调用关联" value={message} />
                        )}
                      </div>
                    ))}
                    <Evidence title="可用工具定义" value={trace.tools} />
                  </details>
                  {trace.response !== undefined && (
                    <Evidence
                      title="模型返回（含分析依据 / 工具调用）"
                      value={trace.response}
                    />
                  )}
                </article>
              ))}
              {detail.runs.length > 0 && (
                <Evidence title="执行步骤与工具结果" value={detail.runs} />
              )}
              {detail.demands.length > 0 && (
                <Evidence title="主动跟进与候选回复" value={detail.demands} />
              )}
              {detail.logs.length > 0 && (
                <div>
                  <h2>决策事件</h2>
                  {detail.logs.map((log) => (
                    <p className="debug-event" key={log.key}>
                      <small>{time(log.at)}</small>
                      <br />
                      {log.reason}
                    </p>
                  ))}
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
