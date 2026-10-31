import { useEffect, useState } from 'react';
import { ChevronRight, Bot } from 'lucide-react';
import { HOSPITAL } from './data';

// 院徽：自绘图形（不使用任何医院的真实标识）
export function Emblem({ size = 52 }: { size?: number }) {
  const t = HOSPITAL.theme;
  const ch = HOSPITAL.short.slice(0, 1);
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <circle cx="32" cy="32" r="30" fill="#fff" stroke={t.primary} strokeWidth="3" />
      <circle cx="32" cy="32" r="23" fill="none" stroke={t.accent} strokeWidth="1.5" strokeDasharray="3 3" />
      <rect x="27" y="14" width="10" height="36" rx="2" fill={t.primary} />
      <rect x="14" y="27" width="36" height="10" rx="2" fill={t.primary} />
      <text x="32" y="36.5" textAnchor="middle" fontSize="11" fontWeight="700" fill="#fff" fontFamily="serif">{ch}</text>
    </svg>
  );
}

// 小艺代为操作时的顶部横幅：浏览器执行器通过 sessionStorage + 自定义事件更新当前步骤，
// 让评委和家人能看清“哪一步是小艺在点”。普通访客不显示。
export function AgentBanner() {
  const read = () => {
    try {
      return { on: sessionStorage.getItem('agent_driving') === '1', step: sessionStorage.getItem('agent_step') || '' };
    } catch {
      return { on: false, step: '' };
    }
  };
  const [state, setState] = useState(read);
  useEffect(() => {
    const update = () => setState(read());
    window.addEventListener('agent-step', update);
    const timer = setInterval(update, 500);
    return () => { window.removeEventListener('agent-step', update); clearInterval(timer); };
  }, []);
  if (!state.on) return null;
  return (
    <div data-testid="agent-banner" className="sticky top-0 z-40 flex items-center justify-center gap-3 py-2 text-sm text-white" style={{ background: 'linear-gradient(90deg,#FF7A45,#F5A623)' }}>
      <span className="grid h-6 w-6 place-items-center rounded-full bg-white/25"><Bot className="h-4 w-4" /></span>
      <span className="font-medium">小艺正在代为操作</span>
      {state.step && <span className="rounded-full bg-white/20 px-3 py-0.5">{state.step}</span>}
      <span className="text-white/85">· 填到付款前会停下，请家人在小艺里确认；锁号后由本人完成模拟支付</span>
    </div>
  );
}

export function Breadcrumb({ items }: { items: string[] }) {
  return (
    <nav className="mb-4 flex items-center gap-1.5 text-sm" style={{ color: 'var(--h-sub)' }}>
      <span>当前位置：</span>
      {items.map((item, i) => (
        <span key={i} className="flex items-center gap-1.5">
          {i > 0 && <ChevronRight className="w-3.5 h-3.5" />}
          <span className={i === items.length - 1 ? 'font-medium' : ''} style={i === items.length - 1 ? { color: 'var(--h-deep)' } : {}}>{item}</span>
        </span>
      ))}
    </nav>
  );
}

export function StepBar({ step }: { step: number }) {
  const steps = ['选择科室', '选择医生与号源', '选择就诊人', '核对信息', '支付（演示不进行）'];
  return (
    <div className="h-card flex items-stretch overflow-hidden">
      {steps.map((s, i) => {
        const on = i + 1 === step, done = i + 1 < step;
        return (
          <div key={s} className="relative flex flex-1 items-center justify-center gap-2 py-3 text-sm font-medium"
            style={on ? { background: 'var(--h-primary)', color: '#fff' } : done ? { background: 'var(--h-soft)', color: 'var(--h-primary)' } : { color: '#94A3B8' }}>
            <span className="grid h-5 w-5 place-items-center rounded-full text-xs"
              style={on ? { background: 'rgba(255,255,255,.25)' } : done ? { background: 'var(--h-primary)', color: '#fff' } : { background: '#E2E8F0' }}>{i + 1}</span>
            {s}
          </div>
        );
      })}
    </div>
  );
}
