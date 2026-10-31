import { Link, useParams } from 'react-router-dom';
import { MapPin, Clock, ChevronRight } from 'lucide-react';
import { DEPARTMENTS, DOCTORS, HOSPITAL, to } from '../data';
import { Breadcrumb } from '../components';

// 医院概况 / 就医指南 / 科室导航 / 专家介绍 / 新闻公告：系统只用到“预约挂号”，其余栏目为静态占位
const TITLES: Record<string, string> = { about: '医院概况', guide: '就医指南', departments: '科室导航', experts: '专家介绍', news: '新闻公告' };

export function InfoPage() {
  const { page = '' } = useParams();
  const title = TITLES[page] || '栏目';
  return (
    <div className="wrap py-6">
      <Breadcrumb items={['首页', title]} />
      <div className="grid gap-5 md:grid-cols-[200px_1fr]">
        <aside className="h-card h-fit overflow-hidden">
          <div className="bg-primary px-4 py-2.5 text-sm font-medium text-white">栏目导航</div>
          {Object.entries(TITLES).map(([k, v]) => (
            <Link key={k} to={to('/' + k)} className="flex items-center justify-between border-b px-4 py-2.5 text-sm"
              style={{ borderColor: 'var(--h-line)', ...(k === page ? { background: 'var(--h-soft)', color: 'var(--h-primary)', fontWeight: 600 } : {}) }}>{v}<ChevronRight className="h-3.5 w-3.5" /></Link>
          ))}
        </aside>
        <section className="h-card p-6">
          <h1 className="h-title" style={{ fontSize: 20 }}>{title}</h1>
          <div className="mt-4 text-sm leading-7" style={{ color: 'var(--h-ink)' }}>
            {page === 'about' && <>
              <p>{HOSPITAL.name}（{HOSPITAL.fullName}）为{HOSPITAL.level}综合医院。</p>
              <p className="mt-2 flex items-center gap-1"><MapPin className="h-4 w-4 t-primary" />地址：{HOSPITAL.address}</p>
              <p className="flex items-center gap-1"><Clock className="h-4 w-4 t-primary" />门诊时间：{HOSPITAL.openTime}</p>
              <p className="mt-2" style={{ color: 'var(--h-sub)' }}>以上名称、地址与门诊时间来自高德地图公开数据；本演示页面不包含医院真实介绍，请以医院官方渠道为准。</p>
            </>}
            {page === 'guide' && <ol className="list-decimal pl-5">
              <li>在“预约挂号”选择科室、日期、医生和号源</li><li>选择就诊人（实名）并核对预约信息</li><li>提交预约后锁号 15 分钟，下一步由本人在所属医院模拟收银台支付</li>
              <li>就诊当天提前 15 分钟到院，按预约时段候诊</li><li>需要取消时，请在就诊前一日通过“我的预约”操作</li>
            </ol>}
            {page === 'departments' && <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              {DEPARTMENTS.map((d) => <Link key={d.id} to={to(`/appointment/departments?dept=${d.id}`)} className="rounded border px-3 py-2 hover:shadow-sm" style={{ borderColor: 'var(--h-line)' }}>
                <b style={{ color: 'var(--h-deep)' }}>{d.name}</b><div className="truncate text-xs" style={{ color: '#94A3B8' }}>{d.desc}</div></Link>)}
            </div>}
            {page === 'experts' && <div className="grid gap-3 md:grid-cols-3">
              {DOCTORS.filter((d) => d.title !== '主治医师').map((d) => <div key={d.id} className="rounded border p-3" style={{ borderColor: 'var(--h-line)' }}>
                <b>{d.name}</b> <span className="text-xs t-primary">{d.title}</span>
                <div className="text-xs" style={{ color: 'var(--h-sub)' }}>{DEPARTMENTS.find((x) => x.id === d.deptId)?.name} · {d.intro}</div></div>)}
              <p className="col-span-full text-xs" style={{ color: '#94A3B8' }}>专家信息为虚构演示数据。</p>
            </div>}
            {page === 'news' && <p style={{ color: 'var(--h-sub)' }}>【演示】新闻公告为占位栏目，不展示医院真实信息。</p>}
            {!TITLES[page] && <p style={{ color: 'var(--h-sub)' }}>栏目建设中（演示页面）。</p>}
          </div>
        </section>
      </div>
    </div>
  );
}
