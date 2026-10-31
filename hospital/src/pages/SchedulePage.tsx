import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Calendar, Clock, ChevronLeft, User } from 'lucide-react';
import { DEPARTMENTS, DOCTORS, SLOTS, CAMPUSES, HOSPITAL, getDraft, saveDraft, getNext7Days, to } from '../data';
import type { AppointmentSlot } from '../data';
import { Breadcrumb, StepBar } from '../components';

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
const CATEGORY_LABEL: Record<string, string> = { general: '普通门诊', expert: '专家门诊', special: '特需门诊' };
const STATUS_LABEL: Record<string, string> = { available: '可预约', full: '已约满', suspended: '停诊' };
const STATUS_COLOR: Record<string, string> = { available: '#15803D', full: '#94A3B8', suspended: '#B91C1C' };

export function SchedulePage() {
  const navigate = useNavigate();
  const draft = getDraft();
  const days = getNext7Days();
  const [selectedDate, setSelectedDate] = useState<string>(draft.date && days.includes(draft.date) ? draft.date : days[0]);
  const [selectedDoctor, setSelectedDoctor] = useState<string | null>(draft.doctorId || null);
  const dept = DEPARTMENTS.find((d) => d.id === draft.departmentId);
  const campus = CAMPUSES.find((c) => c.id === draft.campusId) || CAMPUSES[0];
  const deptSlots = useMemo(() => SLOTS.filter((s) => s.departmentId === draft.departmentId && s.campusId === campus.id), [draft.departmentId, campus.id]);
  const daySlots = deptSlots.filter((s) => s.date === selectedDate);
  const doctors = DOCTORS.filter((d) => d.deptId === draft.departmentId && daySlots.some((s) => s.doctorId === d.id));

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
    saveDraft({ ...getDraft(), slotId: slot.id, date: slot.date });
    navigate(to('/appointment/patient'));
  }

  if (!dept) {
    return (
      <div className="wrap py-16 text-center" style={{ color: 'var(--h-sub)' }}>
        <p>请先选择科室</p>
        <button onClick={() => navigate(to('/appointment/departments'))} className="h-btn-primary mt-4 px-6 py-2.5">返回选择科室</button>
      </div>
    );
  }

  return (
    <div className="wrap py-6">
      <Breadcrumb items={['首页', '预约挂号', dept.name, '医生排班']} />
      <StepBar step={2} />
      <div className="mt-5 h-card flex items-center justify-between p-5">
        <div>
          <h1 className="h-title" style={{ fontSize: 20 }}>{dept.name}</h1>
          <p className="mt-1 text-sm" style={{ color: 'var(--h-sub)' }}>{dept.desc} · {HOSPITAL.name}{campus.name}</p>
        </div>
        <div className="text-right text-sm" style={{ color: 'var(--h-sub)' }}>
          <div>可预约未来 7 天号源 · 实名就诊</div>
          <div className="mt-1">当日可约号源：<b className="t-primary">{daySlots.filter((s) => s.status === 'available').length}</b> 个</div>
        </div>
      </div>

      <div className="mt-5">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium" style={{ color: 'var(--h-deep)' }}><Calendar className="h-4 w-4 t-primary" /> 选择就诊日期</div>
        <div className="grid grid-cols-4 gap-2 md:grid-cols-7">
          {days.map((date, i) => {
            const d = new Date(date + 'T00:00:00');
            const count = deptSlots.filter((s) => s.date === date && s.status === 'available').length;
            const on = selectedDate === date;
            return (
              <button key={date} data-testid={`date-${date}`} onClick={() => pickDate(date)} aria-label={`选择${d.getMonth() + 1}/${d.getDate()} ${WEEKDAYS[d.getDay()]}`}
                className="h-card p-3 text-center transition" style={on ? { borderColor: 'var(--h-primary)', background: 'var(--h-soft)', boxShadow: '0 0 0 1px var(--h-primary)' } : {}}>
                <div className="text-xs" style={{ color: 'var(--h-sub)' }}>{i === 0 ? '今天' : WEEKDAYS[d.getDay()]}</div>
                <div className="my-1 font-semibold" style={{ color: 'var(--h-deep)' }}>{d.getMonth() + 1}/{d.getDate()}</div>
                <div className="text-xs" style={{ color: count > 0 ? '#15803D' : '#94A3B8' }}>{count > 0 ? `${count}个号源` : '无号'}</div>
              </button>
            );
          })}
        </div>
      </div>

      <div className="mt-6">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium" style={{ color: 'var(--h-deep)' }}><User className="h-4 w-4 t-primary" /> 出诊医生（{selectedDate}）</div>
        {doctors.length === 0 ? (
          <div className="h-card p-8 text-center" style={{ color: 'var(--h-sub)' }}>当日暂无出诊医生，请选择其他日期</div>
        ) : (
          <div className="space-y-3">
            {doctors.map((doc) => {
              const slots = daySlots.filter((s) => s.doctorId === doc.id);
              const avail = slots.filter((s) => s.status === 'available');
              const expanded = selectedDoctor === doc.id;
              return (
                <div key={doc.id} className="h-card" style={expanded ? { borderColor: 'var(--h-primary)' } : {}}>
                  <button data-testid={`doctor-${doc.id}`} onClick={() => pickDoctor(doc.id)} className="flex w-full items-center gap-4 p-4 text-left">
                    <div className="grid h-14 w-14 flex-shrink-0 place-items-center rounded-full text-2xl bg-soft">{doc.avatar}</div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-medium" style={{ fontSize: 17 }}>{doc.name}</span>
                        <span className="h-chip bg-soft t-primary">{doc.title}</span>
                        <span className="h-chip" style={{ background: '#F0FDF4', color: '#15803D' }}>{CATEGORY_LABEL[slots[0]?.category || 'general']}</span>
                      </div>
                      <p className="mt-1 text-sm" style={{ color: 'var(--h-sub)' }}>{doc.intro}</p>
                    </div>
                    <div className="text-right">
                      <div className="font-semibold t-primary">¥{slots[0]?.price ?? '--'}</div>
                      <div className="mt-1 text-xs" style={{ color: avail.length ? '#15803D' : '#94A3B8' }}>{avail.length ? `${avail.length}个号源` : '已约满'}</div>
                    </div>
                  </button>
                  {expanded && (
                    <div className="border-t px-4 pb-4 pt-3" style={{ borderColor: 'var(--h-line)' }}>
                      <div className="mb-2 text-xs font-medium" style={{ color: 'var(--h-sub)' }}>选择号源</div>
                      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
                        {slots.map((slot) => (
                          <button key={slot.id} data-testid={`slot-${slot.id}`} onClick={() => pickSlot(slot)} disabled={slot.status !== 'available'}
                            className="rounded border p-3 text-left transition disabled:cursor-not-allowed disabled:opacity-50"
                            style={{ borderColor: 'var(--h-line)', background: slot.status === 'available' ? '#fff' : '#F8FAFC' }}
                            aria-label={`${slot.session === 'morning' ? '上午' : '下午'} ${slot.startTime}-${slot.endTime} 挂号费${slot.price}元 ${STATUS_LABEL[slot.status]}`}>
                            <div className="flex items-center gap-1 text-sm font-medium"><Clock className="h-3.5 w-3.5" style={{ color: '#94A3B8' }} />{slot.session === 'morning' ? '上午' : '下午'} {slot.startTime}</div>
                            <div className="mt-1 flex items-center justify-between text-xs">
                              <span style={{ color: STATUS_COLOR[slot.status] }}>{STATUS_LABEL[slot.status]} · 余{slot.remaining}</span>
                              <span className="font-semibold t-primary">¥{slot.price}</span>
                            </div>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
      <div className="mt-6">
        <button onClick={() => navigate(to('/appointment/departments'))} className="h-btn-ghost px-5 py-2.5"><ChevronLeft className="h-4 w-4" /> 上一步</button>
      </div>
    </div>
  );
}
