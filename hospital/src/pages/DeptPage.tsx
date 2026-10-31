import { useMemo, useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Search, ArrowRight, Building2 } from 'lucide-react';
import { DEPARTMENTS, CAMPUSES, getDraft, saveDraft } from '../data';
import type { Dept } from '../data';
import { Breadcrumb, StepBar } from '../components';

const CATEGORIES = ['全部科室', '内科系统', '外科系统', '妇产儿科', '五官科', '其他'];

export function DeptPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const layout = params.get('layout') === 'search' ? 'search' : 'grid';
  const [selectedCategory, setSelectedCategory] = useState('全部科室');
  const [search, setSearch] = useState('');
  const [selectedCampus, setSelectedCampus] = useState<string>(getDraft().campusId || CAMPUSES[0]?.id || '');

  // 从 URL ?dept=xxx 预选科室
  useEffect(() => {
    const deptId = params.get('dept');
    if (deptId) {
      const dept = DEPARTMENTS.find((d) => d.id === deptId);
      if (dept) {
        // 自动预选科室，直接进入排班页
        const campusId = dept.campusIds.includes(selectedCampus) ? selectedCampus : dept.campusIds[0];
        const draft = getDraft();
        saveDraft({ ...draft, campusId, departmentId: deptId });
        navigate('/appointment/schedule');
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  function pickDept(dept: Dept) {
    const campusId = dept.campusIds.includes(selectedCampus) ? selectedCampus : dept.campusIds[0];
    saveDraft({ ...getDraft(), campusId, departmentId: dept.id });
    navigate('/appointment/schedule');
  }

  function pickCampus(campusId: string) {
    setSelectedCampus(campusId);
    saveDraft({ ...getDraft(), campusId });
  }

  const filteredDepts = useMemo(() => {
    let list = DEPARTMENTS;
    if (selectedCategory !== '全部科室') list = list.filter((d) => d.category === selectedCategory);
    if (search.trim()) list = list.filter((d) => d.name.includes(search) || d.diseases.some((dz) => dz.includes(search)) || d.desc.includes(search));
    return list.filter((d) => d.campusIds.includes(selectedCampus));
  }, [selectedCategory, search, selectedCampus]);

  return (
    <div className="mx-auto px-6 py-6" style={{ maxWidth: 1280 }}>
      <Breadcrumb items={['预约挂号', '选择科室']} />

      {/* 步骤进度条 */}
      <StepBar step={1} />

      <div className="mt-6 flex items-center gap-3">
        <h1 className="font-semibold" style={{ fontSize: 22, color: '#183B56' }}>选择科室</h1>
        {/* 院区选择 */}
        <div className="ml-auto flex items-center gap-2">
          <Building2 className="w-4 h-4" style={{ color: '#64748B' }} />
          <span className="text-sm" style={{ color: '#64748B' }}>院区：</span>
          {CAMPUSES.map((c) => (
            <button
              key={c.id}
              data-testid={`campus-${c.id}`}
              onClick={() => pickCampus(c.id)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${selectedCampus === c.id ? 'text-white' : 'bg-white'}`}
              style={selectedCampus === c.id ? { background: '#176A9B' } : { border: '1px solid #E2E8F0', color: '#243746' }}
            >
              {c.name}
            </button>
          ))}
        </div>
      </div>

      {/* 布局 B：搜索模式 */}
      {layout === 'search' && (
        <div className="h-card mt-4 p-5">
          <div className="relative mb-4">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: '#94A3B8' }} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索科室名称或症状，如 骨科、膝盖疼"
              className="h-input pl-10"
              aria-label="搜索科室"
            />
          </div>
          <select
            value={selectedCategory === '全部科室' ? '' : selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value || '全部科室')}
            className="h-input"
            aria-label="科室分类"
          >
            <option value="">全部科室</option>
            {CATEGORIES.filter((c) => c !== '全部科室').map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
      )}

      {/* 主体：左右布局 */}
      <div className="mt-4 flex gap-5">
        {/* 左侧分类导航（布局 A） */}
        {layout === 'grid' && (
          <aside className="h-card h-fit p-3 flex-shrink-0" style={{ width: 240 }}>
            <div className="mb-2 px-2 text-xs font-medium" style={{ color: '#64748B' }}>科室分类</div>
            {CATEGORIES.map((cat) => (
              <button
                key={cat}
                onClick={() => setSelectedCategory(cat)}
                className={`mb-1 w-full rounded-lg px-3 py-2 text-left text-sm transition ${selectedCategory === cat ? 'font-medium text-white' : 'hover:bg-slate-50'}`}
                style={selectedCategory === cat ? { background: '#176A9B' } : { color: '#243746' }}
              >
                {cat}
              </button>
            ))}
          </aside>
        )}

        {/* 右侧科室列表 */}
        <div className="flex-1">
          {/* 布局 A 的搜索框 */}
          {layout === 'grid' && (
            <div className="relative mb-4">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: '#94A3B8' }} />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="搜索科室名称或症状"
                className="h-input pl-10"
                aria-label="搜索科室"
              />
            </div>
          )}

          {filteredDepts.length === 0 ? (
            <div className="h-card p-12 text-center" style={{ color: '#64748B' }}>
              <Search className="mx-auto mb-3 w-10 h-10" style={{ color: '#CBD5E1' }} />
              <p>未找到匹配的科室</p>
              <p className="mt-1 text-xs">尝试输入科室名称或症状关键词</p>
            </div>
          ) : (
            <div className="space-y-2">
              {filteredDepts.map((d) => (
                <button
                  key={d.id}
                  data-testid={`dept-${d.id}`}
                  onClick={() => pickDept(d)}
                  className="h-card flex w-full items-center gap-4 p-4 text-left transition hover:shadow-md hover:border-blue-300"
                >
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium" style={{ color: '#183B56' }}>{d.name}</span>
                      <span className="h-chip" style={{ background: '#EFF7FC', color: '#176A9B' }}>{d.category}</span>
                    </div>
                    <div className="mt-1 text-sm" style={{ color: '#64748B' }}>{d.desc}</div>
                  </div>
                  <div className="flex items-center gap-1 text-sm" style={{ color: '#176A9B' }}>
                    预约 <ArrowRight className="w-4 h-4" />
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
