import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronLeft, User, CheckCircle2 } from 'lucide-react';
import { PATIENTS, getDraft, saveDraft } from '../data';
import { Breadcrumb, StepBar } from '../components';

export function PatientPage() {
  const navigate = useNavigate();
  const draft = getDraft();
  const [selectedPatient, setSelectedPatient] = useState<string>(draft.patientId || PATIENTS.find((p) => p.isDefault)?.id || '');

  function pickPatient(patientId: string) {
    setSelectedPatient(patientId);
    saveDraft({ ...getDraft(), patientId });
  }

  function next() {
    if (!selectedPatient) return;
    saveDraft({ ...getDraft(), patientId: selectedPatient });
    navigate('/appointment/confirm');
  }

  return (
    <div className="mx-auto px-6 py-6" style={{ maxWidth: 1280 }}>
      <Breadcrumb items={['预约挂号', '选择就诊人']} />
      <div className="mt-4"><StepBar step={3} /></div>

      <h1 className="mt-5 font-semibold" style={{ fontSize: 22, color: '#183B56' }}>选择就诊人</h1>
      <p className="mt-1 text-sm" style={{ color: '#64748B' }}>请选择本次就诊的患者</p>

      <div className="mt-5 space-y-3">
        {PATIENTS.map((p) => (
          <button
            key={p.id}
            onClick={() => pickPatient(p.id)}
            className={`h-card flex w-full items-center gap-4 p-5 text-left transition ${selectedPatient === p.id ? 'border-2' : ''}`}
            style={selectedPatient === p.id ? { borderColor: '#176A9B', background: '#EFF7FC' } : {}}
            aria-label={`选择就诊人 ${p.name}`}
          >
            <div className="grid flex-shrink-0 place-items-center rounded-full" style={{ width: 48, height: 48, background: '#EFF7FC' }}>
              <User className="w-6 h-6" style={{ color: '#176A9B' }} />
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className="font-medium" style={{ fontSize: 17, color: '#183B56' }}>{p.name}</span>
                {p.isDefault && <span className="h-chip" style={{ background: '#F0FDF4', color: '#218767' }}>默认就诊人</span>}
              </div>
              <div className="mt-1 text-sm" style={{ color: '#64748B' }}>{p.relation} · 就诊卡号：{p.cardNo}</div>
            </div>
            {selectedPatient === p.id && <CheckCircle2 className="w-5 h-5" style={{ color: '#176A9B' }} />}
          </button>
        ))}
      </div>

      <div className="mt-6 flex justify-between">
        <button onClick={() => navigate('/appointment/schedule')} className="h-btn-ghost px-5 py-2.5">
          <ChevronLeft className="w-4 h-4" /> 上一步
        </button>
        <button onClick={next} disabled={!selectedPatient} className="h-btn-primary px-8 py-2.5">
          下一步
        </button>
      </div>
    </div>
  );
}
