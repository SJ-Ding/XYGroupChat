import React, { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, LockKeyhole, RefreshCw } from "lucide-react";
import { api, post, clientId } from "./api";
import Login from "./Login";

type Memory = {
  key: string;
  content: string;
  lifetime: string;
  scope: string;
  subjects: string[];
  expires_at: number | null;
  sources: number[];
};
type Step = {
  tool: string;
  arguments: Record<string, any>;
  status?: string;
  result?: any;
};
type Run = {
  key: string;
  title: string;
  status: string;
  steps: Step[];
  conversation?: boolean;
  source_id?: number;
  action_status?: string;
  reply_status?: string;
  reply_error?: string;
};
type Reminder = {
  key: string;
  content: string;
  at: number;
  clock?: string;
  weekdays?: number[];
  timezone: string;
  category: string;
  status: string;
  sent: boolean;
  share_health: boolean;
  respect_quiet: boolean;
  notify_user_id?: number;
  notify_after_minutes?: number;
};
type Subscription = {
  key: string;
  topic: string;
  clock: string;
  timezone: string;
  enabled: boolean;
  shadow: boolean;
  share_health: boolean;
  next_at: number;
  trigger?: string;
  memory_key?: string;
};
type Delivery = {
  key: string;
  content: string;
  status: string;
  at: number;
  category?: string;
};
type Preferences = {
  timezone: string;
  quiet_start: string | null;
  quiet_end: string | null;
  care_limit: number;
};
type State = {
  memories: Memory[];
  conflicts: {
    key: string;
    memory_key: string;
    proposed: string;
    status: string;
  }[];
  runs: Run[];
  tasks: {
    key: string;
    title: string;
    done: boolean;
    due: number | null;
    owner_id: number | null;
  }[];
  reminders: Reminder[];
  subscriptions: Subscription[];
  deliveries: Delivery[];
  shadow: { key: string; topic: string; at: number }[];
  preferences: Preferences;
  jobs: {
    key: string;
    source: number;
    status: string;
    error?: string;
    action_status?: string;
  }[];
  metrics: {
    model_calls: number;
    model_failures: number;
    mean_latency_ms: number | null;
    reported_tokens: number;
    usage_available: boolean;
    decisions: Record<string, number>;
    feedback: Record<string, number>;
  };
};
type ChatMessage = {
  id: number;
  user_id: number;
  content: string;
  created: number;
};
type EditStep = {
  tool: string;
  value: string;
  at: string;
  args?: Record<string, any>;
};
const status: Record<string, string> = {
  waiting_input: "待补充",
  waiting_authorization: "待授权",
  queued: "待执行",
  running: "执行中",
  succeeded: "成功",
  failed: "失败",
  cancelled: "已取消",
  active: "启用",
  paused: "已暂停",
  sent: "已发送，未确认送达",
  delivered: "已送达",
  acknowledged: "已确认",
  completed: "已完成",
  snoozed: "稍后提醒",
  skipped: "本次跳过",
  dismissed: "不需要",
  stopped: "已停止",
};
const stamp = (t: number) => new Date(t * 1000).toLocaleString("zh-CN");
const localTime = (t: number) =>
  new Date(t * 1000 - new Date(t * 1000).getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
const toolNames: Record<string, string> = {
  remember: "记住信息",
  family_tasks: "家庭待办",
  group_reminder: "设置提醒",
  memory_search: "检索记忆",
};
const emptyReminder = {
  key: "",
  content: "",
  at: "",
  mode: "once",
  clock: "09:00",
  weekdays: [0, 1, 2, 3, 4, 5, 6],
  timezone: "Asia/Shanghai",
  category: "daily",
  share_health: false,
  respect_quiet: true,
  notify_user_id: "",
  notify_after_minutes: 30,
};

export default function HarnessPage({ onBack }: { onBack: () => void }) {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [scope, setScope] = useState("personal");
  const [tab, setTab] = useState("inbox");
  const [data, setData] = useState<State | null>(null);
  const [error, setError] = useState("");
  const [connectionError, setConnectionError] = useState("");
  const [busy, setBusy] = useState(false);
  const [mem, setMem] = useState({
    key: "",
    content: "",
    lifetime: "long",
    subjects: "",
    expires_at: "",
  });
  const [rem, setRem] = useState(emptyReminder);
  const [sub, setSub] = useState({
    topic: "life",
    clock: "09:00",
    timezone: "Asia/Shanghai",
    shadow: true,
    share_health: false,
    trigger: "daily",
    memory_key: "",
  });
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [runTitle, setRunTitle] = useState("");
  const [runKey, setRunKey] = useState("");
  const [steps, setSteps] = useState<EditStep[]>([
    { tool: "family_tasks", value: "", at: "" },
  ]);
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [members, setMembers] = useState<{ id: number; name: string }[]>([]);
  const requestId = useRef(clientId());
  const chatId = useRef(clientId());
  const memoryRequestId = useRef(clientId());
  const reminderRequestId = useRef(clientId());
  const scopeRef = useRef(scope);
  const root = "/api/harness/" + scope;
  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const result = await api<State>(root + "/state", { signal });
        if (signal?.aborted || scopeRef.current !== scope) return;
        setData(result);
        setPrefs((old) => old || result.preferences);
        setConnectionError("");
        if (scope === "personal") {
          let rows: ChatMessage[] = [],
            cursor = 0,
            page: ChatMessage[];
          do {
            page = await api<ChatMessage[]>(
              "/api/harness/personal/messages?after=" + cursor,
              { signal },
            );
            rows = [...rows, ...page];
            if (page.length) cursor = page[page.length - 1].id;
          } while (page.length === 100);
          if (!signal?.aborted && scopeRef.current === scope) setChat(rows);
        }
      } catch (err) {
        if (!signal?.aborted && scopeRef.current === scope) {
          if ((err as Error & { status?: number }).status === 401) {
            setAuthed(false);
            setData(null);
            setChat([]);
            setPrefs(null);
          } else setConnectionError((err as Error).message);
        }
      }
    },
    [root, scope],
  );
  useEffect(() => {
    api<{ authenticated: boolean }>("/api/auth/status")
      .then((s) => setAuthed(s.authenticated))
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (authed)
      api<{ id: number; name: string }[]>("/api/groups/1/members")
        .then(setMembers)
        .catch((e) => setError(e.message));
  }, [authed]);
  useEffect(() => {
    setData(null);
    setChat([]);
    if (!authed) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      await load(controller.signal);
      if (!controller.signal.aborted) timer = setTimeout(poll, 3000);
    };
    poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [load, authed]);
  const act = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try {
      await work();
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const scopeChange = (value: string) => {
    scopeRef.current = value;
    setScope(value);
    setData(null);
    setMem({
      key: "",
      content: "",
      lifetime: "long",
      subjects: "",
      expires_at: "",
    });
    setRem(emptyReminder);
    setSub((old) => ({
      ...old,
      trigger: "daily",
      memory_key: "",
      share_health: false,
    }));
    setRunKey("");
    setRunTitle("");
    setSteps([{ tool: "family_tasks", value: "", at: "" }]);
    requestId.current = clientId();
    memoryRequestId.current = clientId();
    reminderRequestId.current = clientId();
  };
  const stepArguments = (s: EditStep): Step => ({
    tool: s.tool,
    arguments:
      s.tool === "remember"
        ? { ...(s.value ? { content: s.value } : {}) }
        : s.tool === "memory_search"
          ? { query: s.value }
          : s.tool === "group_reminder"
            ? {
                ...(s.value ? { content: s.value } : {}),
                ...(s.at ? { at: new Date(s.at).getTime() / 1000 } : {}),
              }
            : {
                ...s.args,
                action: s.args?.action || "create",
                ...(s.value
                  ? s.args?.action === "complete"
                    ? { key: s.value }
                    : { title: s.value }
                  : {}),
              },
  });
  return (
    <section className="harness-page">
      <header className="harness-header">
        <button className="secondary" onClick={onBack}>
          <ArrowLeft size={17} />
          返回聊天
        </button>
        <div>
          <h1>
            <LockKeyhole size={22} />
            个人空间与主动服务
          </h1>
          <p>管理记忆、任务、提醒和关怀订阅</p>
        </div>
        {authed && (
          <button
            className="secondary"
            onClick={() =>
              act(async () => {
                await api("/api/auth/logout", post({}));
                location.reload();
              })
            }
          >
            退出登录
          </button>
        )}
      </header>
      <div className="harness-body">
        {error && (
          <p className="harness-error" role="alert">
            {error}
          </p>
        )}
        {connectionError && (
          <p className="harness-error" role="alert">
            连接中断：{connectionError}
          </p>
        )}
        {authed === null ? (
          <p>正在连接…</p>
        ) : !authed ? (
          <Login />
        ) : (
          <>
            <div className="harness-toolbar">
              <div className="harness-tabs" aria-label="接收范围">
                {[
                  ["personal", "仅自己"],
                  ["group", "家庭群"],
                ].map(([key, label]) => (
                  <button
                    key={key}
                    className={scope === key ? "selected" : ""}
                    onClick={() => scopeChange(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <button
                className="secondary"
                disabled={busy}
                onClick={() => load()}
              >
                <RefreshCw size={16} />
                刷新
              </button>
            </div>
            <p className="field-help">
              {scope === "personal"
                ? "本页记忆、会话和提醒仅本人可见。"
                : "本页记忆和群内提醒对家庭成员可见；只展示自己发起的执行任务和订阅。"}
            </p>
            <div className="harness-tabs" aria-label="能力模块">
              {[
                ["inbox", "消息与反馈"],
                ["memory", "分层记忆"],
                ["runs", "执行任务"],
                ["reminders", "日常与用药提醒"],
                ["subscriptions", "关怀订阅"],
                ["preferences", "偏好与指标"],
              ].map(([key, label]) => (
                <button
                  key={key}
                  className={tab === key ? "selected" : ""}
                  onClick={() => setTab(key)}
                >
                  {label}
                </button>
              ))}
            </div>
            {!data ? (
              <p>正在读取…</p>
            ) : (
              <div className="harness-content">
                {tab === "inbox" && (
                  <>
                    <h2>提醒收件箱</h2>
                    {!data.deliveries.length && (
                      <p className="panel-intro">
                        暂无提醒。设置提醒或订阅后，会在这里接收。
                      </p>
                    )}
                    {data.deliveries.map((d) => (
                      <article className="harness-card" key={d.key}>
                        <small>
                          {stamp(d.at)} · {status[d.status] || d.status}
                        </small>
                        <p>{d.content}</p>
                        {![
                          "completed",
                          "snoozed",
                          "skipped",
                          "dismissed",
                          "stopped",
                        ].includes(d.status) && (
                          <div className="harness-actions">
                            {[
                              ["delivered", "标为已读"],
                              ["acknowledged", "确认收到"],
                              [
                                "completed",
                                d.category === "medication"
                                  ? "已服用"
                                  : "已完成",
                              ],
                              ["snoozed", "10分钟后提醒"],
                              ["skipped", "本次跳过"],
                              ["dismissed", "不需要"],
                              ["stopped", "停止此提醒"],
                            ].map(([action, label]) => (
                              <button
                                className="secondary"
                                disabled={busy}
                                key={action}
                                onClick={() =>
                                  act(() =>
                                    api(
                                      root +
                                        "/deliveries/" +
                                        encodeURIComponent(d.key) +
                                        "/feedback",
                                      post({ action, snooze_minutes: 10 }),
                                    ),
                                  )
                                }
                              >
                                {label}
                              </button>
                            ))}
                          </div>
                        )}
                      </article>
                    ))}
                    {scope === "personal" && (
                      <>
                        <h2>与小忆聊聊</h2>
                        <p className="field-help">
                          私人会话不会发送到家庭群。可以询问个人记忆，或明确说“记住……”。
                        </p>
                        <div className="private-messages">
                          {chat.map((m) => (
                            <article
                              className={
                                "harness-card " +
                                (m.user_id ? "private-mine" : "")
                              }
                              key={m.id}
                            >
                              <small>
                                {m.user_id ? "我" : "小忆"} · {stamp(m.created)}
                              </small>
                              <p>{m.content}</p>
                            </article>
                          ))}
                        </div>
                        <form
                          className="settings-form"
                          onSubmit={(e) => {
                            e.preventDefault();
                            act(async () => {
                              await api(
                                "/api/harness/personal/messages",
                                post({
                                  content: draft,
                                  client_id: chatId.current,
                                }),
                              );
                              setDraft("");
                              chatId.current = clientId();
                            });
                          }}
                        >
                          <label>
                            私人消息
                            <textarea
                              value={draft}
                              onChange={(e) => {
                                setDraft(e.target.value);
                                chatId.current = clientId();
                              }}
                              required
                              maxLength={10000}
                            />
                          </label>
                          <button
                            className="primary"
                            disabled={busy || !draft.trim()}
                          >
                            发送给小忆
                          </button>
                        </form>
                        {data.jobs?.map((j) => (
                          <article className="harness-card" key={j.key}>
                            <p role="alert">
                              {j.action_status === "succeeded"
                                ? "动作已完成，回复未送达："
                                : "回复暂未完成："}
                              {j.error}
                            </p>
                            <button
                              className="secondary"
                              disabled={busy}
                              onClick={() =>
                                act(() =>
                                  api(
                                    "/api/harness/personal/jobs/" +
                                      j.key +
                                      "/retry",
                                    post({}),
                                  ),
                                )
                              }
                            >
                              重试这条消息
                            </button>
                          </article>
                        ))}
                      </>
                    )}
                  </>
                )}
                {tab === "memory" && (
                  <div className="harness-columns">
                    <div>
                      <h2>{mem.key ? "编辑记忆" : "新增记忆"}</h2>
                      <form
                        className="settings-form"
                        onSubmit={(e) => {
                          e.preventDefault();
                          act(async () => {
                            await api(
                              root +
                                "/memories" +
                                (mem.key ? "/" + mem.key : ""),
                              {
                                method: mem.key ? "PUT" : "POST",
                                body: JSON.stringify({
                                  content: mem.content,
                                  client_id: memoryRequestId.current,
                                  lifetime: mem.lifetime,
                                  scope:
                                    scope === "personal"
                                      ? "private"
                                      : mem.subjects
                                        ? "profile"
                                        : "group",
                                  subjects: mem.subjects
                                    .split(/[，,]/)
                                    .map((s) => s.trim())
                                    .filter(Boolean),
                                  expires_at: mem.expires_at
                                    ? new Date(mem.expires_at).getTime() / 1000
                                    : null,
                                }),
                              },
                            );
                            setMem({
                              key: "",
                              content: "",
                              lifetime: "long",
                              subjects: "",
                              expires_at: "",
                            });
                            memoryRequestId.current = clientId();
                          });
                        }}
                      >
                        <label>
                          记忆内容
                          <textarea
                            required
                            value={mem.content}
                            maxLength={2000}
                            onChange={(e) =>
                              setMem({ ...mem, content: e.target.value })
                            }
                          />
                        </label>
                        <label>
                          保留层级
                          <select
                            value={mem.lifetime}
                            onChange={(e) =>
                              setMem({ ...mem, lifetime: e.target.value })
                            }
                          >
                            <option value="working">工作记忆（默认1天）</option>
                            <option value="short">短期记忆（默认7天）</option>
                            <option value="long">长期记忆</option>
                          </select>
                        </label>
                        <label>
                          涉及成员（逗号分隔）
                          <input
                            value={mem.subjects}
                            onChange={(e) =>
                              setMem({ ...mem, subjects: e.target.value })
                            }
                          />
                        </label>
                        <label>
                          有效期（可选）
                          <input
                            type="datetime-local"
                            value={mem.expires_at}
                            onChange={(e) =>
                              setMem({ ...mem, expires_at: e.target.value })
                            }
                          />
                        </label>
                        <button className="primary" disabled={busy}>
                          保存记忆
                        </button>
                      </form>
                    </div>
                    <div>
                      <h2>当前有效记忆</h2>
                      {!data.memories.length && <p>暂无有效记忆</p>}
                      {data.memories.map((m) => (
                        <article className="harness-card" key={m.key}>
                          <small>
                            {{ working: "工作", short: "短期", long: "长期" }[
                              m.lifetime
                            ] || "长期"}{" "}
                            ·{" "}
                            {m.scope === "private"
                              ? "仅本人"
                              : m.scope === "profile"
                                ? "群内成员画像"
                                : "群组共同记忆"}
                            {m.expires_at
                              ? " · " + stamp(m.expires_at) + "到期"
                              : ""}
                          </small>
                          <p>{m.content}</p>
                          <div className="harness-actions">
                            <button
                              className="secondary"
                              onClick={() =>
                                setMem({
                                  key: m.key,
                                  content: m.content,
                                  lifetime: m.lifetime || "long",
                                  subjects: m.subjects?.join(",") || "",
                                  expires_at: m.expires_at
                                    ? localTime(m.expires_at)
                                    : "",
                                })
                              }
                            >
                              编辑
                            </button>
                            <button
                              className="secondary"
                              disabled={busy}
                              onClick={() =>
                                act(() =>
                                  api(root + "/memories/" + m.key, {
                                    method: "DELETE",
                                  }),
                                )
                              }
                            >
                              删除
                            </button>
                          </div>
                        </article>
                      ))}
                      {data.conflicts
                        .filter((c) => c.status === "pending")
                        .map((c) => (
                          <article className="harness-card" key={c.key}>
                            <strong>待核对的信息</strong>
                            <p>{c.proposed}</p>
                            <button
                              className="secondary"
                              onClick={() => {
                                const m = data.memories.find(
                                  (m) => m.key === c.memory_key,
                                );
                                if (m)
                                  setMem({
                                    key: m.key,
                                    content: c.proposed,
                                    lifetime: m.lifetime || "long",
                                    subjects: m.subjects?.join(",") || "",
                                    expires_at: "",
                                  });
                              }}
                            >
                              核对并编辑原记忆
                            </button>
                          </article>
                        ))}
                    </div>
                  </div>
                )}
                {tab === "runs" && (
                  <div className="harness-columns">
                    <div>
                      <h2>{runKey ? "补充任务" : "创建执行任务"}</h2>
                      <p className="field-help">
                        先保存并查看步骤，再授权执行。步骤按顺序运行，失败后保留已完成结果。
                      </p>
                      <form
                        className="settings-form"
                        onSubmit={(e) => {
                          e.preventDefault();
                          act(async () => {
                            const body = {
                              title: runTitle,
                              client_id: requestId.current,
                              steps: steps.map(stepArguments),
                              authorized: false,
                            };
                            if (runKey)
                              await api(
                                root + "/runs/" + runKey + "/control",
                                post({
                                  action: "supplement",
                                  steps: body.steps,
                                }),
                              );
                            else await api(root + "/runs", post(body));
                            setRunKey("");
                            setRunTitle("");
                            setSteps([
                              { tool: "family_tasks", value: "", at: "" },
                            ]);
                            requestId.current = clientId();
                          });
                        }}
                      >
                        <label>
                          任务目标
                          <input
                            required
                            value={runTitle}
                            onChange={(e) => setRunTitle(e.target.value)}
                          />
                        </label>
                        {!runKey && (
                          <>
                            <button
                              className="secondary"
                              type="button"
                              disabled={busy || !runTitle.trim()}
                              onClick={() =>
                                act(async () => {
                                  await api(
                                    root + "/runs/plan",
                                    post({
                                      goal: runTitle,
                                      client_id: requestId.current,
                                    }),
                                  );
                                  setRunTitle("");
                                  requestId.current = clientId();
                                })
                              }
                            >
                              让小忆规划步骤
                            </button>
                            <p className="field-help">
                              仅将上方填写的目标发送给已配置模型。生成的步骤需审核授权后才执行，也可手动填写。
                            </p>
                          </>
                        )}
                        {steps.map((s, i) => (
                          <fieldset key={i}>
                            <legend>步骤 {i + 1}</legend>
                            <label>
                              能力
                              <select
                                value={s.tool}
                                onChange={(e) =>
                                  setSteps((old) =>
                                    old.map((v, n) =>
                                      n === i
                                        ? {
                                            ...v,
                                            tool: e.target.value,
                                            args: undefined,
                                          }
                                        : v,
                                    ),
                                  )
                                }
                              >
                                {Object.entries(toolNames).map(
                                  ([key, label]) => (
                                    <option key={key} value={key}>
                                      {label}
                                    </option>
                                  ),
                                )}
                              </select>
                            </label>
                            {s.tool === "family_tasks" && (
                              <label>
                                待办操作
                                <select
                                  value={s.args?.action || "create"}
                                  onChange={(e) =>
                                    setSteps((old) =>
                                      old.map((v, n) =>
                                        n === i
                                          ? {
                                              ...v,
                                              args: { action: e.target.value },
                                              value: "",
                                            }
                                          : v,
                                      ),
                                    )
                                  }
                                >
                                  <option value="create">创建</option>
                                  <option value="complete">
                                    完成（填写待办编号）
                                  </option>
                                  <option value="list">查看</option>
                                </select>
                              </label>
                            )}
                            <label>
                              内容
                              <input
                                value={s.value}
                                onChange={(e) =>
                                  setSteps((old) =>
                                    old.map((v, n) =>
                                      n === i
                                        ? { ...v, value: e.target.value }
                                        : v,
                                    ),
                                  )
                                }
                              />
                            </label>
                            {s.tool === "group_reminder" && (
                              <label>
                                提醒时间
                                <input
                                  type="datetime-local"
                                  value={s.at}
                                  onChange={(e) =>
                                    setSteps((old) =>
                                      old.map((v, n) =>
                                        n === i
                                          ? { ...v, at: e.target.value }
                                          : v,
                                      ),
                                    )
                                  }
                                />
                              </label>
                            )}
                            {steps.length > 1 && (
                              <button
                                type="button"
                                className="secondary"
                                onClick={() =>
                                  setSteps((old) =>
                                    old.filter((_, n) => n !== i),
                                  )
                                }
                              >
                                移除此步骤
                              </button>
                            )}
                          </fieldset>
                        ))}
                        <button
                          type="button"
                          className="secondary"
                          disabled={steps.length >= 12}
                          onClick={() =>
                            setSteps([
                              ...steps,
                              { tool: "family_tasks", value: "", at: "" },
                            ])
                          }
                        >
                          添加步骤
                        </button>
                        <button className="primary" disabled={busy}>
                          保存，等待授权
                        </button>
                      </form>
                    </div>
                    <div>
                      <h2>执行记录</h2>
                      <h3>待办清单</h3>
                      {!data.tasks?.length && (
                        <p className="field-help">
                          执行任务创建的待办会出现在这里。
                        </p>
                      )}
                      {data.tasks?.map((t) => (
                        <article className="harness-card" key={t.key}>
                          <strong>{t.title}</strong>
                          <p>{t.done ? "已完成" : "待完成"}</p>
                          <label>
                            到期时间
                            <input
                              aria-label={t.title + "的到期时间"}
                              type="datetime-local"
                              defaultValue={t.due ? localTime(t.due) : ""}
                              onBlur={(e) => {
                                const due = e.target.value
                                  ? new Date(e.target.value).getTime() / 1000
                                  : null;
                                if (due !== t.due)
                                  act(() =>
                                    api(root + "/tasks/" + t.key, {
                                      method: "PUT",
                                      body: JSON.stringify({ ...t, due }),
                                    }),
                                  );
                              }}
                            />
                          </label>
                          <div className="harness-actions">
                            <button
                              className="secondary"
                              disabled={busy}
                              onClick={() =>
                                act(() =>
                                  api(root + "/tasks/" + t.key, {
                                    method: "PUT",
                                    body: JSON.stringify({
                                      ...t,
                                      done: !t.done,
                                    }),
                                  }),
                                )
                              }
                            >
                              {t.done ? "标为未完成" : "完成待办"}
                            </button>
                          </div>
                          <small>待办编号：{t.key}</small>
                        </article>
                      ))}
                      <h3>步骤执行记录</h3>
                      {!data.runs.length && <p>暂无执行任务</p>}
                      {data.runs.map((r) => (
                        <article className="harness-card" key={r.key}>
                          <strong>{r.title}</strong>
                          <small>{status[r.status] || r.status}</small>
                          {r.reply_status === "failed" && (
                            <div>
                              <p role="alert">
                                {r.action_status === "succeeded"
                                  ? "动作已完成；"
                                  : ""}
                                回复未送达：{r.reply_error}
                              </p>
                              <button
                                className="secondary"
                                disabled={busy}
                                onClick={() =>
                                  act(() =>
                                    api(
                                      scope === "personal"
                                        ? "/api/harness/personal/jobs/" +
                                            r.source_id +
                                            "/retry"
                                        : "/api/groups/1/retry/" + r.source_id,
                                      post({}),
                                    ),
                                  )
                                }
                              >
                                仅重试回复
                              </button>
                            </div>
                          )}
                          <ol>
                            {r.steps.map((s, i) => (
                              <li key={i}>
                                {toolNames[s.tool] || s.tool}：
                                {s.arguments.action
                                  ? ({
                                      create: "创建",
                                      complete: "完成",
                                      list: "查看",
                                    }[s.arguments.action as string] ||
                                      s.arguments.action) + " · "
                                  : ""}
                                {s.arguments.title ||
                                  s.arguments.content ||
                                  s.arguments.query ||
                                  s.arguments.key ||
                                  "待补充"}
                                {s.arguments.at
                                  ? " · " + stamp(s.arguments.at)
                                  : ""}{" "}
                                {s.arguments.owner_id
                                  ? " · 负责人：" +
                                    (members.find(
                                      (m) => m.id === s.arguments.owner_id,
                                    )?.name || s.arguments.owner_id)
                                  : ""}
                                {s.arguments.due
                                  ? " · 到期：" + stamp(s.arguments.due)
                                  : ""}
                                ·{" "}
                                {status[s.status || ""] || s.status || "待执行"}
                                {s.result?.error && (
                                  <p role="alert">{s.result.error}</p>
                                )}
                              </li>
                            ))}
                          </ol>
                          {!r.conversation && (
                            <div className="harness-actions">
                              {r.status === "waiting_authorization" && (
                                <button
                                  className="primary"
                                  disabled={busy}
                                  onClick={() =>
                                    act(() =>
                                      api(
                                        root + "/runs/" + r.key + "/control",
                                        post({ action: "authorize" }),
                                      ),
                                    )
                                  }
                                >
                                  授权这些步骤
                                </button>
                              )}
                              {r.status === "failed" && (
                                <button
                                  className="secondary"
                                  disabled={busy}
                                  onClick={() =>
                                    act(() =>
                                      api(
                                        root + "/runs/" + r.key + "/control",
                                        post({ action: "retry" }),
                                      ),
                                    )
                                  }
                                >
                                  重试未完成步骤
                                </button>
                              )}
                              {[
                                "waiting_input",
                                "waiting_authorization",
                              ].includes(r.status) && (
                                <button
                                  className="secondary"
                                  onClick={() => {
                                    setRunKey(r.key);
                                    setRunTitle(r.title);
                                    setSteps(
                                      r.steps.map((s) => ({
                                        tool: s.tool,
                                        value:
                                          s.arguments.title ||
                                          s.arguments.content ||
                                          s.arguments.query ||
                                          s.arguments.key ||
                                          "",
                                        args: s.arguments,
                                        at: s.arguments.at
                                          ? localTime(s.arguments.at)
                                          : "",
                                      })),
                                    );
                                  }}
                                >
                                  补充或修改
                                </button>
                              )}
                              {!["succeeded", "cancelled"].includes(
                                r.status,
                              ) && (
                                <button
                                  className="secondary"
                                  disabled={busy}
                                  onClick={() =>
                                    act(() =>
                                      api(
                                        root + "/runs/" + r.key + "/control",
                                        post({ action: "cancel" }),
                                      ),
                                    )
                                  }
                                >
                                  取消后续步骤
                                </button>
                              )}
                            </div>
                          )}
                        </article>
                      ))}
                    </div>
                  </div>
                )}
                {tab === "reminders" && (
                  <div className="harness-columns">
                    <div>
                      <h2>{rem.key ? "更改提醒" : "设置提醒"}</h2>
                      <form
                        className="settings-form"
                        onSubmit={(e) => {
                          e.preventDefault();
                          act(async () => {
                            await api(
                              root +
                                "/reminders" +
                                (rem.key ? "/" + rem.key : ""),
                              {
                                method: rem.key ? "PUT" : "POST",
                                body: JSON.stringify({
                                  ...rem,
                                  client_id: reminderRequestId.current,
                                  at:
                                    rem.mode === "once"
                                      ? new Date(rem.at).getTime() / 1000
                                      : null,
                                  clock: rem.mode === "once" ? null : rem.clock,
                                  weekdays:
                                    rem.mode === "once" ? null : rem.weekdays,
                                  notify_user_id: rem.notify_user_id
                                    ? Number(rem.notify_user_id)
                                    : null,
                                  notify_after_minutes: rem.notify_user_id
                                    ? rem.notify_after_minutes
                                    : null,
                                }),
                              },
                            );
                            setRem(emptyReminder);
                            reminderRequestId.current = clientId();
                          });
                        }}
                      >
                        <label>
                          提醒类型
                          <select
                            value={rem.category}
                            onChange={(e) =>
                              setRem({ ...rem, category: e.target.value })
                            }
                          >
                            <option value="daily">日常事项</option>
                            <option value="medication">用药提醒</option>
                          </select>
                        </label>
                        <label>
                          提醒内容
                          <textarea
                            required
                            value={rem.content}
                            maxLength={2000}
                            onChange={(e) =>
                              setRem({ ...rem, content: e.target.value })
                            }
                          />
                        </label>
                        {rem.category === "medication" && (
                          <p className="field-help">
                            请填写已经确定的用药安排。系统只发送提醒并记录你的反馈，不推断药物、剂量或疗程。
                          </p>
                        )}
                        <label>
                          重复规则
                          <select
                            value={rem.mode}
                            onChange={(e) =>
                              setRem({ ...rem, mode: e.target.value })
                            }
                          >
                            <option value="once">一次性</option>
                            <option value="weekly">按星期重复</option>
                          </select>
                        </label>
                        {rem.mode === "once" ? (
                          <label>
                            提醒时间
                            <input
                              required
                              type="datetime-local"
                              value={rem.at}
                              onChange={(e) =>
                                setRem({ ...rem, at: e.target.value })
                              }
                            />
                          </label>
                        ) : (
                          <>
                            <label>
                              每天的时间
                              <input
                                type="time"
                                required
                                value={rem.clock}
                                onChange={(e) =>
                                  setRem({ ...rem, clock: e.target.value })
                                }
                              />
                            </label>
                            <div className="harness-weekdays">
                              {["一", "二", "三", "四", "五", "六", "日"].map(
                                (v, i) => (
                                  <label key={i}>
                                    <input
                                      type="checkbox"
                                      checked={rem.weekdays.includes(i)}
                                      onChange={(e) =>
                                        setRem({
                                          ...rem,
                                          weekdays: e.target.checked
                                            ? [...rem.weekdays, i]
                                            : rem.weekdays.filter(
                                                (n) => n !== i,
                                              ),
                                        })
                                      }
                                    />
                                    {v}
                                  </label>
                                ),
                              )}
                            </div>
                          </>
                        )}
                        <label>
                          时区
                          <input
                            value={rem.timezone}
                            onChange={(e) =>
                              setRem({ ...rem, timezone: e.target.value })
                            }
                            required
                          />
                        </label>
                        <label className="toggle-label">
                          遵守个人免打扰
                          <input
                            type="checkbox"
                            checked={rem.respect_quiet}
                            onChange={(e) =>
                              setRem({
                                ...rem,
                                respect_quiet: e.target.checked,
                              })
                            }
                          />
                        </label>
                        <label>
                          未确认时通知指定家人（可选）
                          <select
                            value={rem.notify_user_id}
                            onChange={(e) =>
                              setRem({ ...rem, notify_user_id: e.target.value })
                            }
                          >
                            <option value="">不通知</option>
                            {members.map((m) => (
                              <option key={m.id} value={m.id}>
                                {m.name}
                              </option>
                            ))}
                          </select>
                        </label>
                        {rem.notify_user_id && (
                          <label>
                            等待确认的分钟数
                            <input
                              type="number"
                              min={5}
                              max={1440}
                              value={rem.notify_after_minutes}
                              onChange={(e) =>
                                setRem({
                                  ...rem,
                                  notify_after_minutes: Number(e.target.value),
                                })
                              }
                            />
                          </label>
                        )}
                        {(rem.notify_user_id ||
                          (scope === "group" &&
                            rem.category === "medication")) && (
                          <label className="toggle-label">
                            我同意向上述接收范围分享自己的提醒状态
                            <input
                              required
                              type="checkbox"
                              checked={rem.share_health}
                              onChange={(e) =>
                                setRem({
                                  ...rem,
                                  share_health: e.target.checked,
                                })
                              }
                            />
                          </label>
                        )}
                        <button className="primary" disabled={busy}>
                          保存提醒
                        </button>
                      </form>
                    </div>
                    <div>
                      <h2>我的提醒规则</h2>
                      {!data.reminders.length && <p>暂无提醒</p>}
                      {data.reminders.map((r) => (
                        <article className="harness-card" key={r.key}>
                          <small>
                            {r.category === "medication" ? "用药" : "日常"} ·{" "}
                            {r.sent ? "本次已触发" : status[r.status] || "启用"}
                          </small>
                          <p>{r.content}</p>
                          <small>
                            {r.clock
                              ? `${r.clock} · ${r.timezone} · 周${(r.weekdays || [0, 1, 2, 3, 4, 5, 6]).map((i) => ["一", "二", "三", "四", "五", "六", "日"][i]).join("、")}`
                              : stamp(r.at)}
                          </small>
                          <div className="harness-actions">
                            <button
                              className="secondary"
                              onClick={() =>
                                setRem({
                                  key: r.key,
                                  content: r.content,
                                  at: localTime(r.at),
                                  mode: r.clock ? "weekly" : "once",
                                  clock: r.clock || "09:00",
                                  weekdays: r.weekdays || [0, 1, 2, 3, 4, 5, 6],
                                  timezone: r.timezone || "Asia/Shanghai",
                                  category: r.category || "daily",
                                  share_health: r.share_health || false,
                                  respect_quiet: r.respect_quiet !== false,
                                  notify_user_id: r.notify_user_id
                                    ? String(r.notify_user_id)
                                    : "",
                                  notify_after_minutes:
                                    r.notify_after_minutes || 30,
                                })
                              }
                            >
                              更改或恢复
                            </button>
                            {!r.sent && r.status !== "cancelled" && (
                              <button
                                className="secondary"
                                disabled={busy}
                                onClick={() =>
                                  act(() =>
                                    api(
                                      root + "/reminders/" + r.key + "/control",
                                      post({
                                        action:
                                          r.status === "paused"
                                            ? "resume"
                                            : "pause",
                                      }),
                                    ),
                                  )
                                }
                              >
                                {r.status === "paused"
                                  ? "恢复提醒"
                                  : "暂停提醒"}
                              </button>
                            )}
                            {r.status !== "cancelled" && (
                              <button
                                className="secondary"
                                disabled={busy}
                                onClick={() =>
                                  act(() =>
                                    api(root + "/reminders/" + r.key, {
                                      method: "DELETE",
                                    }),
                                  )
                                }
                              >
                                取消提醒
                              </button>
                            )}
                          </div>
                        </article>
                      ))}
                    </div>
                  </div>
                )}
                {tab === "subscriptions" && (
                  <div className="harness-columns">
                    <div>
                      <h2>按主题订阅关怀</h2>
                      <p className="field-help">
                        默认先观察，只记录候选。关闭“仅观察”后，按订阅范围低频发送。
                      </p>
                      <form
                        className="settings-form"
                        onSubmit={(e) => {
                          e.preventDefault();
                          act(() =>
                            api(
                              root + "/subscriptions",
                              post({
                                ...sub,
                                memory_key: sub.memory_key || null,
                                enabled: true,
                              }),
                            ),
                          );
                        }}
                      >
                        <label>
                          主题
                          <select
                            value={sub.topic}
                            onChange={(e) =>
                              setSub({ ...sub, topic: e.target.value })
                            }
                          >
                            <option value="life">生活安排</option>
                            <option value="health">健康关怀</option>
                          </select>
                        </label>
                        <label>
                          触发方式
                          <select
                            value={sub.trigger}
                            onChange={(e) =>
                              setSub({ ...sub, trigger: e.target.value })
                            }
                          >
                            <option value="daily">每天约定时间</option>
                            <option value="task_due">
                              待办将在24小时内到期
                            </option>
                            {scope === "personal" && (
                              <option value="memory_expiring">
                                个人记忆将在24小时内到期
                              </option>
                            )}
                          </select>
                        </label>
                        {scope === "personal" && (
                          <label>
                            关联个人记忆（可选）
                            <select
                              value={sub.memory_key}
                              onChange={(e) =>
                                setSub({ ...sub, memory_key: e.target.value })
                              }
                            >
                              <option value="">不关联</option>
                              {data.memories.map((m) => (
                                <option key={m.key} value={m.key}>
                                  {m.content.slice(0, 40)}
                                </option>
                              ))}
                            </select>
                          </label>
                        )}
                        <label>
                          每日触达时间（事件触发时不使用）
                          <input
                            type="time"
                            value={sub.clock}
                            required
                            onChange={(e) =>
                              setSub({ ...sub, clock: e.target.value })
                            }
                          />
                        </label>
                        <label>
                          时区
                          <input
                            value={sub.timezone}
                            required
                            onChange={(e) =>
                              setSub({ ...sub, timezone: e.target.value })
                            }
                          />
                        </label>
                        <label className="toggle-label">
                          仅观察，不发送
                          <input
                            type="checkbox"
                            checked={sub.shadow}
                            onChange={(e) =>
                              setSub({ ...sub, shadow: e.target.checked })
                            }
                          />
                        </label>
                        {scope === "group" && sub.topic === "health" && (
                          <label className="toggle-label">
                            同意在家庭群接收健康关怀
                            <input
                              required
                              type="checkbox"
                              checked={sub.share_health}
                              onChange={(e) =>
                                setSub({
                                  ...sub,
                                  share_health: e.target.checked,
                                })
                              }
                            />
                          </label>
                        )}
                        <button className="primary" disabled={busy}>
                          订阅此主题
                        </button>
                      </form>
                    </div>
                    <div>
                      <h2>已订阅主题</h2>
                      {!data.subscriptions.length && (
                        <p>尚未订阅，系统不会主动发起关怀。</p>
                      )}
                      {data.subscriptions.map((s) => (
                        <article className="harness-card" key={s.key}>
                          <strong>
                            {s.topic === "life" ? "生活安排" : "健康关怀"}
                          </strong>
                          <p>
                            {s.enabled
                              ? s.shadow
                                ? "观察中，不发送"
                                : "已开启"
                              : "已退订"}{" "}
                            · {s.clock} · {s.timezone}
                          </p>
                          <div className="harness-actions">
                            <button
                              className="secondary"
                              disabled={busy}
                              onClick={() =>
                                act(() =>
                                  api(
                                    root +
                                      "/subscriptions/" +
                                      encodeURIComponent(s.key),
                                    {
                                      method: "PUT",
                                      body: JSON.stringify({
                                        ...s,
                                        enabled: true,
                                        shadow: !s.shadow,
                                      }),
                                    },
                                  ),
                                )
                              }
                            >
                              {s.shadow ? "开始实际触达" : "切换仅观察"}
                            </button>
                            {s.enabled && (
                              <button
                                className="secondary"
                                disabled={busy}
                                onClick={() =>
                                  act(() =>
                                    api(
                                      root +
                                        "/subscriptions/" +
                                        encodeURIComponent(s.key),
                                      { method: "DELETE" },
                                    ),
                                  )
                                }
                              >
                                退订
                              </button>
                            )}
                          </div>
                        </article>
                      ))}
                      <h3>最近观察记录</h3>
                      {data.shadow.map((s) => (
                        <p key={s.key}>
                          {stamp(s.at)} · {s.topic === "life" ? "生活" : "健康"}
                          关怀候选，未发送
                        </p>
                      ))}
                    </div>
                  </div>
                )}
                {tab === "preferences" && (
                  <div className="harness-columns">
                    <div>
                      <h2>个人接收偏好</h2>
                      {prefs && (
                        <form
                          className="settings-form"
                          onSubmit={(e) => {
                            e.preventDefault();
                            act(() =>
                              api("/api/harness/personal/preferences", {
                                method: "PUT",
                                body: JSON.stringify(prefs),
                              }),
                            );
                          }}
                        >
                          <label>
                            时区
                            <input
                              required
                              value={prefs.timezone}
                              onChange={(e) =>
                                setPrefs({ ...prefs, timezone: e.target.value })
                              }
                            />
                          </label>
                          <label>
                            免打扰开始
                            <input
                              type="time"
                              value={prefs.quiet_start || ""}
                              onChange={(e) =>
                                setPrefs({
                                  ...prefs,
                                  quiet_start: e.target.value || null,
                                })
                              }
                            />
                          </label>
                          <label>
                            免打扰结束
                            <input
                              type="time"
                              value={prefs.quiet_end || ""}
                              onChange={(e) =>
                                setPrefs({
                                  ...prefs,
                                  quiet_end: e.target.value || null,
                                })
                              }
                            />
                          </label>
                          <label>
                            每天主动关怀上限（跨个人与群渠道）
                            <input
                              type="number"
                              min={0}
                              max={10}
                              value={prefs.care_limit}
                              onChange={(e) =>
                                setPrefs({
                                  ...prefs,
                                  care_limit: Number(e.target.value),
                                })
                              }
                            />
                          </label>
                          <button className="primary" disabled={busy}>
                            保存接收偏好
                          </button>
                        </form>
                      )}
                    </div>
                    <div>
                      <h2>当前空间运行指标</h2>
                      <dl className="harness-metrics">
                        <dt>模型调用 / 失败</dt>
                        <dd>
                          {data.metrics.model_calls} /{" "}
                          {data.metrics.model_failures}
                        </dd>
                        <dt>平均响应</dt>
                        <dd>
                          {data.metrics.mean_latency_ms === null
                            ? "暂无数据"
                            : data.metrics.mean_latency_ms + " ms"}
                        </dd>
                        <dt>模型用量</dt>
                        <dd>
                          {data.metrics.reported_tokens} tokens
                          {!data.metrics.usage_available
                            ? "（部分或全部调用未返回用量）"
                            : ""}
                        </dd>
                        <dt>参与判断</dt>
                        <dd>
                          {Object.entries(data.metrics.decisions)
                            .map(([k, v]) => `${k}: ${v}`)
                            .join("，") || "暂无"}
                        </dd>
                        <dt>用户反馈</dt>
                        <dd>
                          {Object.entries(data.metrics.feedback)
                            .map(([k, v]) => `${k}: ${v}`)
                            .join("，") || "暂无"}
                        </dd>
                      </dl>
                    </div>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
