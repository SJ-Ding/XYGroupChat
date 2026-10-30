import { ChevronRight } from 'lucide-react';

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
