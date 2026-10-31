import { Link } from 'react-router-dom';
import { Stethoscope, CalendarCheck, FileText, ClipboardList, Users, Navigation, ChevronRight, Megaphone, Newspaper, Clock } from 'lucide-react';
import { DEPARTMENTS, DOCTORS, HOSPITAL, to } from '../data';

const HOT_DEPT_IDS = ['d-guke', 'd-xinneike', 'd-huxi', 'd-xiaohua', 'd-shenjing', 'd-neifenmi', 'd-yanke', 'd-kouqiang', 'd-pifuke', 'd-erbihou', 'd-jiyi', 'd-puwai'];
// 公告与新闻为演示占位，不代表医院真实信息
const NOTICES = ['【演示】门诊预约实行实名制，请携带身份证或医保卡就诊', '【演示】预约号源每日 07:30 起开放，可预约未来 7 天', '【演示】就诊请提前 15 分钟到院，按预约时段候诊', '【演示】取消预约请在就诊前一日完成'];
const NEWS = ['【演示】老年患者就医绿色通道服务说明', '【演示】慢病长处方与复诊预约指引', '【演示】膝关节健康科普：阴雨天关节酸痛怎么办', '【演示】高血压患者居家血压监测小贴士', '【演示】互联网医院复诊服务常见问题'];

export function HomePage() {
  const hot = HOT_DEPT_IDS.map((id) => DEPARTMENTS.find((d) => d.id === id)!).filter(Boolean);
  const experts = DOCTORS.filter((d) => d.title === '主任医师' || d.title === '副主任医师').slice(0, 4);
  const today = new Date();
  return (
    <div>
      {/* 横幅：自绘建筑插画（不使用医院真实照片） */}
      <section className="relative overflow-hidden" style={{ background: `linear-gradient(120deg, var(--h-deep), var(--h-primary))` }}>
        <svg className="absolute right-0 bottom-0 opacity-25" width="620" height="260" viewBox="0 0 620 260" aria-hidden="true">
          <rect x="60" y="80" width="140" height="180" fill="#fff" /><rect x="220" y="30" width="180" height="230" fill="#fff" /><rect x="420" y="110" width="150" height="150" fill="#fff" />
          {Array.from({ length: 6 }).map((_, r) => Array.from({ length: 5 }).map((__, c) => (
            <rect key={`${r}-${c}`} x={236 + c * 32} y={48 + r * 34} width="18" height="20" fill="var(--h-primary)" opacity=".5" />
          )))}
          <rect x="296" y="0" width="28" height="28" fill="#fff" /><rect x="303" y="6" width="14" height="16" fill="var(--h-accent)" />
        </svg>
        <div className="wrap relative py-14">
          <div className="text-sm tracking-[0.3em] text-white/70">{HOSPITAL.level} · 综合医院</div>
          <h1 className="mt-3 font-bold text-white" style={{ fontSize: 34, fontFamily: '"Songti SC","STSong","SimSun",serif' }}>{HOSPITAL.slogan}</h1>
          <p className="mt-3 max-w-xl text-sm leading-relaxed text-white/80">提供预约挂号、科室导航、专家出诊查询、就医指南等服务。预约号源可查询未来 7 天，请按预约时段到院就诊。</p>
          <div className="mt-6 flex gap-3">
            <Link to={to('/appointment/departments')} data-testid="hero-appointment" className="h-btn px-7 py-3 text-base text-white" style={{ background: 'var(--h-accent)' }}>
              <Stethoscope className="h-5 w-5" /> 预约挂号
            </Link>
            <Link to={to('/guide')} className="h-btn border border-white/50 px-7 py-3 text-base text-white hover:bg-white/10">就医指南</Link>
          </div>
        </div>
      </section>

      <div className="wrap">
        {/* 快捷入口 */}
        <section className="relative z-10 -mt-8 grid grid-cols-3 gap-3 md:grid-cols-6">
          {[
            { icon: Stethoscope, title: '预约挂号', path: '/appointment/departments' },
            { icon: ClipboardList, title: '科室导航', path: '/departments' },
            { icon: Users, title: '专家介绍', path: '/experts' },
            { icon: CalendarCheck, title: '就医指南', path: '/guide' },
            { icon: FileText, title: '我的预约', path: '/records' },
            { icon: Navigation, title: '来院路线', path: '/about' },
          ].map((q) => (
            <Link key={q.title} to={to(q.path)} className="h-card flex flex-col items-center gap-2 py-5 transition hover:-translate-y-0.5 hover:shadow-md">
              <span className="grid h-12 w-12 place-items-center rounded-full bg-soft"><q.icon className="h-6 w-6 t-primary" /></span>
              <span className="text-sm font-medium">{q.title}</span>
            </Link>
          ))}
        </section>

        <section className="mt-8 grid gap-5 md:grid-cols-[1.25fr_1fr]">
          <div className="h-card p-5">
            <div className="h-title"><Newspaper className="h-4 w-4" />新闻动态<Link to={to('/news')} className="h-more">更多 ›</Link></div>
            <ul className="mt-3 divide-y" style={{ borderColor: 'var(--h-line)' }}>
              {NEWS.map((n, i) => (
                <li key={n} className="flex items-center gap-3 py-2.5 text-sm">
                  <ChevronRight className="h-3.5 w-3.5 t-primary" /><span className="flex-1 truncate">{n}</span>
                  <span className="text-xs" style={{ color: '#94A3B8' }}>{`${today.getMonth() + 1}-${String(Math.max(1, today.getDate() - i * 3)).padStart(2, '0')}`}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="h-card p-5">
            <div className="h-title"><Megaphone className="h-4 w-4" />门诊公告</div>
            <div className="mt-3 rounded p-3 text-sm bg-soft"><Clock className="mr-1 inline h-4 w-4 t-primary" />门诊时间：{HOSPITAL.openTime}</div>
            <ul className="mt-2 space-y-2 text-sm" style={{ color: 'var(--h-sub)' }}>
              {NOTICES.map((n) => <li key={n} className="flex gap-2"><span className="t-primary">•</span>{n}</li>)}
            </ul>
          </div>
        </section>

        <section className="mt-6 h-card p-5">
          <div className="h-title"><ClipboardList className="h-4 w-4" />科室导航<Link to={to('/departments')} className="h-more">全部科室 ›</Link></div>
          <div className="mt-4 grid grid-cols-3 gap-3 md:grid-cols-6">
            {hot.map((d) => (
              <Link key={d.id} to={to(`/appointment/departments?dept=${d.id}`)} className="rounded border px-3 py-3 text-center text-sm transition hover:shadow-sm" style={{ borderColor: 'var(--h-line)' }}>
                <div className="font-medium" style={{ color: 'var(--h-deep)' }}>{d.name}</div>
                <div className="mt-1 truncate text-xs" style={{ color: '#94A3B8' }}>{d.diseases.slice(0, 2).join(' · ')}</div>
              </Link>
            ))}
          </div>
        </section>

        <section className="mt-6 mb-10 h-card p-5">
          <div className="h-title"><Users className="h-4 w-4" />专家风采<Link to={to('/experts')} className="h-more">更多专家 ›</Link></div>
          <div className="mt-4 grid gap-4 md:grid-cols-4">
            {experts.map((d) => (
              <div key={d.id} className="rounded border p-4" style={{ borderColor: 'var(--h-line)' }}>
                <div className="flex items-center gap-3">
                  <span className="grid h-12 w-12 place-items-center rounded-full text-2xl bg-soft">{d.avatar}</span>
                  <div><div className="font-medium">{d.name}</div><div className="text-xs t-primary">{d.title}</div></div>
                </div>
                <div className="mt-2 text-xs" style={{ color: 'var(--h-sub)' }}>{DEPARTMENTS.find((x) => x.id === d.deptId)?.name} · {d.specialties.slice(0, 2).join('、')}</div>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs" style={{ color: '#94A3B8' }}>专家信息为虚构演示数据。</p>
        </section>
      </div>
    </div>
  );
}
