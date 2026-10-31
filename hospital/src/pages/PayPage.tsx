import { useEffect, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { ShieldCheck, Loader2, CheckCircle2, Clock, Wallet, Users, CreditCard, Landmark } from 'lucide-react';
import { fetchAppointment, payAppointment } from '../data';
import type { Appointment } from '../data';

// 模拟收银台：仅演示用，不产生真实扣款。支付只能由本人在此页面点击完成，
// 成功后通知小艺（相当于支付回调 webhook），小艺再发凭证卡、写日历。
const METHODS = [
  { key: 'family', label: '家庭共享支付（演示）', desc: '子女为父母代付，家庭账户统一结算', icon: Users },
  { key: 'insurance', label: '医保个人账户（演示）', desc: '模拟医保个账扣费', icon: Landmark },
  { key: 'card', label: '银行卡（演示）', desc: '模拟储蓄卡快捷支付', icon: CreditCard },
];

export function PayPage() {
  const { id = '' } = useParams<{ id: string }>();
  const [params] = useSearchParams();
  const token = params.get('t') || '';
  const [appt, setAppt] = useState<Appointment | null>(null);
  const [method, setMethod] = useState('family');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [opened] = useState(Date.now());
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    fetchAppointment(id).then(setAppt).catch((e) => setError(e.message));
  }, [id]);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  async function pay() {
    setBusy(true);
    setError('');
    try {
      await new Promise((r) => setTimeout(r, 700));
      setAppt(await payAppointment(id, token, method));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!appt) {
    return <div className="mx-auto px-6 py-16 text-center" style={{ color: '#64748B' }}>{error || '正在加载订单…'}</div>;
  }
  const paid = appt.pay_status === 'paid';
  // 锁号倒计时：从打开收银台开始计 15 分钟（真实到期以后端演示时钟为准）
  const left = Math.max(0, 15 * 60 - Math.round((now - opened) / 1000));
  const mm = String(Math.floor(left / 60)).padStart(2, '0');
  const ss = String(left % 60).padStart(2, '0');

  return (
    <div className="mx-auto px-6 py-8" style={{ maxWidth: 720 }}>
      <div className="h-card overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 text-white" style={{ background: 'linear-gradient(90deg,#0F766E,#176A9B)' }}>
          <div>
            <div className="text-xs text-white/70">家人帮 · 模拟收银台</div>
            <div className="mt-0.5 font-semibold" style={{ fontSize: 18 }}>附近两家医院 · 挂号费</div>
          </div>
          <ShieldCheck className="h-8 w-8 text-white/70" />
        </div>

        {paid ? (
          <div className="p-10 text-center" data-testid="pay-success">
            <CheckCircle2 className="mx-auto h-16 w-16" style={{ color: '#218767' }} />
            <h1 className="mt-4 font-semibold" style={{ fontSize: 22, color: '#183B56' }}>支付成功</h1>
            <p className="mt-2 text-sm" style={{ color: '#64748B' }}>已通知小艺：挂号凭证和日历提醒会发到家庭群，可以关闭此页面。</p>
          </div>
        ) : (
          <div className="p-6">
            <div className="text-center">
              <div className="text-sm" style={{ color: '#64748B' }}>应付金额</div>
              <div className="mt-1 font-semibold" style={{ fontSize: 40, color: '#183B56' }}>¥{appt.fee.toFixed(2)}</div>
              <div className="mt-1 flex items-center justify-center gap-1 text-xs" style={{ color: '#D69B32' }}>
                <Clock className="h-3.5 w-3.5" /> 号源保留中，请在 {mm}:{ss} 内完成支付
              </div>
            </div>
            <dl className="mt-6 grid grid-cols-2 gap-y-3 rounded-xl p-4 text-sm" style={{ background: '#F8FAFC' }}>
              <dt style={{ color: '#64748B' }}>订单号</dt><dd className="text-right font-mono" style={{ color: '#183B56' }}>{appt.id}</dd>
              <dt style={{ color: '#64748B' }}>就诊人</dt><dd className="text-right" style={{ color: '#183B56' }}>{appt.patientName}</dd>
              <dt style={{ color: '#64748B' }}>科室 / 医生</dt><dd className="text-right" style={{ color: '#183B56' }}>{appt.deptName} · {appt.doctorName}</dd>
              <dt style={{ color: '#64748B' }}>就诊时间</dt><dd className="text-right" style={{ color: '#183B56' }}>{appt.date} {appt.startTime}</dd>
              <dt style={{ color: '#64748B' }}>院区</dt><dd className="text-right" style={{ color: '#183B56' }}>{appt.campusName}</dd>
            </dl>
            <div className="mt-5 space-y-2">
              {METHODS.map((m) => (
                <button key={m.key} onClick={() => setMethod(m.key)} data-testid={`pay-method-${m.key}`}
                  className="flex w-full items-center gap-3 rounded-xl border p-3 text-left transition"
                  style={method === m.key ? { borderColor: '#176A9B', background: '#EFF7FC' } : { borderColor: '#E2E8F0' }}>
                  <m.icon className="h-5 w-5" style={{ color: '#176A9B' }} />
                  <div className="flex-1">
                    <div className="text-sm font-medium" style={{ color: '#183B56' }}>{m.label}</div>
                    <div className="text-xs" style={{ color: '#64748B' }}>{m.desc}</div>
                  </div>
                  <span className="h-4 w-4 rounded-full border-2" style={{ borderColor: '#176A9B', background: method === m.key ? '#176A9B' : 'transparent' }} />
                </button>
              ))}
            </div>
            {error && <div className="mt-4 rounded-xl p-3 text-sm" style={{ background: '#FEF2F2', color: '#CB4B4B' }}>{error}</div>}
            <button data-testid="pay-confirm" onClick={pay} disabled={busy || appt.pay_status === 'expired' || !token}
              className="h-btn-primary mt-6 w-full py-3 text-base">
              {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <Wallet className="h-5 w-5" />}
              {busy ? '支付处理中…' : `确认支付 ¥${appt.fee}`}
            </button>
            <p className="mt-3 text-center text-xs" style={{ color: '#94A3B8' }}>模拟支付，不产生真实扣款 · 小艺没有代付能力，支付必须由本人确认</p>
          </div>
        )}
      </div>
    </div>
  );
}
