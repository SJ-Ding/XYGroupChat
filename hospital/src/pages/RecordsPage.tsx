import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { FileText, Calendar, Clock, Wallet, User, X, ClipboardList } from 'lucide-react';
import { listAppointments, cancelAppointment, fetchEmr, HOSPITAL, to } from '../data';
import type { AppointmentStatus, Emr } from '../data';
import { Breadcrumb } from '../components';

const STATUS_LABEL: Record<string, string> = { pending: '待就诊', confirmed: '待就诊', cancelled: '已取消', completed: '已就诊' };
const STATUS_COLOR: Record<string, string> = { pending: '#A16207', confirmed: '#15803D', cancelled: '#94A3B8', completed: '#1D4ED8' };
const PAY_LABEL: Record<string, string> = { unpaid: '待支付', paid: '已支付', expired: '锁号超时' };
const FILTERS: { key: AppointmentStatus | 'all'; label: string }[] = [
  { key: 'all', label: '全部' }, { key: 'confirmed', label: '待就诊' }, { key: 'completed', label: '已就诊' }, { key: 'cancelled', label: '已取消' },
];

export function RecordsPage() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<AppointmentStatus | 'all'>('all');
  const [tick, setTick] = useState(0);
  const [emr, setEmr] = useState<Record<string, Emr | string>>({});
  const records = listAppointments().filter((a) => !a.hospitalId || a.hospitalId === HOSPITAL.id);
  const filtered = filter === 'all' ? records : records.filter((r) => r.status === filter);

  async function handleCancel(id: string) {
    const res = await cancelAppointment(id);
    if (!res.ok) { window.alert(res.error); return; }
    setTick((t) => t + 1);
  }
  async function toggleEmr(id: string) {
    if (emr[id]) { setEmr({ ...emr, [id]: '' }); return; }
    try { setEmr({ ...emr, [id]: await fetchEmr(id) }); } catch { setEmr({ ...emr, [id]: '暂无病历' }); }
  }

  return (
    <div className="wrap py-6">
      <Breadcrumb items={['首页', '我的预约']} />
      <div className="flex items-center justify-between">
        <h1 className="h-title" style={{ fontSize: 20 }}>我的预约 · {HOSPITAL.name}</h1>
        <button onClick={() => navigate(to('/appointment/departments'))} className="h-btn-primary px-5 py-2">预约挂号</button>
      </div>
      <div className="mt-4 flex gap-2">
        {FILTERS.map((f) => (
          <button key={f.key} onClick={() => setFilter(f.key)} className="rounded px-4 py-1.5 text-sm font-medium transition"
            style={filter === f.key ? { background: 'var(--h-primary)', color: '#fff' } : { background: '#fff', border: '1px solid var(--h-line)' }}>{f.label}</button>
        ))}
      </div>
      <div className="mt-5 space-y-3" key={tick}>
        {filtered.length === 0 ? (
          <div className="h-card p-12 text-center" style={{ color: 'var(--h-sub)' }}><FileText className="mx-auto mb-3 h-12 w-12" style={{ color: '#CBD5E1' }} />暂无预约记录</div>
        ) : filtered.map((a) => {
          const record = emr[a.id];
          return (
            <div key={a.id} className="h-card p-5">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm" style={{ color: 'var(--h-sub)' }}>{a.id}</span>
                  <span className="h-chip" style={{ background: `${STATUS_COLOR[a.status]}15`, color: STATUS_COLOR[a.status] }}>{STATUS_LABEL[a.status]}</span>
                  {a.status === 'confirmed' && a.pay_status && <span className="h-chip" style={{ background: '#FFF7E6', color: '#A16207' }}>{PAY_LABEL[a.pay_status]}</span>}
                </div>
                <span className="text-xs" style={{ color: '#94A3B8' }}>{new Date(a.createdAt).toLocaleString('zh-CN')}</span>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
                <Info icon={User} label="就诊人" value={a.patientName} />
                <Info icon={FileText} label="科室" value={a.deptName} />
                <Info icon={User} label="医生" value={`${a.doctorName}（${a.doctorTitle}）`} />
                <Info icon={Calendar} label="日期" value={a.date} />
                <Info icon={Clock} label="时间" value={`${a.session === 'morning' ? '上午' : '下午'} ${a.startTime}`} />
                <Info icon={Wallet} label="费用" value={`¥${a.fee}`} />
              </div>
              <div className="mt-3 flex gap-4 border-t pt-3 text-sm" style={{ borderColor: 'var(--h-line)' }}>
                {a.status === 'confirmed' && a.pay_status === 'unpaid' && a.payToken && (
                  <Link to={`/pay/${a.id}?t=${a.payToken}`} className="flex items-center gap-1 t-primary">去支付</Link>
                )}
                {a.status === 'confirmed' && <button onClick={() => handleCancel(a.id)} className="flex items-center gap-1" style={{ color: '#B91C1C' }}><X className="h-3.5 w-3.5" /> 取消预约</button>}
                {a.status === 'completed' && <button data-testid={`emr-${a.id}`} onClick={() => toggleEmr(a.id)} className="flex items-center gap-1 t-primary"><ClipboardList className="h-3.5 w-3.5" /> {record ? '收起病历' : '查看门诊病历'}</button>}
              </div>
              {record && typeof record !== 'string' && (
                <div className="mt-3 rounded p-4 text-sm leading-relaxed" style={{ background: '#F8FAFC' }} data-testid="emr">
                  {record.complaint && <div><b>主诉：</b>{record.complaint}</div>}
                  {record.exam && <div><b>查体：</b>{record.exam}</div>}
                  <div><b>诊断：</b>{record.diagnosis}</div>
                  {(record.medications || []).length > 0 && <div><b>处方：</b>{record.medications!.map((m) => `${m.name} ${m.dose || ''} ${m.frequency || ''}`).join('；')}</div>}
                  <div className="mt-1"><b>医嘱：</b></div>
                  <ol className="ml-5 list-decimal">{record.advice.map((x) => <li key={x}>{x}</li>)}</ol>
                  <div className="mt-2 text-xs" style={{ color: '#94A3B8' }}>{record.doctor}（{record.doctor_title}） · {record.visit_date} · {record.note}</div>
                </div>
              )}
              {typeof record === 'string' && record && <div className="mt-3 text-sm" style={{ color: '#94A3B8' }}>{record}</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Info({ icon: Icon, label, value }: { icon: typeof Calendar; label: string; value: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <Icon className="h-3.5 w-3.5 flex-shrink-0" style={{ color: '#94A3B8' }} />
      <span style={{ color: 'var(--h-sub)' }}>{label}：</span><span className="font-medium">{value}</span>
    </div>
  );
}
