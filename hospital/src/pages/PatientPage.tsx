import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronLeft, User, CheckCircle2, ShieldCheck } from 'lucide-react';
import { PATIENTS, getDraft, saveDraft, to } from '../data';
import { Breadcrumb, StepBar } from '../components';

export function PatientPage() {
  const navigate = useNavigate();
  const [selected, setSelected] = useState<string>(getDraft().patientId || PATIENTS.find((p) => p.isDefault)?.id || '');
  function pick(id: string) {
    setSelected(id);
    saveDraft({ ...getDraft(), patientId: id });
  }
  return (
    <div className="wrap py-6">
      <Breadcrumb items={['首页', '预约挂号', '选择就诊人']} />
      <StepBar step={3} />
      <h1 className="h-title mt-6" style={{ fontSize: 20 }}>选择就诊人</h1>
      <p className="mt-1 flex items-center gap-1 text-sm" style={{ color: 'var(--h-sub)' }}><ShieldCheck className="h-4 w-4" />实名就诊：请选择与证件一致的就诊人</p>
      <div className="mt-5 grid gap-3 md:grid-cols-3">
        {PATIENTS.map((p) => (
          <button key={p.id} data-testid={`patient-${p.id}`} onClick={() => pick(p.id)} aria-label={`选择就诊人 ${p.name}`}
            className="h-card flex items-center gap-4 p-5 text-left transition"
            style={selected === p.id ? { borderColor: 'var(--h-primary)', background: 'var(--h-soft)', boxShadow: '0 0 0 1px var(--h-primary)' } : {}}>
            <div className="grid h-12 w-12 flex-shrink-0 place-items-center rounded-full bg-soft"><User className="h-6 w-6 t-primary" /></div>
            <div className="flex-1">
              <div className="flex items-center gap-2"><span className="font-medium" style={{ fontSize: 17 }}>{p.name}</span>
                {p.isDefault && <span className="h-chip" style={{ background: '#F0FDF4', color: '#15803D' }}>默认</span>}</div>
              <div className="mt-1 text-sm" style={{ color: 'var(--h-sub)' }}>{p.relation} · 就诊卡 {p.cardNo}</div>
            </div>
            {selected === p.id && <CheckCircle2 className="h-5 w-5 t-primary" />}
          </button>
        ))}
      </div>
      <div className="mt-6 flex justify-between">
        <button onClick={() => navigate(to('/appointment/schedule'))} className="h-btn-ghost px-5 py-2.5"><ChevronLeft className="h-4 w-4" /> 上一步</button>
        <button data-testid="patient-next" onClick={() => { if (selected) { saveDraft({ ...getDraft(), patientId: selected }); navigate(to('/appointment/confirm')); } }}
          disabled={!selected} className="h-btn-primary px-8 py-2.5">下一步</button>
      </div>
    </div>
  );
}
