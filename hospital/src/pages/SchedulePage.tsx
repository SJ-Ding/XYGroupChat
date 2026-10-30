import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Calendar, Clock, Wallet, ChevronLeft, User } from 'lucide-react';
import { DEPARTMENTS, DOCTORS, SLOTS, CAMPUSES, getDraft, saveDraft, getNext7Days } from '../data';
import type { AppointmentSlot } from '../data';
import { Breadcrumb, StepBar } from '../components';

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
const CATEGORY_LABEL: Record<string, string> = { general: '普通门诊', expert: '专家门诊', special: '特需门诊' };
const STATUS_LABEL: Record<string, string> = { available: '可预约', full: '已约满', suspended: '停诊' };
const STATUS_COLOR: Record<string, string> = { available: '#218767', full: '#94A3B8', suspended: '#CB4B4B' };

export function SchedulePage() {
  const navigate = useNavigate();
  const draft = getDraft();
  const days = getNext7Days();
  const [selectedDate, setSelectedDate] = useState<string>(draft.date && days.includes(draft.date) ? draft.date : days[0]);
  const [selectedDoctor, setSelectedDoctor] = useState<string | null>(draft.doctorId || null);

  const dept = DEPARTMENTS.find((d) => d.id === draft.departmentId);
  const campus = CAMPUSES.find((c) => c.id === draft.campusId);

  // 当天有排班的医生
  const doctorsWithSlots = useMemo(() => {
    if (!draft.departmentId || !draft.campusId) return [];
    const doctorIds = new Set(
      SLOTS.filter((s) => s.departmentId === draft.departmentId && s.date === selectedDate && s.campusId === draft.campusId && s.status === 'available').map((s) => s.doctorId)
    );
    return DOCTORS.filter((d) => doctorIds.has(d.id));
  }, [draft.departmentId, draft.campusId, selectedDate]);

  // 当天该科室号源统计
  const daySlotCount = useMemo(() => {
    if (!draft.departmentId || !draft.campusId) return 0;
    return SLOTS.filter((s) => s.departmentId === draft.departmentId && s.date === selectedDate && s.campusId === draft.campusId && s.status === 'available').length;
  }, [draft.departmentId, draft.campusId, selectedDate]);

  function pickDate(date: string) {
    setSelectedDate(date);
    setSelectedDoctor(null);
    saveDraft({ ...getDraft(), date, doctorId: null, slotId: null });
  }

  function pickDoctor(doctorId: string) {
    setSelectedDoctor(doctorId);
    saveDraft({ ...getDraft(), doctorId });
  }

  function pickSlot(slot: AppointmentSlot) {
    if (slot.status !== 'available') return;
    saveDraft({ ...getDraft(), slotId: slot.id });
    navigate('/appointment/patient');
  }

  if (!dept || !campus) {
    return (
      <div className="mx-auto px-6 py-16 text-center" style={{ maxWidth: 1280, color: '#64748B' }}>
        <p>请先选择科室</p>
        <button onClick={() => navigate('/appointment/departments')} className="h-btn-primary mt-4 px-6 py-2.5">返回选择科室</button>
      </div>
    );
  }

  const selectedDoctorObj = selectedDoctor ? DOCTORS.find((d) => d.id === selectedDoctor) : null;
  const doctorSlots = selectedDoctor ? SLOTS.filter((s) => s.doctorId === selectedDoctor && s.date === selectedDate) : [];

  return (
    <div className="mx-auto px-6 py-6" style={{ maxWidth: 1280 }}>
      <Breadcrumb items={['预约挂号', campus.name, dept.name, '医生排班']} />
      <div className="mt-4"><StepBar step={2} /></div>

      {/* 科室信息 */}
      <div className="mt-5 h-card p-5">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-semibold" style={{ fontSize: 22, color: '#183B56' }}>{dept.name}</h1>
            <p className="mt-1 text-sm" style={{ color: '#64748B' }}>{dept.desc} · {campus.name}</p>
          </div>
          <div className="text-right text-sm" style={{ color: '#64748B' }}>
            <div>预约规则：可预约未来 7 天号源</div>
            <div className="mt-1">当日可预约号源：{daySlotCount} 个</div>
          </div>
        </div>
      </div>

      {/* 日期选择 */}
      <div className="mt-5">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium" style={{ color: '#183B56' }}>
          <Calendar className="w-4 h-4" style={{ color: '#176A9B' }} /> 选择预约日期
        </div>
        <div className="grid grid-cols-4 md:grid-cols-7 gap-2">
          {days.map((date) => {
            const d = new Date(date);
            const weekday = WEEKDAYS[d.getDay()];
            const monthDay = `${d.getMonth() + 1}/${d.getDate()}`;
            const count = SLOTS.filter((s) => s.departmentId === dept.id && s.date === date && s.campusId === campus.id && s.status === 'available').length;
            const isToday = date === days[0];
            return (
              <button
                key={date}
                onClick={() => pickDate(date)}
                className={`h-card p-3 text-center transition ${selectedDate === date ? 'border-2' : ''}`}
                style={selectedDate === date ? { borderColor: '#176A9B', background: '#EFF7FC' } : {}}
                aria-label={`选择${monthDay} ${weekday}`}
              >
                <div className="text-xs" style={{ color: '#64748B' }}>{isToday ? '今天' : weekday}</div>
                <div className="my-1 font-semibold" style={{ color: '#183B56' }}>{monthDay}</div>
                <div className="text-xs" style={{ color: count > 0 ? '#218767' : '#94A3B8' }}>
                  {count > 0 ? `${count}个号源` : '无号'}
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* 医生列表 */}
      <div className="mt-6">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium" style={{ color: '#183B56' }}>
          <User className="w-4 h-4" style={{ color: '#176A9B' }} /> 选择医生（{selectedDate}）
        </div>
        {doctorsWithSlots.length === 0 ? (
          <div className="h-card p-8 text-center" style={{ color: '#64748B' }}>
            <p>当日暂无可预约医生</p>
            <p className="mt-1 text-xs">请尝试选择其他日期</p>
          </div>
        ) : (
          <div className="space-y-3">
            {doctorsWithSlots.map((doc) => {
              const docAvailableSlots = SLOTS.filter((s) => s.doctorId === doc.id && s.date === selectedDate && s.status === 'available');
              const isExpanded = selectedDoctor === doc.id;
              return (
                <div key={doc.id} className={`h-card transition ${isExpanded ? 'shadow-md' : ''}`}>
                  <button
                    onClick={() => pickDoctor(doc.id)}
                    className="flex w-full items-center gap-4 p-4 text-left"
                  >
                    <div className="grid flex-shrink-0 place-items-center rounded-xl text-2xl" style={{ width: 56, height: 56, background: '#EFF7FC' }}>
                      {doc.avatar}
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-medium" style={{ fontSize: 17, color: '#183B56' }}>{doc.name}</span>
                        <span className="h-chip" style={{ background: '#EFF7FC', color: '#176A9B' }}>{doc.title}</span>
                        <span className="h-chip" style={{ background: '#F0FDF4', color: '#218767' }}>{CATEGORY_LABEL[docAvailableSlots[0]?.category || 'general']}</span>
                      </div>
                      <p className="mt-1 text-sm" style={{ color: '#64748B' }}>{doc.intro}</p>
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {doc.specialties.slice(0, 3).map((sp) => (
                          <span key={sp} className="h-chip" style={{ background: '#F1F5F9', color: '#64748B', fontSize: 10 }}>{sp}</span>
                        ))}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="flex items-center gap-1 font-semibold" style={{ color: '#176A9B' }}>
                        <Wallet className="w-4 h-4" /> {docAvailableSlots[0]?.price || '--'}元
                      </div>
                      <div className="mt-1 text-xs" style={{ color: docAvailableSlots.length > 0 ? '#218767' : '#94A3B8' }}>
                        {docAvailableSlots.length > 0 ? `${docAvailableSlots.length}个号源` : '已约满'}
                      </div>
                    </div>
                  </button>

                  {/* 展开号源 */}
                  {isExpanded && (
                    <div className="border-t px-4 pb-4 pt-3" style={{ borderColor: '#E2E8F0' }}>
                      <div className="mb-2 text-xs font-medium" style={{ color: '#64748B' }}>选择号源</div>
                      {doctorSlots.length === 0 ? (
                        <p className="py-3 text-sm" style={{ color: '#94A3B8' }}>该医生当日暂无可用号源</p>
                      ) : (
                        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
                          {doctorSlots.map((slot) => (
                            <button
                              key={slot.id}
                              onClick={() => pickSlot(slot)}
                              disabled={slot.status !== 'available'}
                              className="flex items-center justify-between rounded-lg border p-3 text-left transition disabled:cursor-not-allowed disabled:opacity-50"
                              style={slot.status === 'available' ? { borderColor: '#E2E8F0', background: '#fff' } : { borderColor: '#F1F5F9', background: '#F8FAFC' }}
                              aria-label={`${slot.session === 'morning' ? '上午' : '下午'} ${slot.startTime}-${slot.endTime} 挂号费${slot.price}元 ${STATUS_LABEL[slot.status]}`}
                            >
                              <div>
                                <div className="flex items-center gap-1.5 text-sm font-medium" style={{ color: '#183B56' }}>
                                  <span className="h-chip" style={{ background: slot.session === 'morning' ? '#FEF3C7' : '#E0E7FF', color: slot.session === 'morning' ? '#92400E' : '#3730A3' }}>
                                    {slot.session === 'morning' ? '上午' : '下午'}
                                  </span>
                                  <span className="flex items-center gap-1"><Clock className="w-3.5 h-3.5" style={{ color: '#94A3B8' }} /> {slot.startTime}-{slot.endTime}</span>
                                </div>
                                <div className="mt-1 text-xs" style={{ color: STATUS_COLOR[slot.status] }}>{STATUS_LABEL[slot.status]} · 剩余{slot.remaining}</div>
                              </div>
                              <div className="text-right">
                                <div className="font-semibold" style={{ color: '#176A9B' }}>¥{slot.price}</div>
                                <div className="text-[10px]" style={{ color: '#94A3B8' }}>{CATEGORY_LABEL[slot.category]}</div>
                              </div>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="mt-6 flex justify-between">
        <button onClick={() => navigate('/appointment/departments')} className="h-btn-ghost px-5 py-2.5">
          <ChevronLeft className="w-4 h-4" /> 上一步
        </button>
        {selectedDoctorObj && (
          <div className="text-sm" style={{ color: '#64748B' }}>
            已选择：{selectedDoctorObj.name} · 请选择号源
          </div>
        )}
      </div>
    </div>
  );
}
