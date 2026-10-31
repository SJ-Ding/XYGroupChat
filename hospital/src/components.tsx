import { appStorageKey } from './data';
import { useEffect, useState } from 'react';
import { ChevronRight, Bot } from 'lucide-react';

// 小艺代为操作时的顶部横幅：浏览器执行器通过 sessionStorage + 自定义事件更新当前步骤，
// 让评委和家人能看清“哪一步是小艺在点”。普通访客不显示。
export function AgentBanner() {
  const read = () => {
    try {
      return { on: sessionStorage.getItem(appStorageKey('agent_driving')) === '1', step: sessionStorage.getItem(appStorageKey('agent_step')) || '' };
    } catch {
      return { on: false, step: '' };
    }
  };
  const [state, setState] = useState(read);
  useEffect(() => {
    const update = () => setState(read());
    window.addEventListener('agent-step', update);
    const timer = setInterval(update, 800);
    return () => { window.removeEventListener('agent-step', update); clearInterval(timer); };
  }, []);
  if (!state.on) return null;
  return (
    <div data-testid="agent-banner" className="sticky z-40 flex items-center justify-center gap-3 py-2 text-sm text-white" style={{ top: 68, background: 'linear-gradient(90deg,#FF7A45,#F5A623)' }}>
      <span className="grid h-6 w-6 place-items-center rounded-full bg-white/25"><Bot className="h-4 w-4" /></span>
      <span className="font-medium">小艺正在代为操作</span>
      {state.step && <span className="rounded-full bg-white/20 px-3 py-0.5">{state.step}</span>}
      <span className="text-white/80">· 提交前会请家人确认，支付必须本人完成</span>
    </div>
  );
}

export function Breadcrumb({ items }: { items: string[] }) {
  return (
    <nav className="mb-4 flex items-center gap-1.5 text-sm" style={{ color: '#64748B' }}>
      {items.map((item, i) => (
        <span key={i} className="flex items-center gap-1.5">
          {i > 0 && <ChevronRight className="w-3.5 h-3.5" />}
          <span className={i === items.length - 1 ? 'font-medium' : ''} style={i === items.length - 1 ? { color: '#183B56' } : {}}>{item}</span>
        </span>
      ))}
    </nav>
  );
}

export function StepBar({ step }: { step: number }) {
  const steps = ['选择科室', '选择排班', '选择就诊人', '确认预约'];
  return (
    <div className="flex items-center gap-2">
      {steps.map((s, i) => (
        <div key={s} className="flex items-center gap-2">
          {i > 0 && <ChevronRight className="w-4 h-4" style={{ color: '#CBD5E1' }} />}
          <span
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium"
            style={i + 1 === step ? { background: '#176A9B', color: '#fff' } : i + 1 < step ? { background: '#E0F2FE', color: '#176A9B' } : { background: '#F1F5F9', color: '#94A3B8' }}
          >
            <span className="grid h-5 w-5 place-items-center rounded-full text-xs" style={i + 1 === step ? { background: 'rgba(255,255,255,.25)' } : i + 1 < step ? { background: '#176A9B', color: '#fff' } : { background: '#E2E8F0' }}>{i + 1}</span>
            {s}
          </span>
        </div>
      ))}
    </div>
  );
}
