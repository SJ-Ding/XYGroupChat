import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { CheckCircle2, Loader2, ChevronLeft, Info } from 'lucide-react';
import { DEPARTMENTS, DOCTORS, CAMPUSES, PATIENTS, appStorageKey, getDraft, saveDraft, submitAppointment, getSlotById } from '../data';
import { Breadcrumb, StepBar } from '../components';

const CATEGORY_LABEL: Record<string, string> = { general: '普通门诊', expert: '专家门诊', special: '特需门诊' };

export function ConfirmPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const draft = getDraft();

  // 兜底：从 query 参数恢复（Playwright 恢复时带 token 导航会丢失 state）
  const querySlotId = params.get('slotId') || draft.slotId || '';
  const queryDeptId = params.get('departmentId') || draft.departmentId || '';
  const queryDoctorId = params.get('doctorId') || draft.doctorId || '';
  const queryPatientId = params.get('patientId') || draft.patientId || PATIENTS.find((p) => p.isDefault)?.id || '';

  const slot = getSlotById(querySlotId);
  const dept = DEPARTMENTS.find((d) => d.id === (slot?.departmentId || queryDeptId));
  const doctor = DOCTORS.find((d) => d.id === (slot?.doctorId || queryDoctorId));
  const campus = CAMPUSES.find((c) => c.id === slot?.campusId);
  const patient = PATIENTS.find((p) => p.id === queryPatientId);

  const [accepted, setAccepted] = useState(draft.acceptedNotice);

  if (!slot || !dept || !doctor || !patient || !campus) {
    return (
      <div className="mx-auto px-6 py-16 text-center" style={{ maxWidth: 1280, color: '#64748B' }}>
        <p>预约信息不完整，请重新选择号源。</p>
        <button onClick={() => navigate('/appointment/departments')} className="h-btn-primary mt-4 px-6 py-2.5">返回预约挂号</button>
      </div>
    );
  }

  const taskId = params.get('task_id') || sessionStorage.getItem(appStorageKey('hospital_task_id')) || '';
  const token = params.get('token') || sessionStorage.getItem(appStorageKey('hospital_token')) || '';

  async function handleSubmit() {
    setError('');
    if (!accepted) { setError('请先阅读并同意预约须知'); return; }
    setSubmitting(true);
    await new Promise((r) => setTimeout(r, 400));

    // 后端统一校验号源、幂等，返回带支付凭证的预约
    const res = await submitAppointment({ slotId: slot!.id, patientId: patient!.id, taskId, token });
    setSubmitting(false);
    if (res.ok && res.appointment) {
      navigate(`/appointment/result/${res.appointment.id}`);
    } else {
      setError(res.error || '提交失败');
    }
  }

  return (
    <div className="mx-auto px-6 py-6" style={{ maxWidth: 1280 }}>
      <Breadcrumb items={['预约挂号', '确认预约']} />
      <div className="mt-4"><StepBar step={4} /></div>

      <h1 className="mt-5 font-semibold" style={{ fontSize: 22, color: '#183B56' }}>核对预约信息</h1>

      <div className="mt-5 grid gap-5 md:grid-cols-[1fr_320px]">
        {/* 左侧：预约详情 */}
        <div className="h-card p-6">
          <h2 className="mb-4 flex items-center gap-2 border-b pb-3 font-medium" style={{ borderColor: '#E2E8F0', color: '#183B56' }}>
            <Info className="w-4 h-4" style={{ color: '#176A9B' }} /> 就诊信息
          </h2>
          <dl className="grid grid-cols-2 gap-y-4 text-sm">
            <Row label="院区" value={campus.name} />
            <Row label="科室" value={dept.name} />
            <Row label="医生" value={`${doctor.name}（${doctor.title}）`} />
            <Row label="门诊类型" value={CATEGORY_LABEL[slot.category]} />
            <Row label="就诊日期" value={slot.date} />
            <Row label="就诊时间" value={`${slot.session === 'morning' ? '上午' : '下午'} ${slot.startTime}-${slot.endTime}`} />
            <Row label="就诊人" value={`${patient.name}（${patient.relation}）`} />
            <Row label="挂号费" value={`¥${slot.price}`} highlight />
          </dl>

          {error && (
            <div className="mt-4 rounded-xl p-4 text-sm" style={{ background: '#FEF2F2', border: '1px solid #FECACA', color: '#CB4B4B' }}>{error}</div>
          )}
        </div>

        {/* 右侧：费用与须知 */}
        <div className="space-y-4">
          <div className="h-card p-5">
            <h3 className="mb-3 font-medium" style={{ color: '#183B56' }}>费用摘要</h3>
            <div className="flex items-center justify-between border-b pb-3 text-sm" style={{ borderColor: '#E2E8F0' }}>
              <span style={{ color: '#64748B' }}>挂号费</span>
              <span className="font-semibold" style={{ color: '#176A9B' }}>¥{slot.price}</span>
            </div>
            <div className="mt-3 text-xs" style={{ color: '#64748B' }}>
              支付方式：锁号成功后 15 分钟内在线支付，超时自动释放号源
            </div>
          </div>

          <div className="h-card p-5">
            <h3 className="mb-3 font-medium" style={{ color: '#183B56' }}>预约须知</h3>
            <ul className="space-y-2 text-xs leading-relaxed" style={{ color: '#64748B' }}>
              <li>· 请按预约时间提前 15 分钟到院取号</li>
              <li>· 预约信息应与就诊人一致</li>
              <li>· 取消预约请在就诊前一日操作</li>
              <li>· 号源以最终提交结果为准</li>
              <li>· 同一时段每人限约一个号源</li>
            </ul>
          </div>

          <label className="flex items-start gap-2 text-sm" style={{ color: '#243746' }}>
            <input
              type="checkbox"
              checked={accepted}
              onChange={(e) => { setAccepted(e.target.checked); saveDraft({ ...getDraft(), acceptedNotice: e.target.checked }); }}
              className="mt-0.5"
              data-testid="agree"
              aria-label="同意预约须知"
            />
            <span>我已阅读并同意上述预约须知</span>
          </label>
        </div>
      </div>

      <div className="mt-6 flex justify-between">
        <button onClick={() => navigate('/appointment/patient')} className="h-btn-ghost px-5 py-2.5">
          <ChevronLeft className="w-4 h-4" /> 上一步
        </button>
        <button
          data-testid="submit-appointment"
          onClick={handleSubmit}
          disabled={submitting || !accepted}
          className="h-btn-primary px-8 py-2.5"
        >
          {submitting ? <Loader2 className="w-5 h-5 animate-spin" /> : <CheckCircle2 className="w-5 h-5" />}
          {submitting ? '提交中…' : '确认提交预约'}
        </button>
      </div>
    </div>
  );
}

function Row({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <dt style={{ color: '#64748B' }}>{label}</dt>
      <dd className="font-medium" style={highlight ? { color: '#176A9B', fontSize: 18 } : { color: '#183B56' }}>{value}</dd>
    </div>
  );
}
