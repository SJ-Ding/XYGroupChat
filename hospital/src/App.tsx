import { Link, NavLink, Route, Routes, useNavigate } from 'react-router-dom';
import { Home, Stethoscope, CalendarCheck, FileText, Clock, Bell } from 'lucide-react';
import { Breadcrumb, AgentBanner } from './components';
import { HomePage } from './pages/HomePage';
import { DeptPage } from './pages/DeptPage';
import { SchedulePage } from './pages/SchedulePage';
import { PatientPage } from './pages/PatientPage';
import { ConfirmPage } from './pages/ConfirmPage';
import { ResultPage } from './pages/ResultPage';
import { RecordsPage } from './pages/RecordsPage';
import { PayPage } from './pages/PayPage';

const nav = [
  { to: '/', label: '首页', icon: Home, end: true },
  { to: '/appointment/departments', label: '预约挂号', icon: Stethoscope, end: false },
  { to: '/records', label: '我的预约', icon: FileText, end: false },
  { to: '/guide', label: '就诊指南', icon: CalendarCheck, end: false },
];

export default function App() {
  return (
    <div className="min-h-screen flex flex-col" style={{ background: '#F6F8FB' }}>
      {/* 顶部导航 */}
      <header className="sticky top-0 z-30 shadow-sm" style={{ background: '#176A9B' }}>
        <div className="mx-auto flex items-center gap-6 px-6" style={{ maxWidth: 1280, height: 68 }}>
          <Link to="/" className="flex items-center gap-2.5 text-white">
            <div className="grid place-items-center rounded-lg" style={{ width: 36, height: 36, background: 'rgba(255,255,255,.15)' }}>
              <span className="text-lg font-bold text-white">+</span>
            </div>
            <div className="leading-tight">
              <div className="font-semibold text-white" style={{ fontSize: 16 }}>市第一人民医院</div>
              <div className="text-white/70" style={{ fontSize: 11 }}>互联网预约服务平台</div>
            </div>
          </Link>
          <nav className="hidden md:flex items-center gap-1 ml-4">
            {nav.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  `rounded-lg px-4 py-2 text-sm font-medium transition ${isActive ? 'bg-white/20 text-white' : 'text-white/80 hover:bg-white/10 hover:text-white'}`
                }
              >
                <span className="flex items-center gap-1.5"><n.icon className="w-4 h-4" /> {n.label}</span>
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-4 text-sm text-white/80">
            <span className="hidden sm:flex items-center gap-1"><Clock className="w-4 h-4" /> 8:00-17:00</span>
            <span className="flex items-center gap-1"><Bell className="w-4 h-4" /> 通知</span>
            <span className="flex items-center gap-1 text-white/90">王秀兰</span>
          </div>
        </div>
      </header>

      <AgentBanner />

      {/* 模拟平台提示条 */}
      <div className="text-center py-1.5 text-xs" style={{ background: '#FFF7E6', color: '#D69B32', borderBottom: '1px solid #F5E6C8' }}>
        模拟演示平台 · 所有医院、医生、患者及号源均为虚构数据，仅用于产品演示
      </div>

      <main className="flex-1">
        <Routes>
          <Route path="/" element={<HomePage />} />
          {/* 新流程路由 */}
          <Route path="/appointment/departments" element={<DeptPage />} />
          <Route path="/appointment/schedule" element={<SchedulePage />} />
          <Route path="/appointment/patient" element={<PatientPage />} />
          <Route path="/appointment/confirm" element={<ConfirmPage />} />
          <Route path="/appointment/result/:id" element={<ResultPage />} />
          {/* 兼容旧路由 → 重定向到新科室选择 */}
          <Route path="/appointment" element={<LegacyRedirect />} />
          <Route path="/confirm" element={<LegacyConfirmRedirect />} />
          <Route path="/result" element={<LegacyResultRedirect />} />
          <Route path="/records" element={<RecordsPage />} />
          <Route path="/pay/:id" element={<PayPage />} />
          <Route path="/guide" element={<GuidePage />} />
        </Routes>
      </main>

      {/* Footer */}
      <footer className="text-center py-6 text-xs" style={{ background: '#183B56', color: 'rgba(255,255,255,.4)' }}>
        市第一人民医院 · 互联网预约服务平台（模拟演示） · © 2026 · 预约热线 12333
      </footer>
    </div>
  );
}

function LegacyRedirect() {
  const navigate = useNavigate();
  navigate('/appointment/departments', { replace: true });
  return null;
}
function LegacyConfirmRedirect() {
  const navigate = useNavigate();
  navigate('/appointment/confirm', { replace: true });
  return null;
}
function LegacyResultRedirect() {
  const navigate = useNavigate();
  navigate('/records', { replace: true });
  return null;
}

function GuidePage() {
  return (
    <div className="mx-auto px-6 py-8" style={{ maxWidth: 1280 }}>
      <Breadcrumb items={['就诊指南']} />
      <h1 className="mb-6 font-semibold" style={{ fontSize: 24, color: '#183B56' }}>就诊指南</h1>
      <div className="space-y-4 rounded-xl bg-white p-6 shadow-sm" style={{ border: '1px solid #E2E8F0' }}>
        <h2 className="font-medium" style={{ color: '#183B56' }}>预约流程</h2>
        <ol className="space-y-3 text-sm leading-relaxed" style={{ color: '#243746' }}>
          <li><span className="font-medium text-blue-600">1.</span> 选择院区与科室</li>
          <li><span className="font-medium text-blue-600">2.</span> 选择预约日期</li>
          <li><span className="font-medium text-blue-600">3.</span> 查看医生排班，选择号源</li>
          <li><span className="font-medium text-blue-600">4.</span> 选择就诊人</li>
          <li><span className="font-medium text-blue-600">5.</span> 核对预约信息，阅读并同意预约须知</li>
          <li><span className="font-medium text-blue-600">6.</span> 提交预约，获取预约编号</li>
        </ol>
        <h2 className="pt-4 font-medium" style={{ color: '#183B56' }}>注意事项</h2>
        <ul className="space-y-2 text-sm leading-relaxed" style={{ color: '#243746' }}>
          <li>· 预约开放时间为每日 8:00-17:00，可预约未来 7 天号源。</li>
          <li>· 就诊请携带医保卡或身份证，提前 15 分钟到院取号。</li>
          <li>· 如需取消预约，请在就诊前一日通过"我的预约"页面操作。</li>
          <li>· 号源以最终提交结果为准，提交前状态可能变化。</li>
          <li>· 同一时段每人限约一个号源，请勿重复预约。</li>
        </ul>
      </div>
    </div>
  );
}
