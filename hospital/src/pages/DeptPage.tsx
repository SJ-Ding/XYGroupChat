import { useMemo, useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Search, ChevronRight, Building2 } from 'lucide-react';
import { DEPARTMENTS, CAMPUSES, HOSPITAL, getDraft, saveDraft, to } from '../data';
import type { Dept } from '../data';
import { Breadcrumb, StepBar } from '../components';

const CATEGORIES = ['全部科室', '内科系统', '外科系统', '妇产儿科', '五官科', '其他'];

export function DeptPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [selectedCategory, setSelectedCategory] = useState('全部科室');
  const [search, setSearch] = useState('');
  const campus = CAMPUSES[0];

  function pickDept(dept: Dept) {
    saveDraft({ ...getDraft(), campusId: campus.id, departmentId: dept.id, doctorId: null, slotId: null });
    navigate(to('/appointment/schedule'));
  }

  // 从 URL ?dept=xxx 预选科室，直接进入排班页
  useEffect(() => {
    const dept = DEPARTMENTS.find((d) => d.id === params.get('dept'));
    if (dept) pickDept(dept);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  const filtered = useMemo(() => {
    let list = DEPARTMENTS.filter((d) => d.campusIds.includes(campus.id));
    if (selectedCategory !== '全部科室') list = list.filter((d) => d.category === selectedCategory);
    if (search.trim()) list = list.filter((d) => d.name.includes(search) || d.diseases.some((dz) => dz.includes(search)) || d.desc.includes(search));
    return list;
  }, [selectedCategory, search, campus.id]);

  return (
    <div className="wrap py-6">
      <Breadcrumb items={['首页', '预约挂号', '选择科室']} />
      <StepBar step={1} />
      <div className="mt-6 flex items-center gap-3">
        <h1 className="h-title" style={{ fontSize: 20 }}>选择科室</h1>
        <span className="ml-auto flex items-center gap-1.5 text-sm" style={{ color: 'var(--h-sub)' }}>
          <Building2 className="h-4 w-4" />{HOSPITAL.name} · {campus.name}（{campus.address}）
        </span>
      </div>
      <div className="mt-4 flex gap-5">
        <aside className="h-card h-fit flex-shrink-0 overflow-hidden" style={{ width: 200 }}>
          <div className="bg-primary px-4 py-2.5 text-sm font-medium text-white">科室分类</div>
          {CATEGORIES.map((cat) => (
            <button key={cat} onClick={() => setSelectedCategory(cat)}
              className="block w-full border-b px-4 py-2.5 text-left text-sm transition"
              style={{ borderColor: 'var(--h-line)', ...(selectedCategory === cat ? { background: 'var(--h-soft)', color: 'var(--h-primary)', fontWeight: 600 } : {}) }}>
              {cat}
            </button>
          ))}
        </aside>
        <div className="flex-1">
          <div className="relative mb-4">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2" style={{ color: '#94A3B8' }} />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="搜索科室名称或症状，如 骨科、膝盖疼" className="h-input pl-10" aria-label="搜索科室" />
          </div>
          {filtered.length === 0 ? (
            <div className="h-card p-12 text-center" style={{ color: 'var(--h-sub)' }}>未找到匹配的科室，试试输入症状关键词</div>
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              {filtered.map((d) => (
                <button key={d.id} data-testid={`dept-${d.id}`} onClick={() => pickDept(d)}
                  className="h-card flex items-center gap-4 p-4 text-left transition hover:shadow-md">
                  <span className="grid h-10 w-10 flex-shrink-0 place-items-center rounded bg-soft text-sm font-semibold t-primary">{d.name.slice(0, 1)}</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2"><span className="font-medium" style={{ color: 'var(--h-deep)' }}>{d.name}</span>
                      <span className="h-chip bg-soft t-primary">{d.category}</span></div>
                    <div className="mt-1 truncate text-sm" style={{ color: 'var(--h-sub)' }}>{d.desc}</div>
                  </div>
                  <span className="flex items-center text-sm t-primary">挂号<ChevronRight className="h-4 w-4" /></span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
