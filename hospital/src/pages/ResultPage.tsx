import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { CheckCircle2, FileText, Home, Calendar, Clock, Wallet, User, Building2, Stethoscope, CreditCard } from 'lucide-react';
import { getAppointmentById, fetchAppointment } from '../data';
import type { Appointment } from '../data';
import { Breadcrumb } from '../components';

const CATEGORY_LABEL: Record<string, string> = { general: '普通门诊', expert: '专家门诊', special: '特需门诊' };
const PAY_LABEL: Record<string, string> = { unpaid: '待支付', paid: '已支付', expired: '已超时' };

export function ResultPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [appt, setAppt] = useState<Appointment | undefined>(id ? getAppointmentById(id) : undefined);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    if (!id) return;
    fetchAppointment(id).then(setAppt).catch(() => setMissing(true));
  }, [id]);

  if (!appt) {
    return (
      <div className="mx-auto px-6 py-16 text-center" style={{ maxWidth: 1280, color: '#64748B' }}>
        <p>{missing ? '未找到预约结果。' : '正在读取预约结果…'}</p>
        <button onClick={() => navigate('/')} className="h-btn-primary mt-4 px-6 py-2.5">返回首页</button>
      </div>
    );
  }
  const paid = appt.pay_status === 'paid';

  return (
    <div className="mx-auto px-6 py-6" style={{ maxWidth: 896 }}>
      <Breadcrumb items={['预约挂号', '预约结果']} />

      <div className="mb-8 mt-6 text-center">
        <div className="mx-auto mb-4 grid place-items-center rounded-full" style={{ width: 80, height: 80, background: '#F0FDF4' }}>
          <CheckCircle2 className="w-12 h-12" style={{ color: '#218767' }} />
        </div>
        <h1 className="font-semibold" style={{ fontSize: 24, color: '#183B56' }} data-testid="result-title">{paid ? '预约成功 · 已支付' : '锁号成功 · 待支付'}</h1>
        <p className="mt-1 text-sm" style={{ color: '#64748B' }}>
          {paid ? '请凭预约编号到院取号就诊' : '号源已为您保留 15 分钟，请尽快完成支付，超时将自动释放'}
        </p>
      </div>

      {/* 电子预约凭证 */}
      <div className="h-card overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 text-white" style={{ background: 'linear-gradient(90deg, #176A9B, #145A84)' }}>
          <div>
            <div className="text-xs text-white/70">预约编号</div>
            <div className="font-mono font-semibold tracking-wider" style={{ fontSize: 20 }} data-testid="appointment-id">{appt.id}</div>
          </div>
          <Stethoscope className="w-8 h-8 text-white/60" />
        </div>
        <div className="space-y-3 p-6">
          <Item icon={Building2} label="就诊院区" value={appt.campusName} />
          <Item icon={Stethoscope} label="科室" value={appt.deptName} />
          <Item icon={User} label="医生" value={`${appt.doctorName}（${appt.doctorTitle}）`} />
          <Item icon={Calendar} label="就诊日期" value={appt.date} />
          <Item icon={Clock} label="就诊时间" value={`${appt.session === 'morning' ? '上午' : '下午'} ${appt.startTime}-${appt.endTime}`} />
          <Item icon={User} label="就诊人" value={appt.patientName} />
          <Item icon={Wallet} label="挂号费" value={`¥${appt.fee}（${PAY_LABEL[appt.pay_status || 'unpaid']}）`} highlight />
          <Item icon={FileText} label="门诊类型" value={CATEGORY_LABEL[appt.category] || '普通门诊'} />
        </div>
        <div className="px-6 py-3 text-center text-xs" style={{ background: '#F8FAFC', color: '#64748B', borderTop: '1px solid #E2E8F0' }}>
          请提前 15 分钟到院，凭此编号在自助机取号 · 支付状态：{PAY_LABEL[appt.pay_status || 'unpaid']}
        </div>
      </div>

      <div className="mt-6 flex gap-3">
        {!paid && appt.pay_status !== 'expired' && appt.payToken && (
          <Link to={`/pay/${appt.id}?t=${appt.payToken}`} className="h-btn-primary flex-1 py-2.5">
            <CreditCard className="w-4 h-4" /> 去支付 ¥{appt.fee}
          </Link>
        )}
        <button onClick={() => navigate('/records')} className="h-btn-ghost flex-1 py-2.5">
          <FileText className="w-4 h-4" /> 查看预约记录
        </button>
        <button onClick={() => navigate('/')} className="h-btn-ghost flex-1 py-2.5">
          <Home className="w-4 h-4" /> 返回首页
        </button>
      </div>
    </div>
  );
}

function Item({ icon: Icon, label, value, highlight }: { icon: typeof Calendar; label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <div className="grid flex-shrink-0 place-items-center rounded-lg" style={{ width: 36, height: 36, background: '#EFF7FC' }}>
        <Icon className="w-4 h-4" style={{ color: '#176A9B' }} />
      </div>
      <div className="flex flex-1 items-center justify-between">
        <span className="text-sm" style={{ color: '#64748B' }}>{label}</span>
        <span className="font-medium" style={highlight ? { color: '#176A9B' } : { color: '#183B56' }}>{value}</span>
      </div>
    </div>
  );
}
