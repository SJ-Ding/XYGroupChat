// ============================================================
// 模拟医院数据模型 —— 演示用
// 医院名称、地址来自高德地图公开数据；科室排班、医生、号源、病历均为虚构。
// 医院/院区/科室/医生/就诊人来自 catalog.json（与小艺后端共用一份）；
// 号源、预约、病历由后端 /api/hospital 统一提供，保证刷新不变、预约真实扣减。
// ============================================================
import catalog from './catalog.json';

// ---------------- 基础模型 ----------------
export interface Hospital {
  id: string;
  name: string;
  short: string;
  fullName: string;
  aliases: string[];
  address: string;
  lng: number;
  lat: number;
  level: string;
  openTime: string;
  slogan: string;
  theme: { primary: string; deep: string; accent: string; soft: string };
}

export interface Campus {
  id: string;
  hospitalId: string;
  name: string;
  address: string;
  lng?: number;
  lat?: number;
  level?: string;
}

export interface Dept {
  id: string;
  name: string;
  desc: string;
  category: string;
  diseases: string[];
  campusIds: string[]; // 该科室在哪些院区有
}

export interface Doctor {
  id: string;
  name: string;
  title: string; // 主任医师/副主任医师/主治医师
  deptId: string;
  campusId: string;
  avatar: string;
  intro: string;
  specialties: string[];
}

export type SlotStatus = 'available' | 'full' | 'suspended';
export type SlotSession = 'morning' | 'afternoon';
export type SlotCategory = 'general' | 'expert' | 'special';

export interface AppointmentSlot {
  id: string;
  doctorId: string;
  departmentId: string;
  campusId: string;
  date: string; // YYYY-MM-DD
  startTime: string; // HH:MM
  endTime: string;
  session: SlotSession;
  category: SlotCategory;
  price: number;
  capacity: number;
  remaining: number;
  status: SlotStatus;
}

export interface Patient {
  id: string;
  name: string;
  relation: string; // 与当前账号关系
  cardNo: string; // 就诊卡号（脱敏）
  isDefault: boolean;
}

export type AppointmentStatus = 'pending' | 'confirmed' | 'cancelled' | 'completed';
export type PayStatus = 'unpaid' | 'paid' | 'expired';

export interface Emr {
  hospital: string;
  campus: string;
  department: string;
  doctor: string;
  doctor_title: string;
  patient: string;
  visit_date: string;
  complaint: string;
  diagnosis: string;
  exam: string;
  advice: string[];
  medications?: { name: string; dose?: string; frequency?: string; days?: string | number }[];
  note: string;
}

export interface Appointment {
  id: string;
  slotId?: string;
  hospitalId?: string;
  hospitalName?: string;
  campusName: string;
  deptName: string;
  doctorName: string;
  doctorTitle: string;
  date: string;
  session: SlotSession;
  startTime: string;
  endTime: string;
  category: SlotCategory;
  fee: number;
  patientName: string;
  patientId: string;
  taskId?: string | null;
  createdAt: number;
  status: AppointmentStatus;
  pay_status?: PayStatus;
  lock_expires?: number;
  paid_at?: number | null;
  payToken?: string;
  emr?: Emr | null;
}

// ---------------- 预约草稿（LocalStorage 持久化）----------------
export interface AppointmentDraft {
  campusId: string | null;
  departmentId: string | null;
  date: string | null;
  doctorId: string | null;
  slotId: string | null;
  patientId: string | null;
  acceptedNotice: boolean;
}

// 草稿按医院站点分开存，避免两家医院互相串号
const draftKey = () => 'hospital-appointment-draft-' + (window.location.pathname.match(/^\/hospital\/apps\/([^/]+)/)?.[1] || 'portal');

export function getDraft(): AppointmentDraft {
  try {
    const raw = localStorage.getItem(draftKey());
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return { campusId: null, departmentId: null, date: null, doctorId: null, slotId: null, patientId: null, acceptedNotice: false };
}

export function saveDraft(draft: AppointmentDraft): void {
  try {
    localStorage.setItem(draftKey(), JSON.stringify(draft));
  } catch { /* ignore */ }
}

export function clearDraft(): void {
  try {
    localStorage.removeItem(draftKey());
  } catch { /* ignore */ }
}

// ============================================================
// 目录数据（与后端共用 catalog.json）
// ============================================================
export const HOSPITALS: Hospital[] = catalog.hospitals;
export const ALL_CAMPUSES: Campus[] = catalog.campuses;
export const DEPARTMENTS: Dept[] = catalog.departments;
export const PATIENTS: Patient[] = catalog.patients;
export const ALL_DOCTORS: Doctor[] = catalog.doctors;
export const SITE_NOTE: string = catalog.site.note;

// 当前医院从 /hospital/apps/{hospital_id}/ 读取，应用和 API 均按医院隔离。
const appMatch = window.location.pathname.match(/^\/hospital\/apps\/([^/]+)/);
export const ACTIVE_HOSPITAL = HOSPITALS.find((h) => h.id === (appMatch ? decodeURIComponent(appMatch[1]) : ''));
export const APP_BASE = ACTIVE_HOSPITAL ? `/hospital/apps/${ACTIVE_HOSPITAL.id}` : '/hospital';
export const HOSPITAL_NAME = ACTIVE_HOSPITAL?.name || '选择模拟医院';

// 兼容页面里原有的当前医院判断；医院名称不再进入 URL。
export const CURRENT_SITE = ACTIVE_HOSPITAL ? ACTIVE_HOSPITAL.id : '';
export const HOSPITAL: Hospital = ACTIVE_HOSPITAL || HOSPITALS[0];
export const CAMPUSES: Campus[] = ALL_CAMPUSES.filter((c) => c.hospitalId === HOSPITAL.id);
export const DOCTORS: Doctor[] = ALL_DOCTORS.filter((d) => CAMPUSES.some((c) => c.id === d.campusId));

export const siteOf = (h: Hospital) => h.id.replace(/^h-/, '');
/** BrowserRouter 使用 APP_BASE 作为 basename，页面链接只写应用内路径。 */
export const to = (path: string) => path.startsWith('/') ? path : '/' + path;

// ============================================================
// 后端状态：号源 / 预约（启动时加载，提交后局部更新）
// ============================================================
const API = ACTIVE_HOSPITAL ? `/api/hospital/apps/${ACTIVE_HOSPITAL.id}` : '/api/hospital';
let _mockToday: string | null = null;
export let SLOTS: AppointmentSlot[] = [];
let _appointments: Appointment[] = [];

export async function loadState(): Promise<void> {
  const r = await fetch(API + '/state', { cache: 'no-store' });
  if (!r.ok) throw new Error('医院服务暂不可用');
  const d = await r.json();
  _mockToday = d.today;
  SLOTS = d.slots;
  _appointments = d.appointments;
}

export function setMockToday(date: string) { _mockToday = date; }
export function getMockToday(): string {
  if (_mockToday) return _mockToday;
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export function getNext7Days(): string[] {
  const base = new Date(getMockToday() + 'T00:00:00');
  const days: string[] = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(base);
    d.setDate(d.getDate() + i);
    days.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`);
  }
  return days;
}

// ============================================================
// 查询辅助
// ============================================================
export function getSlotsByDoctorDate(doctorId: string, date: string): AppointmentSlot[] {
  return SLOTS.filter((s) => s.doctorId === doctorId && s.date === date && s.campusId === getDraft().campusId);
}
export function getDoctorsByDept(deptId: string): Doctor[] {
  return DOCTORS.filter((d) => d.deptId === deptId);
}
export function getDoctorsByDeptDate(deptId: string, date: string): Doctor[] {
  const doctorIds = new Set(SLOTS.filter((s) => s.departmentId === deptId && s.date === date && s.status === 'available').map((s) => s.doctorId));
  return DOCTORS.filter((d) => doctorIds.has(d.id));
}
export function getSlotById(slotId: string): AppointmentSlot | undefined {
  return SLOTS.find((s) => s.id === slotId);
}
export function matchDeptBySymptom(symptom: string): Dept | null {
  let best: Dept | null = null;
  let bestScore = 0;
  for (const d of DEPARTMENTS) {
    for (const disease of d.diseases) {
      if (symptom.includes(disease) && disease.length > bestScore) { bestScore = disease.length; best = d; }
    }
  }
  return best;
}

// ============================================================
// 预约 / 取消 / 病历（后端校验号源与幂等；v2 起提交前由家人在小艺里确认，不再有授权环节）
// ============================================================
export interface SubmitResult { ok: boolean; error?: string; appointment?: Appointment }

async function call<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(API + path, body === undefined ? { cache: 'no-store' } : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({ detail: '医院服务暂不可用' }));
  if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请求失败');
  return data as T;
}

function remember(appt: Appointment) {
  _appointments = [..._appointments.filter((a) => a.id !== appt.id), appt];
}

export async function submitAppointment(a: { slotId: string; patientId: string; taskId?: string; token?: string }): Promise<SubmitResult> {
  try {
    const appt = await call<Appointment>('/appointments', { slotId: a.slotId, patientId: a.patientId, taskId: a.taskId || '', token: a.token || '' });
    remember(appt);
    const slot = SLOTS.find((s) => s.id === a.slotId);
    if (slot) {
      slot.remaining = Math.max(0, slot.remaining - 1);
      if (slot.remaining <= 0) slot.status = 'full';
    }
    return { ok: true, appointment: appt };
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }
}

export function listAppointments(): Appointment[] {
  return [..._appointments].sort((x, y) => y.createdAt - x.createdAt);
}

export function getAppointmentById(id: string): Appointment | undefined {
  return _appointments.find((a) => a.id === id);
}

export async function fetchAppointment(id: string): Promise<Appointment> {
  const appt = await call<Appointment>('/appointments/' + encodeURIComponent(id));
  remember(appt);
  return appt;
}

export async function cancelAppointment(id: string): Promise<{ ok: boolean; error?: string }> {
  try {
    remember(await call<Appointment>('/appointments/' + encodeURIComponent(id) + '/cancel', {}));
    return { ok: true };
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }
}

export async function payAppointment(id: string, token: string, method: string): Promise<Appointment> {
  const appt = await call<Appointment>('/appointments/' + encodeURIComponent(id) + '/pay', { token, method });
  remember(appt);
  return appt;
}

export async function fetchEmr(id: string): Promise<Emr> {
  return call<Emr>('/appointments/' + encodeURIComponent(id) + '/emr');
}
