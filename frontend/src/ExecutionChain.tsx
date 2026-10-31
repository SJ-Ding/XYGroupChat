import React, { useEffect, useState } from "react";
import { api, base } from "./api";
type Step = {
  id: string;
  run_id: string;
  title: string;
  status: string;
  summary: string;
  started: number | null;
  ended: number | null;
  attempt: number;
};
type Chain = {
  steps: Step[];
  tasks: { id: string; status: string; reply_status?: string }[];
};
const labels: Record<string, string> = {
  queued: "等待执行",
  running: "执行中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
  waiting_input: "等待补充信息",
  waiting_authorization: "等待授权",
};
export function useExecutionChains(ids: string, enabled: boolean) {
  const [rows, setRows] = useState<Record<string, Chain>>({});
  const [error, setError] = useState("");
  useEffect(() => {
    setError("");
    if (!enabled || !ids) {
      setRows({});
      return;
    }
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let fetching = false;
    async function poll() {
      if (fetching || controller.signal.aborted) return;
      fetching = true;
      clearTimeout(timer);
      try {
        const collected: Record<string, Chain> = {};
        const numbers = ids.split(",");
        for (let i = 0; i < numbers.length; i += 100)
          Object.assign(
            collected,
            await api(
              base + "/agent/chains?ids=" + numbers.slice(i, i + 100).join(","),
              { signal: controller.signal },
            ),
          );
        if (!controller.signal.aborted) {
          setRows(collected);
          setError("");
        }
      } catch (e) {
        if (!controller.signal.aborted) setError((e as Error).message);
      } finally {
        fetching = false;
        if (!controller.signal.aborted) timer = setTimeout(poll, 2000);
      }
    }
    const update = (event: Event) => {
      const type = (event as CustomEvent).detail?.type;
      if (["chain_update", "task_update", "agent", "reset"].includes(type))
        void poll();
    };
    void poll();
    addEventListener("xy-event", update);
    return () => {
      controller.abort();
      clearTimeout(timer);
      removeEventListener("xy-event", update);
    };
  }, [ids, enabled]);
  return { rows, error };
}
export function ExecutionChain({
  source,
  chain,
}: {
  source: number;
  chain?: Chain;
}) {
  if (!chain || (!chain.steps.length && !chain.tasks.length)) return null;
  const last = chain.steps[chain.steps.length - 1];
  const waiting = chain.tasks.find((t) =>
    [
      "waiting_input",
      "waiting_authorization",
      "queued",
      "running",
      "cancelled",
      "failed",
    ].includes(t.status),
  );
  const state = waiting?.status || last?.status || "queued";
  return (
    <details className="execution-chain" id={"execution-chain-" + source}>
      <summary>
        <span>小艺正在做什么</span>
        <span>
          {labels[state] || state} · {last?.title || "等待执行"}
        </span>
      </summary>
      {!chain.steps.length && <p>此任务的详细过程未记录</p>}
      <ol>
        {chain.steps.map((step) => (
          <li key={step.id} data-status={step.status}>
            <div>
              <strong>{step.title}</strong>
              <span>{labels[step.status] || step.status}</span>
            </div>
            <p>
              {step.summary || "正在处理"} ·{" "}
              {step.started && step.ended
                ? Math.max(0, step.ended - step.started).toFixed(1) + " 秒"
                : step.started
                  ? "计时中"
                  : "耗时未记录"}
              {step.attempt > 1 ? " · 第 " + step.attempt + " 次执行" : ""}
            </p>
          </li>
        ))}
      </ol>
      {chain.tasks.map((task) => (
        <p key={task.id}>
          任务：{labels[task.status] || task.status}
          {task.reply_status === "failed" ? " · 回复发送失败" : ""}
        </p>
      ))}
    </details>
  );
}
