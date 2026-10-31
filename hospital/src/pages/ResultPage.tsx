import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { CheckCircle2, CreditCard, FileText, Home } from 'lucide-react';
import { getAppointmentById, fetchAppointment, HOSPITAL, to } from '../data';
import type { Appointment } from '../data';
import { Breadcrumb, StepBar } from '../components';

export function ResultPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [appt, setAppt] = useState<Appointment | undefined>(id ? getAppointmentById(id) : undefined);
  const [missing, setMissing] = useState(false);
  useEffect(() => { if (id) fetchAppointment(id).then(setAppt).catch(() => setMissing(true)); }, [id]);
  if (!appt) {
    return <div className="wrap py-16 text-center" style={{ color: 'var(--h-sub)' }}>{missing ? '未找到预约结果。' : '正在读取预约结果…'}</div>;
  }
  const paid = appt.pay_status === 'paid';
  return (
    <div className="wrap py-6" style={{ maxWidth: 900 }}>
      <Breadcrumb items={['首页', '预约挂号', '预约结果']} />
      <StepBar step={5} />
      <div className="mb-6 mt-8 text-center">
        <div className="mx-auto mb-4 grid h-20 w-20 place-items-center rounded-full" style={{ background: '#F0FDF4' }}><CheckCircle2 className="h-12 w-12" style={{ color: '#15803D' }} /></div>
        <h1 className="font-semibold" style={{ fontSize: 24 }} data-testid="result-title">{paid ? '预约成功 · 已支付' : '锁号成功 · 待支付'}</h1>
        <p className="mt-1 text-sm" style={{ color: 'var(--h-sub)' }}>{paid ? '请凭预约编号到院就诊' : '号源已保留 15 分钟，请在所属医院收银台完成模拟支付。'}</p>
      </div>
      <div className="h-card overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 text-white bg-primary">
          <div><div className="text-xs text-white/70">预约编号</div><div className="font-mono font-semibold tracking-wider" style={{ fontSize: 20 }} data-testid="appointment-id">{appt.id}</div></div>
          <div className="text-right text-sm">{HOSPITAL.name}<div className="text-xs text-white/70">{appt.campusName}</div></div>
        </div>
        <dl className="grid grid-cols-2 gap-x-8 gap-y-3 p-6 text-sm">
          {[['科室', appt.deptName], ['医生', `${appt.doctorName}（${appt.doctorTitle}）`], ['就诊日期', appt.date],
            ['就诊时间', `${appt.session === 'morning' ? '上午' : '下午'} ${appt.startTime}-${appt.endTime}`], ['就诊人', appt.patientName],
            ['挂号费', `¥${appt.fee}（${paid ? '已支付' : '待支付'}）`]].map(([k, v]) => (
            <div key={k} className="flex justify-between"><dt style={{ color: 'var(--h-sub)' }}>{k}</dt><dd className="font-medium">{v}</dd></div>
          ))}
        </dl>
      </div>
      <div className="mt-6 flex gap-3">
        {!paid && appt.pay_status !== 'expired' && appt.payToken && (
          <Link to={`/pay/${appt.id}?t=${appt.payToken}`} className="h-btn-primary flex-1 py-2.5"><CreditCard className="h-4 w-4" /> 去支付 ¥{appt.fee}</Link>
        )}
        <button onClick={() => navigate(to('/records'))} className="h-btn-ghost flex-1 py-2.5"><FileText className="h-4 w-4" /> 我的预约</button>
        <button onClick={() => navigate(to('/'))} className="h-btn-ghost flex-1 py-2.5"><Home className="h-4 w-4" /> 返回首页</button>
      </div>
    </div>
  );
}
