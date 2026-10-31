import { Link, NavLink, Route, Routes, useLocation } from 'react-router-dom';
import { Search, Phone, MapPin, Clock, ShieldAlert, Accessibility, Building2, ArrowRight } from 'lucide-react';
import { AgentBanner, Breadcrumb, Emblem } from './components';
import { ACTIVE_HOSPITAL, HOSPITAL, HOSPITALS, SITE_NOTE, to } from './data';
import { HomePage } from './pages/HomePage';
import { DeptPage } from './pages/DeptPage';
import { SchedulePage } from './pages/SchedulePage';
import { PatientPage } from './pages/PatientPage';
import { ConfirmPage } from './pages/ConfirmPage';
import { ResultPage } from './pages/ResultPage';
import { RecordsPage } from './pages/RecordsPage';
import { PayPage } from './pages/PayPage';
import { InfoPage } from './pages/InfoPage';

const NAV = [
  { path: '/', label: '首页', end: true },
  { path: '/about', label: '医院概况' },
  { path: '/guide', label: '就医指南' },
  { path: '/departments', label: '科室导航' },
  { path: '/experts', label: '专家介绍' },
  { path: '/appointment/departments', label: '预约挂号', testid: 'nav-appointment' },
  { path: '/news', label: '新闻公告' },
  { path: '/records', label: '我的预约' },
];

export default function App() {
  if (!ACTIVE_HOSPITAL) return <Portal />;
  return <SiteLayout />;
}

function SiteLayout() {
  const t = HOSPITAL.theme;
  const style = { '--h-primary': t.primary, '--h-deep': t.deep, '--h-accent': t.accent, '--h-soft': t.soft } as React.CSSProperties;
  return (
    <div className="min-h-screen flex flex-col" style={style}>
      <AgentBanner />
      {/* 顶部工具条 */}
      <div className="text-xs" style={{ background: '#F1F3F6', color: 'var(--h-sub)', borderBottom: '1px solid var(--h-line)' }}>
        <div className="wrap flex h-8 items-center gap-5">
          <span>欢迎访问{HOSPITAL.name}网站（演示页面）</span>
          <span className="ml-auto flex items-center gap-1"><Accessibility className="h-3.5 w-3.5" />无障碍</span>
          <span>长者模式</span>
          <a href="/hospital/" className="hover:underline">切换医院</a>
        </div>
      </div>
      {/* 院名与搜索 */}
      <header className="bg-white">
        <div className="wrap flex items-center gap-4 py-4">
          <Link to={to('/')} className="flex items-center gap-3" data-testid="site-home">
            <Emblem size={58} />
            <div className="leading-tight">
              <div className="font-bold tracking-wide" style={{ fontSize: 28, color: 'var(--h-deep)', fontFamily: '"Songti SC","STSong","SimSun",serif' }}>{HOSPITAL.name}</div>
              <div className="mt-1 text-sm" style={{ color: 'var(--h-sub)' }}>{HOSPITAL.fullName} · {HOSPITAL.level}综合医院</div>
            </div>
          </Link>
          <div className="ml-auto hidden md:flex items-center gap-6">
            <div className="text-right text-sm" style={{ color: 'var(--h-sub)' }}>
              <div className="flex items-center justify-end gap-1"><Phone className="h-4 w-4 t-primary" />咨询电话：以医院官方公布为准</div>
              <div className="mt-1 flex items-center justify-end gap-1"><Clock className="h-4 w-4 t-primary" />门诊：{HOSPITAL.openTime}</div>
            </div>
            <div className="relative">
              <input className="h-input w-56 pr-9 text-sm" placeholder="搜索科室、医生、疾病" aria-label="站内搜索" />
              <Search className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2" style={{ color: '#94A3B8' }} />
            </div>
          </div>
        </div>
        {/* 主导航 */}
        <nav className="bg-primary">
          <div className="wrap flex h-12 items-stretch">
            {NAV.map((n) => (
              <NavLink key={n.path} to={to(n.path)} end={n.end} data-testid={n.testid}
                className={({ isActive }) => `flex flex-1 items-center justify-center text-[15px] font-medium text-white transition ${isActive ? 'bg-black/20' : 'hover:bg-black/10'}`}>
                {n.label}
              </NavLink>
            ))}
          </div>
        </nav>
      </header>
      {/* 演示声明：每页固定显示 */}
      <div data-testid="demo-notice" className="text-center text-xs py-1.5" style={{ background: '#FFF7E6', color: '#A16207', borderBottom: '1px solid #F5E6C8' }}>
        <ShieldAlert className="mr-1 inline h-3.5 w-3.5" />
        演示用模拟页面，非{HOSPITAL.name}官方网站，不提供真实挂号 · {SITE_NOTE}
      </div>

      <main className="flex-1">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/appointment/departments" element={<DeptPage />} />
          <Route path="/appointment/schedule" element={<SchedulePage />} />
          <Route path="/appointment/patient" element={<PatientPage />} />
          <Route path="/appointment/confirm" element={<ConfirmPage />} />
          <Route path="/appointment/result/:id" element={<ResultPage />} />
          <Route path="/pay/:id" element={<PayPage />} />
          <Route path="/records" element={<RecordsPage />} />
          <Route path="/:page" element={<InfoPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>

      <footer style={{ background: 'var(--h-deep)', color: 'rgba(255,255,255,.75)' }}>
        <div className="wrap grid gap-6 py-8 text-sm md:grid-cols-[1.4fr_1fr_1fr]">
          <div>
            <div className="mb-2 flex items-center gap-2 text-base font-semibold text-white"><Building2 className="h-4 w-4" />{HOSPITAL.name}</div>
            <div className="flex items-start gap-1.5"><MapPin className="mt-0.5 h-4 w-4 flex-shrink-0" />地址：{HOSPITAL.address}（高德地图）</div>
            <div className="mt-1 flex items-start gap-1.5"><Clock className="mt-0.5 h-4 w-4 flex-shrink-0" />门诊时间：{HOSPITAL.openTime}</div>
            <div className="mt-1">来院路线：在高德地图搜索“{HOSPITAL.name}”</div>
          </div>
          <div>
            <div className="mb-2 font-semibold text-white">便民服务</div>
            <div className="grid grid-cols-2 gap-1">
              <Link to={to('/appointment/departments')} className="hover:text-white">预约挂号</Link>
              <Link to={to('/records')} className="hover:text-white">我的预约</Link>
              <Link to={to('/guide')} className="hover:text-white">就医指南</Link>
              <Link to={to('/departments')} className="hover:text-white">科室导航</Link>
            </div>
          </div>
          <div>
            <div className="mb-2 font-semibold text-white">声明</div>
            <p className="leading-relaxed text-xs">本页面为“家人帮”产品演示的模拟页面，与{HOSPITAL.name}无关，不提供真实挂号、支付或诊疗服务；医生、排班、号源、病历均为虚构。</p>
          </div>
        </div>
        <div className="py-3 text-center text-xs" style={{ background: 'rgba(0,0,0,.18)' }}>演示页面 · 非官方网站 · 仅用于产品演示</div>
      </footer>
    </div>
  );
}

function NotFound() {
  const loc = useLocation();
  return (
    <div className="wrap py-16 text-center" style={{ color: 'var(--h-sub)' }}>
      <Breadcrumb items={['页面不存在']} />
      <p>没有找到页面：{loc.pathname}</p>
      <Link to={to('/')} className="h-btn-primary mt-4 px-6 py-2.5">返回首页</Link>
    </div>
  );
}

/** 演示入口：两家医院的模拟网站 */
function Portal() {
  return (
    <div className="min-h-screen" style={{ background: '#F4F6F9' }}>
      <div className="wrap py-14">
        <h1 className="text-center font-semibold" style={{ fontSize: 26, color: '#1F2D3D' }}>家人帮 · 演示用医院页面</h1>
        <p className="mt-2 text-center text-sm" style={{ color: '#5F6B7A' }}>{SITE_NOTE} 页面仅用于产品演示，不提供真实挂号。</p>
        <div className="mx-auto mt-8 grid max-w-3xl gap-5 md:grid-cols-2">
          {HOSPITALS.map((h) => (
            <a key={h.id} href={`/hospital/apps/${h.id}/`} data-testid={`portal-${h.id}`} className="h-card block p-6 transition hover:shadow-md" style={{ borderTop: `4px solid ${h.theme.primary}` }}>
              <div className="text-lg font-semibold" style={{ color: h.theme.deep }}>{h.name}</div>
              <div className="mt-1 text-sm" style={{ color: '#5F6B7A' }}>{h.fullName} · {h.level}</div>
              <div className="mt-3 text-sm" style={{ color: '#5F6B7A' }}><MapPin className="mr-1 inline h-4 w-4" />{h.address}</div>
              <div className="mt-4 inline-flex items-center gap-1 text-sm font-medium" style={{ color: h.theme.primary }}>进入演示页面 <ArrowRight className="h-4 w-4" /></div>
            </a>
          ))}
        </div>
      </div>
    </div>
  );
}
