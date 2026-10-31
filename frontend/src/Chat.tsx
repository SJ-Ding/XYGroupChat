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
  Stethoscope,
  Volume2,
  PanelRightOpen,
  Accessibility,
  Clock,
  Mic,
} from "lucide-react";
import SidePanel, { ClockPill } from "./care/SidePanel";
import { speak } from "./care/careApi";
import "./care/care.css";
import { ConversationCard, TaskBar } from "./ConversationCard";
import type { ChatCard, AgentTask } from "./types";
import AgentPage from "./AgentPage";
import AgentWorklist from "./AgentWorklist";
import MessageDetails from "./MessageDetails";
import { ExecutionChain, useExecutionChains } from "./ExecutionChain";
import { ChatAnnotation, useChatAnnotations } from "./ChatDebug";
import HarnessPage from "./HarnessPage";
import { Avatar, Modal, Empty } from "./components";
import { api, post, time, base, clientId, identityUrl } from "./api";
import type {
  User,
  Message,
  Memory,
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
  const observer = user.username === "agent";
  // 长辈大字模式：?elder=1 或手动切换（记在本机）
  const [elder, setElder] = useState(() => {
    const q = new URLSearchParams(location.search).get("elder");
    if (q !== null) return q === "1";
    try { return localStorage.getItem("elder-mode") === "1"; } catch { return false; }
  });
  const [careOpen, setCareOpen] = useState(() => {
    try { return localStorage.getItem("care-open") !== "0"; } catch { return true; }
  });
  function toggleElder() {
    setElder((v) => {
      try { localStorage.setItem("elder-mode", v ? "0" : "1"); } catch { /* 忽略 */ }
      return !v;
    });
  }
  function toggleCare() {
    setCareOpen((v) => {
      try { localStorage.setItem("care-open", v ? "0" : "1"); } catch { /* 忽略 */ }
      return !v;
    });
  }
  const [debugSelection, setDebugSelection] = useState<{source:number; keys?:string[]} | null>(null);
  const [cards, setCards] = useState<ChatCard[]>([]);
  const [agentTasks, setAgentTasks] = useState<AgentTask[]>([]);
  async function syncCards() {
    const tasks = await api<AgentTask[]>(base + "/agent-tasks");
    const rows = await api<ChatCard[]>(base + "/cards");
    setAgentTasks(tasks); setCards(rows);
  }
  const [messages, setMessages] = useState<Message[]>([]),
    [members, setMembers] = useState<User[]>([]),
    [panel, setPanel] = useState<Panel>(null),
    [config, setConfig] = useState<Config | null>(null),
    [memories, setMemories] = useState<Memory[]>([]),
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
    version?: number;
      key?: string;
      content: string;
    } | null>(null),
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
  const debugIds = [...new Set([...messages, ...searchResults].map(m => m.id))].sort((a,b)=>a-b).join(",");
  const annotations = useChatAnnotations(debugIds, observer);
  const chains = useExecutionChains(debugIds, observer);
  const [chainFocus, setChainFocus] = useState<number | null>(null);
  useEffect(() => {
    if (chainFocus === null) return;
    const el = document.getElementById("execution-chain-" + chainFocus) as HTMLDetailsElement | null;
    if (el) { el.open = true; el.scrollIntoView({ block: "center" }); setChainFocus(null); }
  }, [chainFocus, chains.rows]);
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
  async function refreshTasks() {
    const state = await api<{foreground: {status: string}}>(base + "/agent/status");
    setStatus(state.foreground.status);
  }
  async function refresh() {
    const [c, m, a, u] = await Promise.all([
      api<Config>(base + "/settings"),
      api<Memory[]>(base + "/memories"),
      api<Activity>(base + "/activity"),
      api<User[]>(base + "/members"),
    ]);
    setConfig((old) => (settingsDirty.current ? old : c));
    setMemories(m);
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
    refreshTasks().catch((e) => notify(e.message));
    syncCards().catch((e) => notify(e.message));
    const cardTimer = setInterval(() => { syncCards().then(() => sync()).catch(() => {}); }, 5000);
    function connect() {
      ws = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${identityUrl("/ws/1")}`,
      );
      ws.onopen = () => {
        setOnline(true);
        refreshTasks().catch(() => {});
        sync().catch((e) => notify(e.message));
        syncCards().catch((e) => notify(e.message));
        heartbeat = setInterval(() => {
          if (ws.readyState === 1) ws.send("ping");
        }, 25000);
      };
      ws.onmessage = (e) => {
        const event = JSON.parse(e.data);
        // 转发给家人帮面板（看板/轨迹/导演台）
        dispatchEvent(new CustomEvent("xy-event", { detail: event }));
        if (event.type === "reset") {
          location.reload();
          return;
        }
        if (event.type === "card_update" || event.type === "task_update" || event.type === "refresh") {
          syncCards().then(() => sync()).catch((e) => notify(e.message));
        }
        if (event.type === "message") {
          scrollToBottom.current = true;
          sync().catch((e) => notify(e.message));
        }
        if (event.type === "presence" || event.type === "refresh")
          refresh().catch(() => {});
        if (event.type === "task_update") {
          refreshTasks().catch(() => {});
        }
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
      clearInterval(cardTimer);
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
  // 长辈模式语音输入：浏览器自带语音识别（Chrome/Edge），识别结果放进输入框，由长辈点发送
  const [listening, setListening] = useState(false);
  function listen() {
    const w = window as unknown as Record<string, any>;
    const SR = w.SpeechRecognition || w.webkitSpeechRecognition;
    if (!SR) {
      notify("当前浏览器不支持语音输入，请用 Chrome 或 Edge 打开");
      return;
    }
    const r = new SR();
    r.lang = "zh-CN";
    r.interimResults = false;
    r.maxAlternatives = 1;
    r.onresult = (e: any) => {
      setDraft(e.results[0][0].transcript);
      input.current?.focus();
    };
    r.onerror = () => notify("没听清，再说一次吧");
    r.onend = () => setListening(false);
    setListening(true);
    r.start();
  }
  // 长辈模式一键发送常用语
  async function quick(text: string) {
    try {
      const row = await api<Message>(base + "/messages", post({ client_id: clientId(), content: text, attachments: [] }));
      scrollToBottom.current = true;
      merge([row]);
    } catch (e) {
      notify((e as Error).message);
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
          body: JSON.stringify({ content: memoryEdit.content, version: memoryEdit.version }),
        },
      );
      setMemoryEdit(null);
      await refresh();
    } catch (e) {
      notify((e as Error).message);
    }
  }
  const agentName = config?.agent_name || "小艺";
  return (
    <main className={`shell ${panel ? "with-panel" : ""} ${elder ? "elder-mode" : ""} ${careOpen && view === "chat" && !elder && !panel ? "with-care" : ""}`}>
      <nav className="rail" aria-label="主导航">
        <button
          className="profile"
          title={observer ? "Agent 聊天视角" : user.name}
          onClick={() => setPanel("members")}
        >
          <Avatar id={observer ? 0 : user.id} name={user.name} small />
        </button>
        <div className="rail-links">
          {[
            [null, MessageCircle, "聊天"],
            ["agent", Bot, "Agent"],
            ["harness", LockKeyhole, "个人与提醒"],
            ["memory", BookOpen, "家庭记忆"],
            ["tasks", ListTodo, "待办清单"],
            ["settings", Settings, "设置"],
          ].filter(([key]) => !observer || key === null).map(([key, Icon, label]) => {
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
          <button
            title="打开模拟医院"
            onClick={() =>
              window.open("/hospital/", "_blank", "noopener,noreferrer")
            }
          >
            <Stethoscope size={23} />
            <span>模拟医院</span>
          </button>
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
          <div className="brand compact">{agentName}</div>
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
                {messages.filter(m => !m.hidden).at(-1)?.content || "把日常的小事，慢慢聊给家人听。"}
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
                  {!observer && m.id === user.id && <em>我</em>}
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
                <em>陪伴管家</em>
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
                我们一家 <span>{observer ? "Agent 视角" : "4"}</span>
              </h1>
              <p>
                <i className={`dot ${online ? "online" : ""}`} />
                {online ? "已连接" : "正在重新连接…"}
                <span className="header-members">
                  {[...members.map((m) => m.name), agentName].join("、")}
                </span>
              </p>
            </div>
            <div className="header-actions">
              <ClockPill />
              {!observer && <button className={elder ? "selected" : ""} onClick={toggleElder} title="长辈大字模式：字更大、按钮更大，可以念给长辈听">
                <Accessibility size={18} />
                <span>{elder ? "退出大字" : "长辈大字"}</span>
              </button>}
              {!observer && !elder && <button className={careOpen ? "selected" : ""} onClick={toggleCare} title="家人帮面板：演示剧本 / 家庭看板 / 思考轨迹">
                <PanelRightOpen size={18} />
                <span>家人帮</span>
              </button>}
              {!observer && <button
                className={panel === "memory" ? "selected" : ""}
                onClick={() => setPanel(panel === "memory" ? null : "memory")}
              >
                <BookOpen size={18} />
                <span>家庭记忆</span>
              </button>}
              <button title="群成员" onClick={() => setPanel("members")}>
                <Users size={21} />
              </button>
            </div>
          </header>
          {!observer && <TaskBar tasks={agentTasks} locate={source} />}
          {observer && chains.error && <p role="alert" className="chat-debug-error">执行链路更新中断：{chains.error}。保留上次成功记录，正在重连。</p>}
          {observer && annotations.error && <p role="alert" className="chat-debug-error">分类信息连接中断：{annotations.error}。当前为上次成功记录。</p>}
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
            {(search ? searchResults : messages).filter(m => !m.hidden).map((m, i, all) => (
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
                {m.user_id === 0 && m.content.startsWith("—— ") ? (
                  <div className="clock-divider" id={"message-" + m.id}><span><Clock size={13} />{m.content.replace(/——/g, "").trim()}</span></div>
                ) : (
                <article
                  id={"message-" + m.id}
                  className={`message ${(observer ? m.user_id === 0 : m.user_id === user.id) ? "mine" : ""} ${m.user_id === 0 ? "agent-message" : ""} ${highlight === m.id ? "highlight" : ""}`}
                >
                  <Avatar id={m.user_id} name={m.name} />
                  <div className="message-body">
                    <div className="message-meta">
                      <span>{m.name}</span>
                      {m.user_id === 0 && <em>陪伴管家</em>}
                      <time>{time(m.created)}</time>
                    </div>
                    <div className="bubble">
                      {m.content && !cards.some(c => c.message_id === m.id) && !(m.cards?.length) && <p>{m.content}</p>}
                      {cards.filter(c => c.message_id === m.id).map(c => observer ? <div key={c.id}><strong>{c.title}</strong><p>{c.description}</p></div> : <ConversationCard key={c.id + ":" + c.version} card={c} onUpdate={syncCards} />)}
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
                    {m.user_id === 0 && elder && m.content && !cards.some(c => c.message_id === m.id) && (
                      <button className="speak-btn" onClick={() => speak(m.content)}><Volume2 size={18} />念给我听</button>
                    )}
                    {observer && m.user_id !== 0 && <ExecutionChain source={m.id} chain={chains.rows[m.id]} />}
                    {observer && m.user_id === 0 && annotations.rows[m.id]?.source && <button className="chain-revisit" onClick={async ()=>{const id=annotations.rows[m.id].source!;await source(id);setChainFocus(id);}}>回看执行链路</button>}
                    {observer && <ChatAnnotation agent={m.user_id === 0} annotation={annotations.rows[m.id]} open={(source,keys)=>setDebugSelection({source,keys})} />}
                    {m.user_id === 0 && user.authenticated && !observer && (
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
                )}
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
          {elder && !observer && (
            <div className="elder-quick">
              <button className={`mic ${listening ? "on" : ""}`} onClick={listen} disabled={listening}>
                <Mic size={20} />{listening ? "正在听…" : "说一句"}
              </button>
              {["药吃过了", "今天有点不舒服", `@${agentName} 帮我挂个号`, "我很好，放心"].map((t) => (
                <button key={t} onClick={() => quick(t)}>{t.replace("@" + agentName + " ", "")}</button>
              ))}
            </div>
          )}
          {observer ? <div className="observer-composer"><Bot size={19}/><span>Agent 聊天视角 · 只读观察 · 分类每 2 秒更新</span><a href="/?user=child">切换为小宇聊天</a></div> : <div className="composer">
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
          </div>}
        </section>
      )}
      {view === "chat" && careOpen && !elder && !observer && !panel && <SidePanel onClose={toggleCare} />}
      {debugSelection && <Modal title="消息上下文与决策" close={()=>setDebugSelection(null)}><MessageDetails source={debugSelection.source} traceKeys={debugSelection.keys} onSource={(id)=>{setDebugSelection(null);source(id);}}/></Modal>}
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
                    tasks: "待办清单",
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
                  <p className="panel-intro">
                    最近的安排先记几天，长久的偏好慢慢记牢。你随时可以更正或删除。
                  </p>
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
                          <span>
                            {m.manual
                              ? "家人记录"
                              : m.lifetime === "working"
                                ? "今天的近况"
                                : m.lifetime === "short"
                                  ? "近期记住"
                                  : "慢慢记牢"}
                            {m.tentative ? " · 尚未确定" : ""}
                          </span>
                          <button
                            aria-label="编辑记忆"
                            onClick={() =>
                              setMemoryEdit({ key: m.key, content: m.content, version: m.version })
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
                        {m.expires_at && (
                          <small>
                            保留到{" "}
                            {new Date(m.expires_at * 1000).toLocaleString(
                              "zh-CN",
                              {
                                month: "numeric",
                                day: "numeric",
                                hour: "2-digit",
                                minute: "2-digit",
                              },
                            )}
                          </small>
                        )}
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
              {panel === "tasks" && <AgentWorklist onSource={(id) => { setPanel(null); navigate("chat"); source(id); }} />}
              {panel === "members" && (
                <>
                  <p className="panel-intro">我们一家 · 3 位家人和 1 位助手</p>
                  <div className="identity-links">
                    {[
                      ["dad", "爸爸"],
                      ["mom", "妈妈"],
                      ["child", "小宇"],
                      ["agent", "Agent 聊天视角"],
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
                              ? "陪伴管家"
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
                  <p className="panel-intro">
                    让{agentName}以适合你们的方式陪伴。
                  </p>
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
                    <label className="toggle-label">
                      自动记下近期安排
                      <input
                        type="checkbox"
                        checked={config.memory_auto ?? true}
                        onChange={(e) => {
                          settingsDirty.current = true;
                          setConfig({
                            ...config,
                            memory_auto: e.target.checked,
                          });
                        }}
                      />
                    </label>
                    <label>
                      短期记忆默认保留（天）
                      <input
                        type="number"
                        min={1}
                        max={30}
                        value={config.memory_short_days ?? 7}
                        onChange={(e) => {
                          settingsDirty.current = true;
                          setConfig({
                            ...config,
                            memory_short_days: Number(e.target.value),
                          });
                        }}
                      />
                    </label>
                    <label>
                      定期整理间隔（小时）
                      <input
                        type="number"
                        min={1}
                        max={168}
                        value={(config.memory_review_seconds ?? 21600) / 3600}
                        onChange={(e) => {
                          settingsDirty.current = true;
                          setConfig({
                            ...config,
                            memory_review_seconds:
                              Number(e.target.value) * 3600,
                          });
                        }}
                      />
                    </label>
                    <p className="field-help">
                      新近况会在消息分析后静默记下，约5分钟后复核；平时按间隔整理。临时感受最多记一天，稳定偏好需要多天反复支持才会转为长期记忆。
                    </p>
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
            {panel === "memory" && (
              <footer>
                <button className="add-button" onClick={() => setMemoryEdit({ content: "" })}>
                  <Plus size={19} />新增记忆
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
