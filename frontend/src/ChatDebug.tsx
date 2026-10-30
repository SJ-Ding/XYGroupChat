import React, { useEffect, useState } from "react";
import { api, base } from "./api";
export type Annotation = {
  decision?: { action: string; reason: string; topic: string } | null;
  intent?: {
    kind: string;
    target: string;
    confidence: number;
    quoted: boolean;
  } | null;
  status?: string;
  source?: number;
  trace_keys?: string[];
};
const kinds: Record<string, string> = {
  request: "求助",
  discussion: "日常交流",
  emotional: "情绪表达",
  joke: "玩笑",
  cancel: "取消",
  feedback: "反馈",
};
const targets: Record<string, string> = {
  agent: "面向助手",
  member: "面向家人",
  group: "面向家庭群",
  unknown: "对象不明",
};
export function useChatAnnotations(ids: string, enabled: boolean) {
  const [rows, setRows] = useState<Record<string, Annotation>>({});
  const [error, setError] = useState("");
  useEffect(() => {
    if (!enabled || !ids) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const numbers = ids.split(",");
        const collected: Record<string, Annotation> = {};
        for (let i = 0; i < numbers.length; i += 100)
          Object.assign(
            collected,
            await api<Record<string, Annotation>>(
              base +
                "/agent/annotations?ids=" +
                numbers.slice(i, i + 100).join(","),
              { signal: controller.signal },
            ),
          );
        if (!controller.signal.aborted) {
          setRows(collected);
          setError("");
        }
      } catch (e) {
        if (!controller.signal.aborted) setError((e as Error).message);
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 2000);
    }
    poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [ids, enabled]);
  return { rows, error };
}
export function ChatAnnotation({
  agent,
  annotation: row,
  open,
}: {
  agent: boolean;
  annotation?: Annotation;
  open: (source: number, keys?: string[]) => void;
}) {
  if (agent)
    return (
      <div className="chat-debug-note">
        {row?.source ? (
          <button onClick={() => open(row.source!, row.trace_keys || [])}>
            查看上下文
          </button>
        ) : (
          <span>暂无关联的生成上下文</span>
        )}
      </div>
    );
  const decision = row?.decision,
    intent = row?.intent;
  const label = decision
    ? { reply: "需要回复", observe: "等待观察", silent: "无需回复" }[
        decision.action
      ] || decision.action
    : row?.status === "failed"
      ? "分析失败"
      : row?.status === "pending"
        ? "等待分析"
        : "暂无分类记录";
  return (
    <div className="chat-debug-note">
      <div className="chat-debug-tags">
        <span className={"decision-chip " + (decision?.action || "unknown")}>
          {label}
        </span>
        {intent && (
          <>
            <span>{kinds[intent.kind] || intent.kind}</span>
            <span>{targets[intent.target] || intent.target}</span>
            <span>置信度 {Math.round(intent.confidence * 100)}%</span>
            {intent.quoted && <span>引用内容</span>}
          </>
        )}
        {decision?.topic && <span>话题：{decision.topic}</span>}
      </div>
      {decision?.reason && <p>{decision.reason}</p>}
    </div>
  );
}
