import { Link } from 'react-router-dom';
import { Stethoscope, CalendarCheck, FileText, ClipboardList, ArrowRight, Clock, User, Info } from 'lucide-react';
import { DEPARTMENTS } from '../data';

const HOT_DEPT_IDS = ['d-guke', 'd-xinneike', 'd-shenjing', 'd-yanke', 'd-kouqiang', 'd-puwai', 'd-pifuke', 'd-huxi'];
const HOT_DEPTS = HOT_DEPT_IDS.map((id) => DEPARTMENTS.find((d) => d.id === id)!).filter(Boolean);

export function HomePage() {
  return (
    <div>
      {/* Banner */}
      <section className="relative overflow-hidden" style={{ background: 'linear-gradient(135deg, #176A9B 0%, #145A84 100%)' }}>
        <div className="mx-auto px-6" style={{ maxWidth: 1280, minHeight: 300 }}>
          <div className="flex flex-col justify-center py-12" style={{ minHeight: 300 }}>
            <h1 className="font-bold text-white" style={{ fontSize: 32 }}>市第一人民医院</h1>
            <p className="mt-2 text-white/80" style={{ fontSize: 18 }}>三级甲等综合医院 · 互联网预约服务平台</p>
            <p className="mt-4 text-white/60 text-sm leading-relaxed max-w-2xl">
              提供在线预约挂号、排班查询、就诊指南等服务。预约开放时间：每日 8:00-17:00，可预约未来 7 天号源。
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link to="/appointment/departments" className="h-btn-primary px-6 py-3 text-base">
                <Stethoscope className="w-5 h-5" /> 预约挂号
              </Link>
              <Link to="/guide" className="h-btn bg-white/15 text-white hover:bg-white/25 border border-white/30 px-6 py-3 text-base">
                就诊指南
              </Link>
            </div>
          </div>
        </div>
      </section>

      <div className="mx-auto px-6" style={{ maxWidth: 1280 }}>
        {/* 快捷服务 */}
        <section className="grid grid-cols-2 md:grid-cols-4 gap-4 -mt-8 relative z-10">
          {[
            { icon: Stethoscope, title: '预约挂号', desc: '选择科室医生', to: '/appointment/departments', color: '#176A9B' },
            { icon: CalendarCheck, title: '出诊排班', desc: '查看医生排班', to: '/appointment/departments', color: '#218767' },
            { icon: FileText, title: '我的预约', desc: '查看预约记录', to: '/records', color: '#D69B32' },
            { icon: ClipboardList, title: '就诊指南', desc: '了解就诊流程', to: '/guide', color: '#6B7280' },
          ].map((q) => (
            <Link key={q.title} to={q.to} className="h-card flex items-center gap-4 p-5 transition hover:shadow-md">
              <div className="grid place-items-center rounded-xl" style={{ width: 48, height: 48, background: `${q.color}15` }}>
                <q.icon className="w-6 h-6" style={{ color: q.color }} />
              </div>
              <div>
                <div className="font-medium" style={{ color: '#183B56' }}>{q.title}</div>
                <div className="text-xs" style={{ color: '#64748B' }}>{q.desc}</div>
              </div>
            </Link>
          ))}
        </section>

        {/* 热门科室 */}
        <section className="py-10">
          <div className="mb-5 flex items-center justify-between">
            <h2 className="font-semibold" style={{ fontSize: 20, color: '#183B56' }}>热门科室</h2>
            <Link to="/appointment/departments" className="flex items-center gap-1 text-sm hover:underline" style={{ color: '#176A9B' }}>
              查看全部科室 <ArrowRight className="w-4 h-4" />
            </Link>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {HOT_DEPTS.map((d) => (
              <Link key={d.id} to={`/appointment/departments?dept=${d.id}`} className="h-card p-4 transition hover:shadow-md hover:border-blue-300">
                <div className="font-medium" style={{ color: '#183B56' }}>{d.name}</div>
                <div className="mt-1 text-xs leading-relaxed" style={{ color: '#64748B' }}>{d.desc}</div>
                <div className="mt-2 flex items-center gap-1 text-xs" style={{ color: '#176A9B' }}>去预约 <ArrowRight className="w-3 h-3" /></div>
              </Link>
            ))}
          </div>
        </section>

        {/* 门诊公告与就诊须知 */}
        <section className="pb-10 grid md:grid-cols-2 gap-4">
          <div className="h-card p-5">
            <h2 className="mb-3 flex items-center gap-2 font-medium" style={{ color: '#183B56' }}>
              <Info className="w-4 h-4" style={{ color: '#176A9B' }} /> 门诊公告
            </h2>
            <ul className="space-y-2.5 text-sm" style={{ color: '#243746' }}>
              <li className="flex items-start gap-2"><span className="mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full" style={{ background: '#176A9B' }} /> 互联网预约服务平台已上线，支持在线预约挂号。</li>
              <li className="flex items-start gap-2"><span className="mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full" style={{ background: '#176A9B' }} /> 骨科张明远副主任医师本周一至周五上午坐诊。</li>
              <li className="flex items-start gap-2"><span className="mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full" style={{ background: '#176A9B' }} /> 10月31日内分泌科钱伟主任医师上午专家门诊。</li>
              <li className="flex items-start gap-2"><span className="mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full" style={{ background: '#D69B32' }} /> 心血管内科11月1日起增设东院区专家门诊。</li>
            </ul>
          </div>
          <div className="h-card p-5">
            <h2 className="mb-3 flex items-center gap-2 font-medium" style={{ color: '#183B56' }}>
              <ClipboardList className="w-4 h-4" style={{ color: '#176A9B' }} /> 就诊须知
            </h2>
            <ul className="space-y-2.5 text-sm" style={{ color: '#243746' }}>
              <li className="flex items-start gap-2"><Clock className="mt-0.5 w-4 h-4 flex-shrink-0" style={{ color: '#64748B' }} /> 预约开放时间：每日 8:00-17:00</li>
              <li className="flex items-start gap-2"><User className="mt-0.5 w-4 h-4 flex-shrink-0" style={{ color: '#64748B' }} /> 就诊须携带医保卡或身份证，信息须与就诊人一致</li>
              <li className="flex items-start gap-2"><Clock className="mt-0.5 w-4 h-4 flex-shrink-0" style={{ color: '#64748B' }} /> 请提前 15 分钟到院，凭预约编号在自助机取号</li>
              <li className="flex items-start gap-2"><Info className="mt-0.5 w-4 h-4 flex-shrink-0" style={{ color: '#64748B' }} /> 如需取消预约，请在就诊前一日操作，取消后号源释放</li>
            </ul>
          </div>
        </section>
      </div>
    </div>
  );
}
