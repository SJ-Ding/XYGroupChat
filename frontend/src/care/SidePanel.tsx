// 家人帮右侧面板：家庭健康看板 / 小艺在想什么（思考轨迹）/ 演示剧本（导演台）
import React, { useState } from "react";
import {
  LayoutDashboard, Brain, Clapperboard, Play, RotateCcw, FastForward, CircleCheck, Pill, Stethoscope,
  Footprints, Wrench, BookOpen, Database, Sparkles, Route, CreditCard, Bot, UserRound,
  ExternalLink, Clock, ShieldCheck, Map as MapIcon,
} from "lucide-react";
import { api, post } from "../api";
import { useLive, type Dashboard, type TraceTurn, type DemoState } from "./careApi";

const KIND: Record<string, { label: string; icon: React.ReactNode; cls: string }> = {
  rule: { label: "规则", icon: <Route size={13} />, cls: "k-rule" },
  llm: { label: "大模型", icon: <Sparkles size={13} />, cls: "k-llm" },
  tool: { label: "工具", icon: <Wrench size={13} />, cls: "k-tool" },
  skill: { label: "Skill", icon: <BookOpen size={13} />, cls: "k-skill" },
  memory: { label: "记忆", icon: <Database size={13} />, cls: "k-memory" },
  card: { label: "卡片", icon: <CreditCard size={13} />, cls: "k-card" },
  error: { label: "异常", icon: <Wrench size={13} />, cls: "k-error" },
};

export function ClockPill() {
  const { data } = useLive<Dashboard>("/api/care/dashboard", ["refresh", "care_trace", "message"], 10000);
  if (!data) return null;
  return (
    <span className="clock-pill" title="演示时钟（DemoClock）：可在「演示剧本」里快进">
      <Clock size={14} />{data.clock.label}<em>第 {data.clock.day} 天</em>
    </span>
  );
}

export default function SidePanel({ onClose }: { onClose?: () => void }) {
  const [tab, setTab] = useState<"board" | "trace" | "demo">(() => {
    try { return (localStorage.getItem("care-tab") as "board" | "trace" | "demo") || "demo"; } catch { return "demo"; }
  });
  function pick(t: typeof tab) {
    setTab(t);
    try { localStorage.setItem("care-tab", t); } catch { /* 忽略 */ }
  }
  return (
    <aside className="care-side" aria-label="家人帮面板">
      <nav className="care-tabs">
        <button className={tab === "demo" ? "on" : ""} onClick={() => pick("demo")}><Clapperboard size={15} />演示剧本</button>
        <button className={tab === "board" ? "on" : ""} onClick={() => pick("board")}><LayoutDashboard size={15} />家庭看板</button>
        <button className={tab === "trace" ? "on" : ""} onClick={() => pick("trace")}><Brain size={15} />小艺在想什么</button>
        {onClose && <button className="care-close" onClick={onClose} aria-label="收起面板">×</button>}
      </nav>
      <div className="care-scroll">
        {tab === "board" && <Board />}
        {tab === "trace" && <Trace />}
        {tab === "demo" && <Director onTrace={() => pick("trace")} />}
      </div>
    </aside>
  );
}

function Board() {
  const { data } = useLive<Dashboard>("/api/care/dashboard", ["refresh", "care_trace", "card_update", "message"], 8000);
  if (!data) return <div className="care-empty">正在读取家庭健康档案…</div>;
  return (
    <>
      <section className="board-week">
        <div><b>{data.week.checkins}</b><small>本周打卡</small></div>
        <div><b>{data.week.cards}</b><small>守护卡片</small></div>
        <div><b>{data.upcoming.length}</b><small>近期安排</small></div>
        <div className={data.week.emergencies ? "warn" : ""}><b>{data.week.emergencies}</b><small>急症拦截</small></div>
      </section>
      <h3 className="care-h">家庭健康概览</h3>
      {data.members.map((m) => (
        <div key={m.login} className="member-card">
          <span className={`member-avatar r-${m.role}`}>{m.real_name.slice(0, 1)}</span>
          <div className="member-body">
            <div className="member-line">
              <b>{m.real_name}</b><small>{m.name} · {m.age}岁</small>
              <span className={`lv lv-${m.level}`}>{m.tag}</span>
            </div>
            <small className="member-note">{[...m.conditions, ...m.allergies.map((a) => a + "过敏")].join(" · ") || m.note}</small>
            {m.adherence && m.adherence.rate !== null && (
              <div className="mini-bar"><Pill size={12} /><span>{m.adherence.title}</span>
                <i><em className={m.adherence.rate >= 90 ? "good" : m.adherence.rate >= 70 ? "warn" : "bad"} style={{ width: `${m.adherence.rate}%` }} /></i>
                <b>{m.adherence.taken}/{m.adherence.total}</b></div>
            )}
            {m.plan.filter((p) => p.type === "rehab").map((p) => (
              <div key={p.title} className="mini-bar"><Footprints size={12} /><span>{p.title}</span>
                <i><em className={(p.rate ?? 100) >= 90 ? "good" : (p.rate ?? 100) >= 70 ? "warn" : "bad"} style={{ width: `${p.rate ?? 0}%` }} /></i>
                <b>{p.taken}/{p.total}</b></div>
            ))}
          </div>
        </div>
      ))}
      <h3 className="care-h">接下来</h3>
      {data.upcoming.length ? data.upcoming.map((u, i) => (
        <div key={i} className={`up-item u-${u.kind}`}>
          {u.kind === "visit" || u.kind === "followup" ? <Stethoscope size={14} /> : u.kind === "rehab" ? <Footprints size={14} /> : <Pill size={14} />}
          <span>{u.label}</span><small>{u.when}</small>
        </div>
      )) : <div className="care-empty small">暂无安排</div>}
      <h3 className="care-h">家庭档案 <small>小艺记得的事</small></h3>
      <div className="profile-list">
        {data.profile.map((p, i) => (
          <div key={i} className={`profile-item d-${p.domain}`}>
            <span>{p.domain === "medical" ? "医疗" : "日常"}</span>{p.content}
          </div>
        ))}
      </div>
    </>
  );
}

function Trace() {
  const { data } = useLive<TraceTurn[]>("/api/care/trace", ["care_trace", "refresh"], 10000);
  const [open, setOpen] = useState<string | null>(null);
  if (!data) return <div className="care-empty">正在读取思考轨迹…</div>;
  if (!data.length) return <div className="care-empty">还没有就医相关的任务。<br />在「演示剧本」里点一步试试。</div>;
  return (
    <>
      <div className="trace-legend">
        {Object.entries(KIND).filter(([k]) => k !== "error").map(([k, v]) => <span key={k} className={v.cls}>{v.icon}{v.label}</span>)}
      </div>
      {data.map((t, i) => {
        const expanded = open === t.turn || (open === null && i === 0);
        const llm = t.steps.some((s) => s.kind === "llm");
        return (
          <section key={t.turn} className={`trace-turn ${i === 0 ? "latest" : ""}`}>
            <button className="trace-title" onClick={() => setOpen(expanded ? "" : t.turn)}>
              <b>{t.title}</b>
              <small>{t.steps.length} 步 · {t.ms}ms {llm ? "· 含大模型" : "· 纯规则"}</small>
            </button>
            {expanded && (
              <ol className="trace-steps">
                {t.steps.map((s) => {
                  const k = KIND[s.kind] || KIND.rule;
                  return (
                    <li key={s.n} className={k.cls}>
                      <span className="ts-icon">{k.icon}</span>
                      <div><b>{s.label}</b>{s.detail && <p>{s.detail}</p>}</div>
                      <em>{s.ms}ms</em>
                    </li>
                  );
                })}
              </ol>
            )}
          </section>
        );
      })}
    </>
  );
}

function Director({ onTrace }: { onTrace: () => void }) {
  const { data, reload } = useLive<DemoState>("/api/demo/state", ["refresh", "care_trace"], 6000);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [who, setWho] = useState("mom");
  const [line, setLine] = useState("");
  const [error, setError] = useState("");
  async function run(key: string, fn: () => Promise<unknown>) {
    setBusy(key);
    setError("");
    try {
      await fn();
      await reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  if (!data) return <div className="care-empty">正在连接演示导演台…</div>;
  const next = data.steps.find((s) => !s.done);
  return (
    <>
      <section className="dir-clock">
        <small>演示时钟 DemoClock</small>
        <b>{data.clock.label}</b>
        <span>第 {data.clock.day} 天</span>
        <div className="dir-clock-actions">
          <button onClick={() => run("clock", () => api("/api/demo/clock", post({ advance_minutes: 60 })))} disabled={!!busy}><FastForward size={14} />快进 1 小时</button>
          <button onClick={() => run("day", () => api("/api/demo/clock", post({ advance_minutes: 1440 })))} disabled={!!busy}><FastForward size={14} />快进 1 天</button>
        </div>
      </section>
      <section className="dir-status" aria-label="服务状态" aria-live="polite">
        <span className={data.controls.model ? "warn" : "off"}><Sparkles size={13} />
          {data.controls.model ? "模型故障已注入" : data.model.configured ? `对话模型 ${data.model.name} · 已配置` : "对话模型未配置"}
          {data.model_last && ` · 最近调用${data.model_last.failed ? "失败" : "成功"}`}</span>
        <span><Sparkles size={13} />识图模型 {data.vision}{data.controls.model ? " · 故障已注入" : " · 识图时验证可用性"}</span>
        <span className={data.controls.amap ? "warn" : "off"}><MapIcon size={13} />
          {data.controls.amap ? "地图故障已注入 · 距离估算" : data.amap ? "地图 MCP 已配置" : "地图未配置 · 距离估算"}
          {data.amap_last && ` · 最近请求${data.amap_last.ok ? "成功" : "失败"}`}</span>
        {!!data.distance_sources.length && <span>已缓存距离来源：{data.distance_sources.join("、")}</span>}
        <span><Bot size={13} />{data.browser_headless ? "浏览器后台模式" : "浏览器可视模式"} · 每步 {data.browser_pause_ms / 1000} 秒 · 启动后验证可用性</span>
      </section>
      <section className="dir-controls" aria-label="演示控制">
        <label><input type="checkbox" checked={data.controls.enabled} disabled={!!busy}
          onChange={e => run("mode", () => api("/api/demo/control", post({ enabled: e.target.checked })))} />启用演示控制</label>
        <small>仅影响演示家庭；退出或重置后清除故障。不改变业务授权。</small>
        {data.controls.enabled && <>
          <label><input type="checkbox" checked={data.controls.slow} disabled={!!busy}
            onChange={e => run("speed", () => api("/api/demo/control", post({ slow: e.target.checked })))} />演示慢速（3 秒／步，正常为 1.5 秒）</label>
          <div className="dir-faults">
            <button disabled={!!busy} aria-pressed={data.controls.model}
              onClick={() => run("fault-model", () => api("/api/demo/control", post({ model: !data.controls.model })))}>
              {data.controls.model ? "恢复模型" : "注入模型故障"}</button>
            <button disabled={!!busy} aria-pressed={data.controls.amap}
              onClick={() => run("fault-amap", () => api("/api/demo/control", post({ amap: !data.controls.amap })))}>
              {data.controls.amap ? "恢复地图" : "注入地图故障"}</button>
          </div>
        </>}
      </section>
      {!!data.browser_tasks.length && <section aria-label="浏览器步骤">
        <h3 className="care-h">浏览器当前步骤</h3>
        {data.browser_tasks.map(task => <div className="dir-task" key={task.task_id}>
          <b>{task.step || "等待浏览器启动"}</b><small>{task.status}</small>
          {task.error && <p role="alert">{task.error}</p>}
        </div>)}
      </section>}
      <h3 className="care-h">演示支线 <small>发送普通消息或注入事件，结果以实际执行为准</small></h3>
      {!data.controls.enabled && <p className="care-empty small">启用演示控制后可运行支线与故障注入。</p>}
      {data.controls.enabled && <div className="dir-branches">
        {data.branches.map(branch => <button key={branch.key} disabled={!!busy} title={branch.line}
          onClick={() => run("branch:" + branch.key, () => api(`/api/demo/branches/${branch.key}`, post({})))}>
          <small>{branch.priority} · {({mom: "妈妈", dad: "爸爸", child: "小林", system: "事件"} as Record<string,string>)[branch.actor]}</small>
          <b>{busy === "branch:" + branch.key ? "执行中…" : branch.title}</b>
        </button>)}
      </div>}
      <h3 className="care-h">演示剧本 <small>按顺序点，消息都走真实流程</small></h3>
      <ol className="dir-steps">
        {data.steps.map((s, i) => (
          <li key={s.key} className={`${s.done ? "done" : ""} ${next?.key === s.key ? "next" : ""}`}>
            <span className="dir-n">{s.done ? <CircleCheck size={16} /> : i + 1}</span>
            <div className="dir-body">
              <b>{s.title}</b>
              <small>{s.desc}</small>
              {s.line && <q>{s.line}</q>}
              {next?.key === s.key && <em>下一步：{s.next}</em>}
            </div>
            <button className="dir-run" onClick={() => run(s.key, () => api(`/api/demo/steps/${s.key}`, post({})))} disabled={!!busy}
              title={s.actor === "system" ? "推进剧情" : "以" + ({ mom: "妈妈", dad: "爸爸", child: "小林" } as Record<string, string>)[s.actor] + "身份发言"}>
              {busy === s.key ? "…" : <Play size={14} />}
            </button>
          </li>
        ))}
      </ol>
      <h3 className="care-h">替家人说一句</h3>
      <form className="dir-say" onSubmit={(e) => {
        e.preventDefault();
        if (!line.trim()) return;
        run("say", () => api("/api/demo/say", post({ user: who, content: line.trim() }))).then(() => setLine(""));
      }}>
        <select value={who} onChange={(e) => setWho(e.target.value)} aria-label="发言人">
          <option value="mom">妈妈</option><option value="dad">爸爸</option><option value="child">小林</option>
        </select>
        <input value={line} onChange={(e) => setLine(e.target.value)} placeholder="例如：头有点晕，想躺会儿" aria-label="替家人发言内容" />
        <button disabled={!!busy || !line.trim()}><UserRound size={14} />发送</button>
      </form>
      <h3 className="care-h">多端视角</h3>
      <div className="dir-links">
        <a href="/?user=mom&elder=1" target="_blank" rel="noreferrer"><ExternalLink size={13} />妈妈 · 长辈大字</a>
        <a href="/?user=dad&elder=1" target="_blank" rel="noreferrer"><ExternalLink size={13} />爸爸 · 长辈大字</a>
        <a href="/hospital/records" target="_blank" rel="noreferrer"><ExternalLink size={13} />医院 · 我的预约</a>
        <button onClick={onTrace}><Brain size={13} />看思考轨迹</button>
      </div>
      <div className="dir-reset">
        {confirmReset ? (
          <>
            <span>清空聊天与记录，回到第 0 天？</span>
            <button className="danger" onClick={() => run("reset", () => api("/api/demo/reset", post({})))} disabled={!!busy}>{busy === "reset" ? "重置中…" : "确认重置"}</button>
            <button onClick={() => setConfirmReset(false)}>取消</button>
          </>
        ) : (
          <button onClick={() => setConfirmReset(true)}><RotateCcw size={14} />重置演示数据</button>
        )}
      </div>
      {error && <p className="card-error" role="alert">{error}</p>}
      <p className="dir-foot"><ShieldCheck size={12} />小艺是就医辅助工具，不诊断疾病、不替代医生 · 所有医院与人物均为虚构演示数据</p>
    </>
  );
}

