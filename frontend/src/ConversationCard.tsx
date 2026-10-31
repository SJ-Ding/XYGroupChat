import React, { useState } from "react";
import { Check, Loader2, CircleAlert, CirclePause, Minus } from "lucide-react";
import { api, base, clientId, post } from "./api";
import type { ChatCard, AgentTask } from "./types";
import { CareCard } from "./care/CareCard";
export const stateLabel: Record<string, string> = {
  queued: "排队中",
  running: "执行中",
  pending: "待执行",
  waiting_input: "待补充信息",
  waiting_authorization: "待审核",
  succeeded: "已完成",
  failed: "执行失败",
  cancelled: "已取消",
  resolved: "已处理",
  active: "信息",
};
export function ConversationCard({
  card,
  onUpdate,
}: {
  card: ChatCard;
  onUpdate: () => Promise<void>;
}) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      Object.entries(card.submitted_values || {}).map(([k, v]) => [
        k,
        String(v),
      ]),
    ),
  );
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [request, setRequest] = useState<{
    signature: string;
    id: string;
  } | null>(null);
  const actions = card.actions || [];
  const booking = card.kind === "intervention" && card.title.startsWith("门诊预约");
  async function act(action: string, link_index?: number) {
    if (busy) return;
    setBusy(true);
    setError("");
    setFieldErrors({});
    const parsed = Object.fromEntries(
      card.fields
        .filter((f) => values[f.key] !== undefined && values[f.key] !== "")
        .map((f) => [
          f.key,
          f.type === "number" ? Number(values[f.key]) : values[f.key],
        ]),
    );
    const payload = {
      action,
      version: card.version,
      values: parsed,
      link_index,
    };
    const signature = JSON.stringify(payload);
    const id = request?.signature === signature ? request.id : clientId();
    setRequest({ signature, id });
    // Open synchronously to preserve the user's browser gesture; navigate only after validation.
    const target =
      action === "open_link" ? window.open("about:blank", "_blank") : null;
    if (target) target.opener = null;
    try {
      await api(
        base + "/cards/" + encodeURIComponent(card.id) + "/actions",
        post({ ...payload, request_id: id }),
      );
      if (target && link_index !== undefined)
        target.location.href = card.links[link_index].url;
      await onUpdate();
    } catch (e) {
      target?.close();
      const err = e as Error & { fields?: Record<string, string> };
      setError(err.message);
      setFieldErrors(err.fields || {});
      await onUpdate().catch(() => {});
    } finally {
      setBusy(false);
    }
  }
  if (card.care) return <CareCard card={card} onUpdate={onUpdate} />;
  if (card.kind === "progress" && !card.fields.length &&
      !actions.some(a => ["confirm", "submit", "retry"].includes(a))) {
    const done = card.status === "succeeded";
    const paused = ["waiting_input", "waiting_authorization"].includes(card.status);
    const failed = card.status === "failed";
    const cancelled = card.status === "cancelled";
    const Icon = done ? Check : failed ? CircleAlert : paused ? CirclePause : cancelled ? Minus : Loader2;
    const text = done ? "已完成，请查看最新消息" :
      cancelled ? "任务已取消" : card.description || stateLabel[card.status] || "正在处理";
    return (
      <section className={`conversation-card progress-line${done ? " is-complete" : ""}${failed ? " is-failed" : ""}`}
        role="status" aria-live="polite" aria-atomic="true" aria-label={text}>
        <Icon size={16} className={!done && !paused && !failed && !cancelled ? "progress-spinner" : ""} aria-hidden="true" />
        <span title={text}>{text}</span>
      </section>
    );
  }
  return (
    <section
      className={`conversation-card card-${card.kind}${booking ? " card-booking" : ""}`}
      aria-label={card.title}
    >
      <div className="card-heading">
        <strong>{card.title}</strong>
        <span role="status">{stateLabel[card.status] || card.status}</span>
      </div>
      {card.description && (
        <p className="card-phase" role="status">
          {!["failed", "waiting_input", "waiting_authorization"].includes(
            card.status,
          ) &&
            card.kind === "progress" && (
              <span className="progress-pulse" aria-hidden="true" />
            )}
          {card.description}
        </p>
      )}
      {!!card.items.length && (
        <dl>
          {card.items.map((item, i) => (
            <React.Fragment key={i}>
              <dt>{item.label}</dt>
              <dd>{item.value}</dd>
            </React.Fragment>
          ))}
        </dl>
      )}
      {card.amount && (
        <div className="card-amount">
          金额 <strong>{card.amount}</strong>
        </div>
      )}
      {!!card.steps?.length && (
        <>
          <small>
            已完成 {card.steps.filter((s) => s.status === "succeeded").length} /{" "}
            {card.steps.length} 步
          </small>
          <ol>
            {card.steps.map((s) => (
              <li key={s.id}>
                <span>{s.title}</span>
                <small>{stateLabel[s.status] || s.status}</small>
              </li>
            ))}
          </ol>
        </>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void act(actions.includes("submit") ? "submit" : "confirm");
        }}
      >
        {card.fields.map((f) => (
          <label className="card-field" key={f.key}>
            {f.label}
            {f.required ? " *" : ""}
            {f.type === "select" ? (
              <select
                disabled={busy || !actions.includes("submit")}
                required={f.required}
                value={values[f.key] || ""}
                onChange={(e) =>
                  setValues({ ...values, [f.key]: e.target.value })
                }
              >
                <option value="">请选择</option>
                {f.options.map((o) => (
                  <option key={o}>{o}</option>
                ))}
              </select>
            ) : (
              <input
                disabled={busy || !actions.includes("submit")}
                required={f.required}
                type={f.type}
                step={f.type === "number" ? "any" : undefined}
                value={values[f.key] || ""}
                onChange={(e) =>
                  setValues({ ...values, [f.key]: e.target.value })
                }
              />
            )}
            {fieldErrors[f.key] && (
              <small role="alert">{fieldErrors[f.key]}</small>
            )}
          </label>
        ))}
        <div className="card-buttons">
          {actions
            .filter((a) => a !== "open_link")
            .map((a) => (
              <button
                disabled={busy}
                key={a}
                type={a === "submit" || a === "confirm" ? "submit" : "button"}
                onClick={
                  a === "submit" || a === "confirm"
                    ? undefined
                    : () => void act(a)
                }
              >
                {
                  (
                    {
                      submit: "提交信息",
                      confirm: booking ? "确认并继续" : "确认并继续",
                      cancel: "取消任务",
                      retry: "重试",
                    } as Record<string, string>
                  )[a]
                }
              </button>
            ))}
          {actions.includes("open_link") &&
            card.links.map((link, i) => (
              <button
                type="button"
                disabled={busy}
                key={i}
                onClick={() => void act("open_link", i)}
              >
                {link.label} ↗
              </button>
            ))}
        </div>
        {error && (
          <p className="card-error" role="alert">
            {error}
          </p>
        )}
      </form>
    </section>
  );
}
export function TaskBar({
  tasks,
  locate,
}: {
  tasks: AgentTask[];
  locate: (id: number) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const active = tasks
    .filter((t) => !["succeeded", "cancelled"].includes(t.status))
    .sort(
      (a, b) =>
        Number(b.status.startsWith("waiting")) -
        Number(a.status.startsWith("waiting")),
    );
  if (!active.length) return null;
  return (
    <aside className="agent-taskbar" aria-label="进行中的任务">
      <button
        className="task-summary"
        aria-expanded={expanded}
        onClick={() => setExpanded(!expanded)}
      >
        <strong>{active.length} 个任务</strong>
        <span>{active[0].title}</span>
        <small>
          {stateLabel[active[0].status]} {expanded ? "收起" : "展开"}
        </small>
      </button>
      {expanded && (
        <div className="task-list">
          {active.map((t) => (
            <button key={t.key} onClick={() => locate(t.message_id)}>
              <span>{t.title}</span>
              <small>
                {stateLabel[t.status]} ·{" "}
                {t.steps.length > 0
                  ? `${t.steps.filter((s) => s.status === "succeeded").length}/${t.steps.length} 步`
                  : ""}
              </small>
            </button>
          ))}
        </div>
      )}
    </aside>
  );
}
