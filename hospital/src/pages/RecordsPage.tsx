import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FileText, Calendar, Clock, Wallet, User, X } from 'lucide-react';
import { listAppointments, cancelAppointment } from '../data';
import type { AppointmentStatus } from '../data';
import { Breadcrumb } from '../components';

const STATUS_LABEL: Record<string, string> = { pending: '待就诊', confirmed: '已确认', cancelled: '已取消', completed: '已完成' };
const STATUS_COLOR: Record<string, string> = { pending: '#D69B32', confirmed: '#218767', cancelled: '#94A3B8', completed: '#176A9B' };
const FILTERS: { key: AppointmentStatus | 'all'; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'confirmed', label: '待就诊' },
  { key: 'cancelled', label: '已取消' },
  { key: 'completed', label: '已完成' },
];

export function RecordsPage() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<AppointmentStatus | 'all'>('all');
  const [tick, setTick] = useState(0); // 刷新用
  const records = listAppointments();
  const filtered = filter === 'all' ? records : records.filter((r) => r.status === filter);

  function handleCancel(id: string) {
    const res = cancelAppointment(id);
    if (!res.ok) { alert(res.error); return; }
    setTick((t) => t + 1);
  }

  return (
    <div className="mx-auto px-6 py-6" style={{ maxWidth: 1280 }}>
      <Breadcrumb items={['我的预约']} />
      <div className="mt-4 flex items-center justify-between">
        <h1 className="font-semibold" style={{ fontSize: 22, color: '#183B56' }}>我的预约</h1>
        <button onClick={() => navigate('/appointment/departments')} className="h-btn-primary px-5 py-2">预约挂号</button>
      </div>

      {/* 筛选 */}
      <div className="mt-4 flex gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`rounded-lg px-4 py-1.5 text-sm font-medium transition ${filter === f.key ? 'text-white' : ''}`}
            style={filter === f.key ? { background: '#176A9B' } : { background: '#fff', border: '1px solid #E2E8F0', color: '#243746' }}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="mt-5" key={tick}>
        {filtered.length === 0 ? (
          <div className="h-card p-12 text-center" style={{ color: '#64748B' }}>
            <FileText className="mx-auto mb-3 w-12 h-12" style={{ color: '#CBD5E1' }} />
            <p>暂无预约记录</p>
            <button onClick={() => navigate('/appointment/departments')} className="h-btn-primary mt-4 px-5 py-2">去预约挂号</button>
          </div>
        ) : (
          <div className="space-y-3">
            {filtered.map((a) => (
              <div key={a.id} className="h-card p-5">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm" style={{ color: '#64748B' }}>{a.id}</span>
                    <span className="h-chip" style={{ background: `${STATUS_COLOR[a.status]}15`, color: STATUS_COLOR[a.status] }}>{STATUS_LABEL[a.status]}</span>
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
                {a.status === 'confirmed' && (
                  <div className="mt-3 border-t pt-3" style={{ borderColor: '#E2E8F0' }}>
                    <button onClick={() => handleCancel(a.id)} className="flex items-center gap-1 text-sm" style={{ color: '#CB4B4B' }}>
                      <X className="w-3.5 h-3.5" /> 取消预约
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Info({ icon: Icon, label, value }: { icon: typeof Calendar; label: string; value: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <Icon className="w-3.5 h-3.5 flex-shrink-0" style={{ color: '#94A3B8' }} />
      <span style={{ color: '#64748B' }}>{label}：</span>
      <span className="font-medium" style={{ color: '#183B56' }}>{value}</span>
    </div>
  );
}
