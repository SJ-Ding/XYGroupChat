import React, { useState, useEffect, useRef } from "react";
import {
  MessageCircle,
  BookOpen,
  ListTodo,
  Settings,
  Users,
  Search,
  X,
  Plus,
  Image as ImageIcon,
  AtSign,
  Send,
  LogOut,
  Pencil,
  Trash2,
  ChevronLeft,
  RefreshCw,
  Check,
  Leaf,
  Loader2,
  LockKeyhole,
  ArrowRight,
  Bot,
} from "lucide-react";
import AgentPage from "./AgentPage";
import HarnessPage from "./HarnessPage";
import { Avatar, Modal, Empty } from "./components";
import { api, post, time, base, clientId, identityUrl } from "./api";
import type {
  User,
  Message,
  Memory,
  Task,
  Config,
  Activity,
  Panel,
} from "./types";
export default function Chat({
  user,
  notify,
}: {
  user: User;
  notify: (s: string) => void;
}) {
  const [messages, setMessages] = useState<Message[]>([]),
    [members, setMembers] = useState<User[]>([]),
    [panel, setPanel] = useState<Panel>(null),
    [config, setConfig] = useState<Config | null>(null),
    [memories, setMemories] = useState<Memory[]>([]),
    [tasks, setTasks] = useState<Task[]>([]),
    [activity, setActivity] = useState<Activity>({ logs: [], failed: [] });
  const [draft, setDraft] = useState(""),
    [images, setImages] = useState<string[]>([]),
    [busy, setBusy] = useState(false),
    [uploading, setUploading] = useState(false),
    [status, setStatus] = useState("idle"),
    [online, setOnline] = useState(false),
    [search, setSearch] = useState(""),
    [query, setQuery] = useState(""),
    [older, setOlder] = useState(true),
    [lightbox, setLightbox] = useState<string | null>(null),
    [highlight, setHighlight] = useState<number | null>(null);
  const [memoryEdit, setMemoryEdit] = useState<{
      key?: string;
      content: string;
    } | null>(null),
    [taskEdit, setTaskEdit] = useState<Task | null>(null),
    [revisions, setRevisions] = useState<
      { previous: { content: string }; at: number }[] | null
    >(null);
  const last = useRef(0),
    bottom = useRef<HTMLDivElement>(null),
    file = useRef<HTMLInputElement>(null),
    input = useRef<HTMLTextAreaElement>(null),
    scrollToBottom = useRef(true),
    pendingSend = useRef<{
      id: string;
      content: string;
      attachments: string[];
    } | null>(null);
  const [view, setView] = useState(() =>
    ["agent", "harness"].includes(
      new URLSearchParams(location.search).get("view") || "",
    )
      ? new URLSearchParams(location.search).get("view")!
      : "chat",
  );
  function navigate(next: string) {
    const url = new URL(location.href);
    if (next !== "chat") url.searchParams.set("view", next);
    else url.searchParams.delete("view");
    history.pushState(null, "", url);
    setView(next);
    setPanel(null);
  }
  useEffect(() => {
    const pop = () => {
      setView(
        ["agent", "harness"].includes(
          new URLSearchParams(location.search).get("view") || "",
        )
          ? new URLSearchParams(location.search).get("view")!
          : "chat",
      );
      setPanel(null);
    };
    addEventListener("popstate", pop);
    return () => removeEventListener("popstate", pop);
  }, []);
  const settingsDirty = useRef(false);
  const [searchResults, setSearchResults] = useState<Message[]>([]);
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      if (search)
        api<Message[]>(base + "/messages?query=" + encodeURIComponent(search))
          .then((rows) => {
            if (!cancelled) setSearchResults(rows);
          })
          .catch((e) => notify(e.message));
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [search, messages.length]);
  function merge(rows: Message[]) {
    setMessages((old) => {
      const map = new Map(old.map((m) => [m.id, m]));
      rows.forEach((m) => map.set(m.id, m));
      return [...map.values()].sort((a, b) => a.id - b.id);
    });
    rows.forEach((m) => (last.current = Math.max(last.current, m.id)));
  }
  async function sync() {
    let rows: Message[];
    let cursor = last.current;
    do {
      rows = await api<Message[]>(base + "/messages?after=" + cursor);
      merge(rows);
      if (rows.length) cursor = rows[rows.length - 1].id;
    } while (rows.length === 100);
  }
  async function refresh() {
    const [c, m, t, a, u] = await Promise.all([
      api<Config>(base + "/settings"),
      api<Memory[]>(base + "/memories"),
      api<Task[]>(base + "/tasks"),
      api<Activity>(base + "/activity"),
      api<User[]>(base + "/members"),
    ]);
    setConfig((old) => (settingsDirty.current ? old : c));
    setMemories(m);
    setTasks(t);
    setActivity(a);
    setMembers(u);
  }
  useEffect(() => {
    let alive = true,
      ws: WebSocket,
      timer: ReturnType<typeof setTimeout>,
      heartbeat: ReturnType<typeof setInterval>;
    api<Message[]>(base + "/messages")
      .then((rows) => {
        if (alive) {
          merge(rows);
          setOlder(rows.length === 50);
        }
      })
      .catch((e) => notify(e.message));
    refresh().catch((e) => notify(e.message));
    function connect() {
      ws = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${identityUrl("/ws/1")}`,
      );
      ws.onopen = () => {
        setOnline(true);
        sync().catch((e) => notify(e.message));
        heartbeat = setInterval(() => {
          if (ws.readyState === 1) ws.send("ping");
        }, 25000);
      };
      ws.onmessage = (e) => {
        const event = JSON.parse(e.data);
        if (event.type === "message") {
          scrollToBottom.current = true;
          sync().catch((e) => notify(e.message));
        }
        if (event.type === "presence" || event.type === "refresh")
          refresh().catch(() => {});
        if (event.type === "agent") {
          setStatus(event.status);
          if (event.status === "failed") notify(event.error);
        }
      };
      ws.onclose = () => {
        setOnline(false);
        clearInterval(heartbeat);
        if (alive) timer = setTimeout(connect, 2000);
      };
    }
    connect();
    return () => {
      alive = false;
      clearTimeout(timer);
      clearInterval(heartbeat);
      ws.close();
    };
  }, []);
  useEffect(() => {
    if (scrollToBottom.current)
      bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, status]);
  async function send() {
    if (busy || uploading || (!draft.trim() && !images.length)) return;
    setBusy(true);
    const data = pendingSend.current;
    const payload =
      data &&
      data.content === draft &&
      JSON.stringify(data.attachments) === JSON.stringify(images)
        ? data
        : { id: clientId(), content: draft, attachments: images };
    pendingSend.current = payload;
    try {
      const row = await api<Message>(
        base + "/messages",
        post({
          client_id: payload.id,
          content: payload.content,
          attachments: payload.attachments,
        }),
      );
      scrollToBottom.current = true;
      merge([row]);
      setDraft("");
      setImages([]);
      pendingSend.current = null;
      input.current?.focus();
    } catch (e) {
      notify((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function upload(files: FileList | null) {
    if (!files) return;
    setUploading(true);
    try {
      for (const f of Array.from(files)) {
        if (images.length >= 4) break;
        const form = new FormData();
        form.append("file", f);
        const result = await api<{ key: string }>(base + "/uploads", {
          method: "POST",
          body: form,
        });
        setImages((old) => [...old, result.key].slice(0, 4));
      }
    } catch (e) {
      notify((e as Error).message);
    } finally {
      setUploading(false);
      if (file.current) file.current.value = "";
    }
  }
  async function source(id: number) {
    try {
      const rows = await api<Message[]>(base + "/messages?around=" + id);
      scrollToBottom.current = false;
      merge(rows);
      setHighlight(id);
      if (window.innerWidth < 1000) setPanel(null);
      setTimeout(
        () =>
          document
            .getElementById("message-" + id)
            ?.scrollIntoView({ behavior: "smooth", block: "center" }),
        100,
      );
    } catch (e) {
      notify((e as Error).message);
    }
  }
  async function saveMemory() {
    if (!memoryEdit?.content.trim()) return;
    try {
      await api(
        base + "/memories" + (memoryEdit.key ? "/" + memoryEdit.key : ""),
        {
          method: memoryEdit.key ? "PUT" : "POST",
          body: JSON.stringify({ content: memoryEdit.content }),
        },
      );
      setMemoryEdit(null);
      await refresh();
    } catch (e) {
      notify((e as Error).message);
    }
  }
  async function saveTask(t: Task) {
    try {
      await api(base + "/tasks" + (t.key ? "/" + t.key : ""), {
        method: t.key ? "PUT" : "POST",
        body: JSON.stringify(t),
      });
      setTaskEdit(null);
      await refresh();
    } catch (e) {
      notify((e as Error).message);
    }
  }
  const agentName = config?.agent_name || "小忆";
  return (
    <main className={`shell ${panel ? "with-panel" : ""}`}>
      <nav className="rail" aria-label="主导航">
        <button
          className="profile"
          title={user.name}
          onClick={() => setPanel("members")}
        >
          <Avatar id={user.id} name={user.name} small />
        </button>
        <div className="rail-links">
          {[
            [null, MessageCircle, "聊天"],
            ["agent", Bot, "Agent"],
            ["harness", LockKeyhole, "个人与提醒"],
            ["memory", BookOpen, "家庭记忆"],
            ["tasks", ListTodo, "待办清单"],
            ["settings", Settings, "设置"],
          ].map(([key, Icon, label]) => {
            const C = Icon as typeof MessageCircle;
            return (
              <button
                key={String(key)}
                title={label as string}
                className={
                  (
                    key === "agent" || key === "harness"
                      ? view === key
                      : key === null
                        ? view === "chat" && panel === null
                        : panel === key
                  )
                    ? "active"
                    : ""
                }
                onClick={() =>
                  key === "agent" || key === "harness"
                    ? navigate(key as string)
                    : key === null
                      ? navigate("chat")
                      : setPanel(key as Panel)
                }
              >
                <C size={23} />
                <span>{label as string}</span>
              </button>
            );
          })}
        </div>
        <button
          className="logout"
          title="切换成员"
          onClick={() => setPanel("members")}
        >
          <Users size={21} />
        </button>
      </nav>
      {view === "chat" && (
        <aside className="conversations">
          <div className="brand compact">小忆</div>
          <div className="searchbox">
            <Search size={17} />
            <input
              aria-label="搜索聊天记录"
              placeholder="搜索聊天记录"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <button
            className="conversation selected"
            onClick={() => {
              setSearch("");
              setPanel(null);
            }}
          >
            <span className="group-avatar">
              <Users size={25} />
            </span>
            <span>
              <strong>我们一家</strong>
              <small>4 位成员 · 家庭群</small>
              <p>
                {messages.at(-1)?.content || "把日常的小事，慢慢聊给家人听。"}
              </p>
            </span>
            <span className="conversation-time">
              {messages.length ? time(messages.at(-1)!.created) : ""}
            </span>
          </button>
          <div className="sidebar-family">
            <span>我的家人</span>
            <button aria-label="查看群成员" onClick={() => setPanel("members")}>
              <Users size={16} />
            </button>
          </div>
          {members.map((m) => (
            <div className="family-member" key={m.id}>
              <Avatar id={m.id} name={m.name} small />
              <div>
                <strong>
                  {m.name}
                  {m.id === user.id && <em>我</em>}
                </strong>
                <small>
                  <i className={m.online ? "dot online" : "dot"} />
                  {m.online ? "在线" : "离线"}
                </small>
              </div>
            </div>
          ))}
          <div className="family-member">
            <Avatar id={0} name={agentName} small />
            <div>
              <strong>
                {agentName}
                <em>家庭助手</em>
              </strong>
              <small>在需要时，搭把手</small>
            </div>
          </div>
          <div className="sidebar-bottom">
            <Leaf size={16} />
            <span>记住日常，陪伴家人</span>
          </div>
        </aside>
      )}
      {view === "harness" ? (
        <HarnessPage onBack={() => navigate("chat")} />
      ) : view === "agent" ? (
        <AgentPage
          onBack={() => navigate("chat")}
          onSettings={() => setPanel("settings")}
          onSource={(id) => {
            navigate("chat");
            source(id);
          }}
        />
      ) : (
        <section className="chat">
          <header className="chat-header">
            <div>
              <h1>
                我们一家 <span>4</span>
              </h1>
              <p>
                <i className={`dot ${online ? "online" : ""}`} />
                {online ? "已连接" : "正在重新连接…"}
                <span className="header-members">
                  爸爸、妈妈、小宇、{agentName}
                </span>
              </p>
            </div>
            <div className="header-actions">
              <button
                className={panel === "memory" ? "selected" : ""}
                onClick={() => setPanel(panel === "memory" ? null : "memory")}
              >
                <BookOpen size={18} />
                <span>家庭记忆</span>
              </button>
              <button title="群成员" onClick={() => setPanel("members")}>
                <Users size={21} />
              </button>
            </div>
          </header>
          <div
            className="messages"
            onScroll={(e) => {
              const el = e.currentTarget;
              scrollToBottom.current =
                el.scrollHeight - el.scrollTop - el.clientHeight < 100;
            }}
          >
            {older && (
              <button
                className="older"
                onClick={async () => {
                  try {
                    scrollToBottom.current = false;
                    const rows = await api<Message[]>(
                      base + "/messages?before=" + messages[0]?.id,
                    );
                    setOlder(rows.length === 50);
                    merge(rows);
                  } catch (e) {
                    notify((e as Error).message);
                  }
                }}
              >
                加载更早的消息
              </button>
            )}
            {!messages.length && (
              <div className="empty-chat">
                <span className="empty-house">
                  <Users size={35} />
                </span>
                <h2>我们一家，随时聊聊。</h2>
                <p>
                  分享今天的小事，或 @{agentName} 寻求帮助。
                  <br />
                  {agentName} 会把重要的家庭记忆留在这里。
                </p>
              </div>
            )}
            {(search ? searchResults : messages).map((m, i, all) => (
              <React.Fragment key={m.id}>
                {(i === 0 ||
                  new Date(m.created * 1000).toDateString() !==
                    new Date(all[i - 1].created * 1000).toDateString()) && (
                  <div className="date-divider">
                    <span>
                      {new Date(m.created * 1000).toLocaleDateString("zh-CN", {
                        month: "long",
                        day: "numeric",
                        weekday: "long",
                      })}
                    </span>
                  </div>
                )}
                <article
                  id={"message-" + m.id}
                  className={`message ${m.user_id === user.id ? "mine" : ""} ${m.user_id === 0 ? "agent-message" : ""} ${highlight === m.id ? "highlight" : ""}`}
                >
                  <Avatar id={m.user_id} name={m.name} />
                  <div className="message-body">
                    <div className="message-meta">
                      <span>{m.name}</span>
                      {m.user_id === 0 && <em>家庭助手</em>}
                      <time>{time(m.created)}</time>
                    </div>
                    <div className="bubble">
                      {m.content && <p>{m.content}</p>}
                      {m.attachments.map((k) => (
                        <button
                          className="chat-image"
                          key={k}
                          onClick={() =>
                            setLightbox(identityUrl(base + "/uploads/" + k))
                          }
                        >
                          <img
                            alt={m.name + "分享的图片"}
                            src={identityUrl(base + "/uploads/" + k)}
                          />
                        </button>
                      ))}
                    </div>
                    {m.user_id === 0 && user.authenticated && (
                      <div className="harness-actions">
                        {[
                          ["helpful", "帮到我了"],
                          ["over_intervention", "这次不用介入"],
                          ["memory_incorrect", "记忆有误"],
                        ].map(([kind, label]) => (
                          <button
                            className="secondary"
                            key={kind}
                            onClick={async () => {
                              try {
                                await api(
                                  "/api/harness/group/feedback",
                                  post({ kind, source: m.id }),
                                );
                                notify("反馈已记录");
                              } catch (e) {
                                notify((e as Error).message);
                              }
                            }}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </article>
              </React.Fragment>
            ))}
            {status === "generating" && (
              <div className="generating">
                <Avatar id={0} name={agentName} small />
                <span>
                  <Loader2 size={15} className="spin" />
                  {agentName} 正在整理回复…
                </span>
              </div>
            )}
            <div ref={bottom} />
          </div>
          <div className="composer">
            <div className="composer-tools">
              <button
                title="发送图片"
                disabled={uploading}
                onClick={() => file.current?.click()}
              >
                {uploading ? (
                  <Loader2 className="spin" size={21} />
                ) : (
                  <ImageIcon size={22} />
                )}
              </button>
              <button
                title={"提及" + agentName}
                onClick={() => {
                  setDraft((d) => d + "@" + agentName + " ");
                  input.current?.focus();
                }}
              >
                <AtSign size={23} />
              </button>
              <span>给家人发消息，或 @{agentName}</span>
              <input
                type="file"
                ref={file}
                multiple
                accept="image/jpeg,image/png,image/webp"
                hidden
                onChange={(e) => upload(e.target.files)}
              />
            </div>
            {images.length > 0 && (
              <div className="image-previews">
                {images.map((k) => (
                  <div key={k}>
                    <img
                      src={identityUrl(base + "/uploads/" + k)}
                      alt="待发送图片"
                    />
                    <button
                      aria-label="移除图片"
                      onClick={() =>
                        setImages((old) => old.filter((i) => i !== k))
                      }
                    >
                      <X size={13} />
                    </button>
                  </div>
                ))}
              </div>
            )}
            <textarea
              ref={input}
              aria-label="聊天消息"
              placeholder="说说今天的事…"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (
                  e.key === "Enter" &&
                  !e.shiftKey &&
                  !e.nativeEvent.isComposing
                ) {
                  e.preventDefault();
                  send();
                }
              }}
            />
            <div className="composer-bottom">
              <span>Enter 发送 · Shift + Enter 换行</span>
              <button
                className="primary"
                disabled={
                  busy || uploading || (!draft.trim() && !images.length)
                }
                onClick={send}
              >
                {busy ? (
                  <Loader2 size={16} className="spin" />
                ) : (
                  <Send size={16} />
                )}
                发送
              </button>
            </div>
          </div>
        </section>
      )}
      {panel && (
        <>
          <button
            className="drawer-backdrop"
            aria-label="关闭侧栏"
            onClick={() => setPanel(null)}
          />
          <aside className="drawer">
            <header>
              <h2>
                {
                  {
                    memory: "家庭记忆",
                    tasks: "家庭待办",
                    settings: "Agent 设置",
                    members: "群成员",
                  }[panel]
                }
              </h2>
              <button aria-label="关闭侧栏" onClick={() => setPanel(null)}>
                <X size={23} />
              </button>
            </header>
            <div className="drawer-content">
              {panel === "memory" && (
                <>
                  <p className="panel-intro">把家人的偏好和约定，放在心上。</p>
                  <div className="searchbox">
                    <Search size={16} />
                    <input
                      placeholder="搜索家庭记忆"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                    />
                  </div>
                  {memories
                    .filter((m) => m.content.includes(query))
                    .map((m) => (
                      <div className="memory-card" key={m.key}>
                        <div className="card-top">
                          <BookOpen size={18} />
                          <span>{m.manual ? "家人记录" : "聊天中记住"}</span>
                          <button
                            aria-label="编辑记忆"
                            onClick={() =>
                              setMemoryEdit({ key: m.key, content: m.content })
                            }
                          >
                            <Pencil size={16} />
                          </button>
                          <button
                            aria-label="删除记忆"
                            onClick={async () => {
                              if (
                                confirm("删除这条记忆？同一来源不会自动恢复。")
                              ) {
                                await api(base + "/memories/" + m.key, {
                                  method: "DELETE",
                                });
                                refresh();
                              }
                            }}
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                        <p>{m.content}</p>
                        <div className="memory-source">
                          {m.sources.length ? (
                            m.sources.map((id) => (
                              <button key={id} onClick={() => source(id)}>
                                来源：查看聊天
                              </button>
                            ))
                          ) : (
                            <span>手动添加</span>
                          )}
                          <span>
                            {new Date(m.updated * 1000).toLocaleDateString(
                              "zh-CN",
                              { month: "numeric", day: "numeric" },
                            )}
                          </span>
                        </div>
                        <button
                          className="revision-link"
                          onClick={async () =>
                            setRevisions(
                              await api(
                                base + "/memories/" + m.key + "/revisions",
                              ),
                            )
                          }
                        >
                          修订记录
                        </button>
                      </div>
                    ))}
                  {!memories.length && (
                    <Empty
                      icon={<BookOpen />}
                      text="记忆会从真实的聊天开始"
                      detail="你也可以手动记下家人的偏好。"
                    />
                  )}
                </>
              )}
              {panel === "tasks" && (
                <>
                  <p className="panel-intro">一家人的事，一起慢慢完成。</p>
                  {tasks.map((t) => (
                    <div
                      className={"task-card " + (t.done ? "done" : "")}
                      key={t.key}
                    >
                      <button
                        className="task-check"
                        aria-label={t.done ? "标为未完成" : "完成待办"}
                        onClick={() => saveTask({ ...t, done: !t.done })}
                      >
                        {t.done && <Check size={15} />}
                      </button>
                      <button
                        className="task-title"
                        onClick={() => setTaskEdit(t)}
                      >
                        <strong>{t.title}</strong>
                        <small>
                          {members.find((m) => m.id === t.owner_id)?.name ||
                            "未分配"}
                          {t.due
                            ? " · " +
                              new Date(t.due * 1000).toLocaleString("zh-CN", {
                                month: "numeric",
                                day: "numeric",
                                hour: "2-digit",
                                minute: "2-digit",
                              })
                            : ""}
                        </small>
                      </button>
                    </div>
                  ))}
                  {!tasks.length && (
                    <Empty
                      icon={<ListTodo />}
                      text="暂时没有待办"
                      detail="把要一起做的事情记下来吧。"
                    />
                  )}
                </>
              )}
              {panel === "members" && (
                <>
                  <p className="panel-intro">我们一家 · 3 位家人和 1 位助手</p>
                  <div className="identity-links">
                    {[
                      ["dad", "爸爸"],
                      ["mom", "妈妈"],
                      ["child", "小宇"],
                    ].map(([id, name]) => (
                      <a
                        key={id}
                        href={"/?user=" + id}
                        aria-current={user.username === id ? "page" : undefined}
                      >
                        切换为{name}
                      </a>
                    ))}
                  </div>
                  {[...members, { id: 0, name: agentName, online: true }].map(
                    (m) => (
                      <div className="member-row" key={m.id}>
                        <Avatar id={m.id} name={m.name} />
                        <div>
                          <strong>{m.name}</strong>
                          <small>
                            {m.id === 0
                              ? "家庭助手"
                              : m.online
                                ? "在线"
                                : "离线"}
                          </small>
                        </div>
                      </div>
                    ),
                  )}
                </>
              )}
              {panel === "settings" && config && (
                <>
                  <p className="panel-intro">让小忆以适合你们的方式陪伴。</p>
                  <form
                    className="settings-form"
                    onSubmit={async (e) => {
                      e.preventDefault();
                      try {
                        await api(base + "/settings", {
                          method: "PUT",
                          body: JSON.stringify(config),
                        });
                        settingsDirty.current = false;
                        notify("设置已保存");
                        refresh();
                      } catch (e) {
                        notify((e as Error).message);
                      }
                    }}
                  >
                    <label>
                      助手名称
                      <input
                        value={config.agent_name}
                        onChange={(e) => (
                          (settingsDirty.current = true),
                          setConfig({ ...config, agent_name: e.target.value })
                        )}
                        maxLength={20}
                        required
                      />
                    </label>
                    <label>
                      系统提示词
                      <textarea
                        rows={9}
                        value={config.prompt}
                        onChange={(e) => (
                          (settingsDirty.current = true),
                          setConfig({ ...config, prompt: e.target.value })
                        )}
                        required
                      />
                    </label>
                    <label className="toggle-label">
                      自主温和跟进
                      <input
                        type="checkbox"
                        checked={config.active}
                        onChange={(e) => (
                          (settingsDirty.current = true),
                          setConfig({ ...config, active: e.target.checked })
                        )}
                      />
                    </label>
                    <label>
                      观察窗口（秒）
                      <input
                        type="number"
                        min={1}
                        max={86400}
                        value={config.wait_seconds}
                        onChange={(e) => (
                          (settingsDirty.current = true),
                          setConfig({
                            ...config,
                            wait_seconds: Number(e.target.value),
                          })
                        )}
                      />
                    </label>
                    <p className="field-help">
                      只对明确且适合助手帮助的需求观察。相关回应会取消，普通聊天保持安静。
                    </p>
                    <label>
                      自主发言冷却（秒）
                      <input
                        type="number"
                        min={0}
                        max={86400}
                        value={config.cooldown_seconds ?? 300}
                        onChange={(e) => {
                          settingsDirty.current = true;
                          setConfig({
                            ...config,
                            cooldown_seconds: Number(e.target.value),
                          });
                        }}
                      />
                    </label>
                    <label>
                      群内每日关怀上限
                      <input
                        type="number"
                        min={0}
                        max={10}
                        value={config.care_group_limit ?? 1}
                        onChange={(e) => {
                          settingsDirty.current = true;
                          setConfig({
                            ...config,
                            care_group_limit: Number(e.target.value),
                          });
                        }}
                      />
                    </label>
                    <label className="toggle-label">
                      自主参与仅观察
                      <input
                        type="checkbox"
                        checked={config.participation_shadow ?? false}
                        onChange={(e) => {
                          settingsDirty.current = true;
                          setConfig({
                            ...config,
                            participation_shadow: e.target.checked,
                          });
                        }}
                      />
                    </label>
                    <div className="model-info">
                      <Bot size={17} />
                      <span>
                        {config.model}
                        <small>
                          {config.configured
                            ? "服务端已配置"
                            : "服务端尚未配置 Key"}
                        </small>
                      </span>
                    </div>
                    <button className="primary full">保存设置</button>
                  </form>
                  <div className="settings-section">
                    <h3>执行状态</h3>
                    {activity.failed.map((f) => (
                      <div className="failed-job" key={f.key}>
                        <p>{f.error}</p>
                        <button
                          onClick={async () => {
                            await api(base + "/retry/" + f.key, post({}));
                            notify("已重新加入处理队列");
                            refresh();
                          }}
                        >
                          <RefreshCw size={14} />
                          重试
                        </button>
                      </div>
                    ))}
                    {!activity.failed.length && (
                      <p className="field-help">暂无失败任务</p>
                    )}
                    <h3>最近的介入判断</h3>
                    {activity.logs.slice(0, 10).map((l, i) => (
                      <div className="activity" key={i}>
                        <time>{time(l.at)}</time>
                        <p>{l.reason}</p>
                      </div>
                    ))}
                    <h3>当前成员：{user.name}</h3>
                    <p className="field-help">
                      {user.authenticated
                        ? "已使用密码登录；当前浏览器共享此成员会话。切换成员需先在个人空间退出登录。"
                        : "当前为 URL 演示身份；个人空间需要单独密码登录。"}
                    </p>
                  </div>
                </>
              )}
            </div>
            {(panel === "memory" || panel === "tasks") && (
              <footer>
                <button
                  className="add-button"
                  onClick={() =>
                    panel === "memory"
                      ? setMemoryEdit({ content: "" })
                      : setTaskEdit({
                          key: "",
                          title: "",
                          done: false,
                          owner_id: null,
                          due: null,
                        })
                  }
                >
                  <Plus size={19} />
                  {panel === "memory" ? "新增记忆" : "新增待办"}
                </button>
              </footer>
            )}
          </aside>
        </>
      )}
      {memoryEdit && (
        <Modal
          title={memoryEdit.key ? "编辑记忆" : "新增家庭记忆"}
          close={() => setMemoryEdit(null)}
        >
          <textarea
            autoFocus
            rows={5}
            aria-label="记忆内容"
            placeholder="例如：妈妈喜欢清淡的口味"
            value={memoryEdit.content}
            onChange={(e) =>
              setMemoryEdit({ ...memoryEdit, content: e.target.value })
            }
          />
          <button className="primary full" onClick={saveMemory}>
            保存记忆
          </button>
        </Modal>
      )}
      {taskEdit && (
        <Modal
          title={taskEdit.key ? "编辑待办" : "新增家庭待办"}
          close={() => setTaskEdit(null)}
        >
          <form
            className="settings-form"
            onSubmit={(e) => {
              e.preventDefault();
              saveTask(taskEdit);
            }}
          >
            <label>
              要做的事
              <input
                autoFocus
                required
                value={taskEdit.title}
                onChange={(e) =>
                  setTaskEdit({ ...taskEdit, title: e.target.value })
                }
              />
            </label>
            <label>
              负责人
              <select
                value={taskEdit.owner_id || ""}
                onChange={(e) =>
                  setTaskEdit({
                    ...taskEdit,
                    owner_id: Number(e.target.value) || null,
                  })
                }
              >
                <option value="">未分配</option>
                {members.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              到期时间
              <input
                type="datetime-local"
                value={
                  taskEdit.due
                    ? new Date(
                        taskEdit.due * 1000 -
                          new Date().getTimezoneOffset() * 60000,
                      )
                        .toISOString()
                        .slice(0, 16)
                    : ""
                }
                onChange={(e) =>
                  setTaskEdit({
                    ...taskEdit,
                    due: e.target.value
                      ? new Date(e.target.value).getTime() / 1000
                      : null,
                  })
                }
              />
            </label>
            <button className="primary full">保存待办</button>
          </form>
        </Modal>
      )}
      {revisions && (
        <Modal title="记忆修订记录" close={() => setRevisions(null)}>
          {revisions.length ? (
            revisions.map((r, i) => (
              <div className="revision" key={i}>
                <small>{new Date(r.at * 1000).toLocaleString()}</small>
                <p>{r.previous.content}</p>
              </div>
            ))
          ) : (
            <p className="panel-intro">尚无修订记录</p>
          )}
        </Modal>
      )}
      {lightbox && (
        <div className="lightbox" onClick={() => setLightbox(null)}>
          <button aria-label="关闭图片">
            <X />
          </button>
          <img src={lightbox} alt="图片预览" />
        </div>
      )}
    </main>
  );
}
