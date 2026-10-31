// 家人帮 · 就医守护富卡片：建议 / 号源对比 / 支付 / 凭证 / 守护计划 / 打卡 / 依从性 / 复诊简报 / 急症
import React, { useState } from "react";
import {
  Lightbulb, Hospital, MapPin, Clock, Wallet, CalendarPlus, BellRing, Siren, Phone, Pill, Activity,
  ClipboardList, Stethoscope, Sparkles, CircleCheck, CircleX, Circle, ShieldCheck, CloudSun, Check,
  Loader2, Footprints, BadgeCheck,
} from "lucide-react";
import type { ChatCard } from "../types";
import { api, post } from "../api";
import { careAct } from "./careApi";

type D = Record<string, any>;

function useAct(card: ChatCard, onUpdate: () => Promise<void>) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  async function act(action: string, extra: Record<string, unknown> = {}) {
    if (busy) return;
    setBusy(action + (extra.option ? ":" + extra.option : ""));
    setError("");
    try {
      if (card.care?.data.prognosis) {
        await api(`/api/groups/${card.care.data.gid}/prognosis/${encodeURIComponent(card.id)}/act`, post({ action, ...extra }));
      } else await careAct(card.id, action, extra);
      await onUpdate();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  return { busy, error, act };
}

function Head({ icon, tone, title, chip, chipTone }: { icon: React.ReactNode; tone: string; title: string; chip?: string; chipTone?: string }) {
  return (
    <div className="cc-head">
      <span className={`cc-icon tone-${tone}`}>{icon}</span>
      <strong>{title}</strong>
      {chip && <span className={`cc-chip ${chipTone || ""}`}>{chip}</span>}
    </div>
  );
}

function Btn({ children, onClick, kind = "primary", busy, disabled }: { children: React.ReactNode; onClick: () => void; kind?: string; busy?: boolean; disabled?: boolean }) {
  return (
    <button type="button" className={`cc-btn ${kind}`} onClick={onClick} disabled={busy || disabled}>
      {busy && <Loader2 size={15} className="spin" />}
      {children}
    </button>
  );
}

function Result({ text }: { text?: string }) {
  if (!text) return null;
  return <div className="cc-result"><Check size={14} /> {text}</div>;
}

export function CareCard({ card, onUpdate }: { card: ChatCard; onUpdate: () => Promise<void> }) {
  const care = card.care!;
  const d: D = care.data;
  const actions = care.actions || [];
  const open = card.status === "active";
  const { busy, error, act } = useAct(card, onUpdate);
  const can = (a: string) => open && actions.includes(a);
  // 守护计划每项的开关（hooks 必须在顶层声明）
  const [enabled, setEnabled] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(((d.items as D[]) || []).map((i) => [i.key, i.enabled !== false])));
  let body: React.ReactNode = null;

  if (care.type === "need_hint") {
    body = (
      <>
        <Head icon={<Lightbulb size={17} />} tone="amber" title="小艺建议" chip="主动发现" chipTone="amber" />
        <blockquote className="cc-quote">{d.member_name}：“{d.quote}”</blockquote>
        <div className="cc-tags">
          {(d.history || []).slice(0, 1).map((h: string) => <span key={h} className="cc-tag"><ClipboardList size={13} />{h.replace(/^.*?）/, "").slice(0, 26)}</span>)}
          {d.weather && <span className="cc-tag"><CloudSun size={13} />{d.weather.city}今天{d.weather.weather} {d.weather.temp}</span>}
          <span className="cc-tag"><Stethoscope size={13} />建议 {d.department}</span>
        </div>
        <p className="cc-text">要我帮{d.member_name}看看 <b>{d.date_label}{d.session === "morning" ? "上午" : "下午"}</b> {d.department}的号吗？</p>
        {open ? (
          <div className="cc-actions">
            <Btn onClick={() => act("accept")} busy={busy === "accept"}>好的，帮挂号</Btn>
            <Btn kind="ghost" onClick={() => act("dismiss")} busy={busy === "dismiss"}>先不用</Btn>
          </div>
        ) : <Result text={d.result} />}
      </>
    );
  }

  if (care.type === "hospital_apps") {
    body = <>
      <Head icon={<Hospital size={17} />} tone="blue" title="选择医院应用" />
      <div className="cc-sub">为 {d.real_name} 预约 {d.department}，请选择办理医院。</div>
      <div className="opt-list">{d.hospitals.map((h: D) => <div className="opt" key={h.id}>
        <div className="opt-main"><b>{h.name}</b><p>{h.address}</p><small>独立模拟预约应用 · 医院信息来自高德{h.available === false && " · 暂无该科室"}</small></div>
        {can("choose_hospital") && <Btn disabled={h.available === false} busy={busy === "choose_hospital:" + h.id} onClick={() => act("choose_hospital", { option: h.id })}>选择此医院</Btn>}
      </div>)}</div>
      {!open && <Result text={d.result} />}
    </>;
  }

  if (care.type === "hospital_options") {
    const chosen = d.chosen as string | undefined;
    body = (
      <>
        <Head icon={<Hospital size={17} />} tone="blue" title={card.title} chip={`${d.options.length} 个可约`} chipTone="blue" />
        <div className="cc-sub">就诊人 <b>{d.real_name}</b>{d.familiar_doctor && <> · 优先找上次的 <b>{d.familiar_doctor}</b> 医生</>}</div>
        <div className="opt-list">
          {d.options.map((o: D) => {
            const parts = o.score_parts as Record<string, number>;
            const w = d.weights as Record<string, number>;
            return (
              <div key={o.id} className={`opt ${o.rank === 1 ? "best" : ""} ${chosen ? (chosen === o.id ? "chosen" : "dim") : ""}`}>
                <span className="opt-rank">{o.rank}</span>
                <div className="opt-main">
                  <div className="opt-title">
                    <b>{o.campus}</b> · {o.doctor}<small>{o.title}</small>
                    {o.rank === 1 && <span className="cc-chip green">推荐</span>}
                    {o.note && <span className="cc-chip">{o.note}</span>}
                  </div>
                  <ul className="opt-reasons">
                    {o.reasons.map((r: string) => <li key={r}><Check size={12} />{r}</li>)}
                  </ul>
                  <div className="opt-score" title={`距离${parts.distance} · 熟悉度${parts.familiar} · 连续性${parts.continuity} · 职称${parts.title}`}>
                    <span className="seg s1" style={{ width: `${w.distance * parts.distance * 100}%` }} />
                    <span className="seg s2" style={{ width: `${w.familiar * parts.familiar * 100}%` }} />
                    <span className="seg s3" style={{ width: `${w.continuity * parts.continuity * 100}%` }} />
                    <span className="seg s4" style={{ width: `${w.title * parts.title * 100}%` }} />
                    <em>{o.score}分</em>
                  </div>
                </div>
                <div className="opt-slot">
                  <div className="opt-time">{o.time}</div>
                  <div className="opt-fee">¥{o.fee}</div>
                  {can("choose") && (
                    <Btn onClick={() => act("choose", { option: o.id })} busy={busy === "choose:" + o.id}>选这个</Btn>
                  )}
                  {chosen === o.id && <span className="cc-chip green">已选</span>}
                </div>
              </div>
            );
          })}
          {(d.compare || []).map((o: D) => (
            <div key={o.id} className="opt none">
              <span className="opt-rank">—</span>
              <div className="opt-main">
                <div className="opt-title"><b>{o.campus}</b><span className="cc-chip gray">对比项</span></div>
                <ul className="opt-reasons muted">
                  <li><MapPin size={12} />{o.distance_km} 公里 · 驾车约 {o.eta_min} 分钟（最近）</li>
                  <li><CircleX size={12} />{o.note}</li>
                </ul>
              </div>
              <div className="opt-slot"><div className="opt-none">无号</div></div>
            </div>
          ))}
        </div>
        <div className="cc-legend">
          <span><i className="s1" />距离 45%</span><span><i className="s2" />熟悉度 30%</span>
          <span><i className="s3" />医生连续性 15%</span><span><i className="s4" />职称 10%</span>
          <em>代码打分 · 理由由数据模板生成</em>
        </div>
        {open ? (
          <div className="cc-actions"><Btn kind="ghost" onClick={() => act("next_day")} busy={busy === "next_day"}>看看后一天</Btn></div>
        ) : <Result text={d.result} />}
      </>
    );
  }

  if (care.type === "payment") {
    const paid = d.pay_status === "paid";
    body = (
      <>
        <Head icon={<Wallet size={17} />} tone="amber" title={paid ? "挂号费已支付" : "锁号成功 · 待支付"} chip={paid ? "已支付" : "15 分钟内支付"} chipTone={paid ? "green" : "amber"} />
        <div className="pay-amount"><small>¥</small>{d.fee}</div>
        <div className="cc-sub center">{d.campus} · {d.department} · {d.doctor}（{d.title}）<br />{d.date_label} {d.time} · 就诊人 {d.patient_name}</div>
        {paid ? (
          <div className="pay-stamp"><BadgeCheck size={18} />支付完成</div>
        ) : (
          <div className="cc-actions center">
            <a className="cc-btn primary" href={d.pay_url} target="_blank" rel="noreferrer">去收银台支付</a>
          </div>
        )}
        <div className="cc-note"><ShieldCheck size={13} />小艺没有支付能力，付款只能由本人在收银台确认</div>
      </>
    );
  }

  if (care.type === "receipt") {
    body = (
      <>
        <Head icon={<CircleCheck size={17} />} tone="green" title="挂号凭证" chip="已完成" chipTone="green" />
        <div className="ticket">
          <div className="ticket-top"><small>预约编号</small><b>{d.appt_id}</b></div>
          <dl className="cc-grid">
            <dt>就诊人</dt><dd>{d.patient_name}</dd>
            <dt>医院</dt><dd>{d.campus}</dd>
            <dt>科室 / 医生</dt><dd>{d.department} · {d.doctor}</dd>
            <dt>就诊时间</dt><dd><b>{d.date_label} {d.time}</b></dd>
            <dt>地址</dt><dd>{d.address}</dd>
            <dt>已支付</dt><dd>¥{d.fee}</dd>
          </dl>
        </div>
        <div className="cc-tags">
          <a className="cc-tag link" href={d.calendar_url}><CalendarPlus size={13} />加入日历（.ics）</a>
          <span className="cc-tag"><BellRing size={13} />{d.reminder}</span>
        </div>
      </>
    );
  }

  if (care.type === "care_plan") {
    const icons: Record<string, React.ReactNode> = { medication: <Pill size={15} />, rehab: <Footprints size={15} />, followup: <Stethoscope size={15} /> };
    const labels: Record<string, string> = { medication: "用药", rehab: "康复", followup: "复诊" };
    body = (
      <>
        <Head icon={<ShieldCheck size={17} />} tone="green" title="就诊后守护计划" chip="按医嘱" chipTone="green" />
        <div className="cc-sub">来源：{d.source}</div>
        <div className="cc-diagnosis"><small>诊断</small>{d.diagnosis}</div>
        <div className="plan-list">
          {d.items.map((i: D) => (
            <label key={i.key} className={`plan-item t-${i.type} ${enabled[i.key] ? "" : "off"}`}>
              <span className="plan-icon">{icons[i.type]}</span>
              <span className="plan-body">
                <b>{labels[i.type]} · {i.title}</b>
                <small>{i.detail}</small>
                <small className="plan-when"><Clock size={11} />{i.schedule}</small>
              </span>
              {open && (
                <input type="checkbox" className="switch" checked={!!enabled[i.key]}
                  onChange={(e) => setEnabled({ ...enabled, [i.key]: e.target.checked })} aria-label={"启用" + i.title} />
              )}
            </label>
          ))}
        </div>
        <div className="cc-note">
          <Sparkles size={13} />{d.extracted_by === "llm" ? "大模型从病历医嘱中结构化提取" : "按病历结构化字段生成（离线规则）"} · 不新增药物、不改剂量
        </div>
        {open ? (
          <div className="cc-actions">
            <Btn onClick={() => act("confirm_plan", { enabled: Object.keys(enabled).filter((k) => enabled[k]) })} busy={busy === "confirm_plan"}>确认计划</Btn>
            <Btn kind="ghost" onClick={() => act("dismiss")} busy={busy === "dismiss"}>暂不启用</Btn>
          </div>
        ) : <><Result text={d.result} />{d.prognosis && actions.includes("cancel_plan") && <div className="cc-actions"><Btn kind="ghost" busy={busy === "cancel_plan"} onClick={() => act("cancel_plan")}>取消提醒</Btn></div>}</>}
      </>
    );
  }

  if (care.type === "med_checkin") {
    const med = d.kind === "medication";
    body = (
      <div className="checkin">
        <span className={`checkin-icon ${med ? "med" : "rehab"}`}>{med ? <Pill size={30} /> : <Activity size={30} />}</span>
        <div className="checkin-body">
          <small>{d.time} · {d.reason}</small>
          <b>{d.title}</b>
          <span>{d.detail}</span>
        </div>
        {open ? (
          <div className="checkin-actions">
            <Btn onClick={() => act("taken")} busy={busy === "taken"}><Check size={18} />已{med ? "吃" : "做"}</Btn>
            {actions.includes("snooze") && <Btn kind="ghost" onClick={() => act("snooze")} busy={busy === "snooze"}>稍后提醒</Btn>}
          </div>
        ) : <div className="checkin-done"><CircleCheck size={22} />{d.result || "已打卡"}</div>}
      </div>
    );
  }

  if (care.type === "adherence") {
    body = (
      <>
        <Head icon={<Pill size={17} />} tone={d.level === "good" ? "green" : d.level === "warn" ? "amber" : "red"} title={card.title}
          chip={d.level === "good" ? "按时" : "需关注"} chipTone={d.level === "good" ? "green" : d.level === "warn" ? "amber" : "red"} />
        <div className="cc-sub">{d.real_name} · {d.title}（{d.detail}）</div>
        <div className="week-dots">
          {d.days.map((x: D) => (
            <div key={x.date} className={`wd ${x.status}`}>
              <span className="wd-dot">{x.status === "taken" ? <Check size={14} /> : x.status === "missed" ? <CircleX size={14} /> : <Circle size={12} />}</span>
              <small>{x.weekday}</small>
              <em>{x.label}</em>
            </div>
          ))}
        </div>
        <div className="rate-bar"><span className={d.level} style={{ width: `${d.rate}%` }} /></div>
        <div className="rate-text">
          <span>已服 <b>{d.taken}/{d.total}</b> 天</span>
          <span className={d.level}>依从率 <b>{d.rate}%</b></span>
        </div>
        {d.missed?.length > 0 && <div className="cc-warn">⚠ {d.missed.join("、")}漏服{d.today_pending ? "，今天早上的还没打卡" : ""}</div>}
        {open ? (
          <div className="cc-actions">
            <Btn kind="warm" onClick={() => act("nudge")} busy={busy === "nudge"}>提醒{d.member_name}吃药</Btn>
            <Btn kind="ghost" onClick={() => act("dismiss")} busy={busy === "dismiss"}>稍后再说</Btn>
          </div>
        ) : <Result text={d.result} />}
      </>
    );
  }

  if (care.type === "followup") {
    const o = d.option as D | null;
    const bar = (s: D | null, label: string) => s && (
      <div className="brief-bar">
        <span>{label}：{s.title}</span>
        <div className="rate-bar thin"><span className={s.rate >= 90 ? "good" : s.rate >= 70 ? "warn" : "bad"} style={{ width: `${s.rate}%` }} /></div>
        <b>{s.taken}/{s.total} 天 · {s.rate}%</b>
      </div>
    );
    body = (
      <>
        <Head icon={<BellRing size={17} />} tone="blue" title="复诊提醒 · 就诊简报" chip="明天复诊" chipTone="blue" />
        {o && (
          <dl className="cc-grid four">
            <dt>就诊人</dt><dd>{d.real_name}</dd><dt>医院</dt><dd>{o.campus}</dd>
            <dt>医生</dt><dd>{o.doctor}（上次）</dd><dt>时间</dt><dd><b>{o.date_label} {o.time}</b></dd>
          </dl>
        )}
        <div className="brief">
          <div className="brief-title"><ClipboardList size={14} />就诊简报 · 康复第 {d.day_n} 天</div>
          <div className="brief-line">上次诊断：{d.diagnosis}</div>
          {bar(d.medication, "用药")}
          {bar(d.rehab, "康复")}
        </div>
        <div className="brief">
          <div className="brief-title"><Sparkles size={14} />建议问医生 <small>{d.generated_by === "llm" ? "大模型生成" : "模板"}</small></div>
          <ol className="brief-q">{d.questions.map((q: string) => <li key={q}>{q}</li>)}</ol>
        </div>
        {open ? (
          <div className="cc-actions">
            {o && <Btn onClick={() => act("book")} busy={busy === "book"}>确认挂号 · ¥{o.fee}</Btn>}
            <Btn kind="ghost" onClick={() => act("reschedule")} busy={busy === "reschedule"}>改约其他时间</Btn>
          </div>
        ) : <Result text={d.result} />}
      </>
    );
  }

  if (care.type === "emergency") {
    body = (
      <>
        <Head icon={<Siren size={17} />} tone="red" title="急症提醒：请立即就医" chip="紧急" chipTone="red solid" />
        <div className="er-reason">{d.reason}</div>
        <blockquote className="cc-quote red">{d.member_name}：“{d.quote}”</blockquote>
        <ol className="er-advice">{d.advice.map((a: string) => <li key={a}>{a}</li>)}</ol>
        {d.nearest && (
          <div className="er-near"><Hospital size={15} />
            <div><b>{d.nearest.name}</b><small>{d.nearest.address}{d.nearest.distance_km ? ` · 约 ${d.nearest.distance_km}km` : ""} · {d.nearest.source}</small></div>
          </div>
        )}
        <div className="cc-actions">
          <a className="cc-btn danger" href="tel:120"><Phone size={16} />拨打 120</a>
          {open && <Btn kind="ghost" onClick={() => act("called")} busy={busy === "called"}>已拨打</Btn>}
          {open && <Btn kind="ghost" onClick={() => act("safe")} busy={busy === "safe"}>虚惊一场</Btn>}
        </div>
        {d.notified && <div className="cc-note red"><BellRing size={13} />已同步通知照护人 {d.notified}</div>}
        {!open && <Result text={d.result} />}
      </>
    );
  }

  return (
    <section className={`care-card cc-${care.type} ${open ? "" : "is-done"}`} aria-label={card.title}>
      {body || <strong>{card.title}</strong>}
      {error && <p className="card-error" role="alert">{error}</p>}
    </section>
  );
}
