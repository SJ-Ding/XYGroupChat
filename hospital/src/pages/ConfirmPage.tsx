import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle2, Loader2, ChevronLeft, Info, Wallet } from 'lucide-react';
import { DEPARTMENTS, DOCTORS, CAMPUSES, PATIENTS, HOSPITAL, getDraft, saveDraft, submitAppointment, getSlotById, to } from '../data';
import { Breadcrumb, StepBar } from '../components';

const CATEGORY_LABEL: Record<string, string> = { general: '普通门诊', expert: '专家门诊', special: '特需门诊' };

export function ConfirmPage() {
  const navigate = useNavigate();
  const draft = getDraft();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [accepted, setAccepted] = useState(draft.acceptedNotice);
  const slot = getSlotById(draft.slotId || '');
  const dept = DEPARTMENTS.find((d) => d.id === (slot?.departmentId || draft.departmentId));
  const doctor = DOCTORS.find((d) => d.id === (slot?.doctorId || draft.doctorId));
  const campus = CAMPUSES.find((c) => c.id === slot?.campusId);
  const patient = PATIENTS.find((p) => p.id === (draft.patientId || PATIENTS.find((x) => x.isDefault)?.id));

  if (!slot || !dept || !doctor || !patient || !campus) {
    return (
      <div className="wrap py-16 text-center" style={{ color: 'var(--h-sub)' }}>
        <p>预约信息不完整，请重新选择号源。</p>
        <button onClick={() => navigate(to('/appointment/departments'))} className="h-btn-primary mt-4 px-6 py-2.5">返回预约挂号</button>
      </div>
    );
  }

  async function handleSubmit() {
    setError('');
    if (!accepted) { setError('请先阅读并同意预约须知'); return; }
    setSubmitting(true);
    const taskId = sessionStorage.getItem('hospital_task_id') || '';
    const res = await submitAppointment({ slotId: slot!.id, patientId: patient!.id, taskId });
    setSubmitting(false);
    if (res.ok && res.appointment) navigate(to(`/appointment/result/${res.appointment.id}`));
    else setError(res.error || '提交失败');
  }

  return (
    <div className="wrap py-6">
      <Breadcrumb items={['首页', '预约挂号', '核对信息']} />
      <StepBar step={4} />
      <h1 className="h-title mt-6" style={{ fontSize: 20 }}>核对预约信息</h1>
      <div className="mt-5 grid gap-5 md:grid-cols-[1fr_320px]">
        <div className="h-card p-6">
          <h2 className="mb-4 flex items-center gap-2 border-b pb-3 font-medium" style={{ borderColor: 'var(--h-line)', color: 'var(--h-deep)' }}><Info className="h-4 w-4 t-primary" /> 就诊信息</h2>
          <dl className="grid grid-cols-2 gap-x-8 gap-y-4 text-sm">
            <Row label="医院" value={HOSPITAL.name} />
            <Row label="院区" value={campus.name} />
            <Row label="科室" value={dept.name} />
            <Row label="医生" value={`${doctor.name}（${doctor.title}）`} />
            <Row label="门诊类型" value={CATEGORY_LABEL[slot.category]} />
            <Row label="就诊日期" value={slot.date} />
            <Row label="就诊时间" value={`${slot.session === 'morning' ? '上午' : '下午'} ${slot.startTime}-${slot.endTime}`} />
            <Row label="就诊人" value={`${patient.name}（${patient.relation}）`} />
            <Row label="挂号费" value={`¥${slot.price}`} highlight />
          </dl>
          {error && <div data-testid="submit-error" className="mt-4 rounded p-4 text-sm" style={{ background: '#FEF2F2', border: '1px solid #FECACA', color: '#B91C1C' }}>{error}</div>}
        </div>
        <div className="space-y-4">
          <div className="h-card p-5">
            <h3 className="mb-3 flex items-center gap-2 font-medium" style={{ color: 'var(--h-deep)' }}><Wallet className="h-4 w-4 t-primary" />费用与支付</h3>
            <div className="flex items-center justify-between border-b pb-3 text-sm" style={{ borderColor: 'var(--h-line)' }}>
              <span style={{ color: 'var(--h-sub)' }}>挂号费</span><span className="font-semibold t-primary">¥{slot.price}</span>
            </div>
            <div className="mt-3 text-xs leading-relaxed" style={{ color: 'var(--h-sub)' }}>提交后为您锁号 15 分钟，下一步请在所属医院模拟收银台由本人确认支付。</div>
          </div>
          <div className="h-card p-5">
            <h3 className="mb-3 font-medium" style={{ color: 'var(--h-deep)' }}>预约须知</h3>
            <ul className="space-y-2 text-xs leading-relaxed" style={{ color: 'var(--h-sub)' }}>
              <li>· 实行实名制预约，就诊人信息须与证件一致</li>
              <li>· 请按预约时段提前 15 分钟到院</li>
              <li>· 取消预约请在就诊前一日操作</li>
              <li>· 同一时段每人限约一个号源</li>
            </ul>
          </div>
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" checked={accepted} data-testid="agree" aria-label="同意预约须知" className="mt-0.5"
              onChange={(e) => { setAccepted(e.target.checked); saveDraft({ ...getDraft(), acceptedNotice: e.target.checked }); }} />
            <span>我已阅读并同意上述预约须知</span>
          </label>
        </div>
      </div>
      <div className="mt-6 flex justify-between">
        <button onClick={() => navigate(to('/appointment/patient'))} className="h-btn-ghost px-5 py-2.5"><ChevronLeft className="h-4 w-4" /> 上一步</button>
        <button data-testid="submit-appointment" onClick={handleSubmit} disabled={submitting || !accepted} className="h-btn-primary px-8 py-2.5">
          {submitting ? <Loader2 className="h-5 w-5 animate-spin" /> : <CheckCircle2 className="h-5 w-5" />}{submitting ? '提交中…' : '确认提交预约'}
        </button>
      </div>
    </div>
  );
}

function Row({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <dt style={{ color: 'var(--h-sub)' }}>{label}</dt>
      <dd className="font-medium" style={highlight ? { color: 'var(--h-primary)', fontSize: 18 } : {}}>{value}</dd>
    </div>
  );
}
