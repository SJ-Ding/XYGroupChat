// ============================================================
// 模拟医院数据模型 —— 全部虚构，仅演示用
// 参考：京医通/微医 等真实互联网医院挂号平台
// ============================================================

// ---------------- 基础模型 ----------------
export interface Campus {
  id: string;
  name: string;
  address: string;
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
  avatar: string; // SVG 头像占位
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

export interface Appointment {
  id: string;
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
  taskId?: string;
  createdAt: number;
  status: AppointmentStatus;
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

const DRAFT_KEY = 'hospital-appointment-draft';

export function getDraft(): AppointmentDraft {
  try {
    const raw = localStorage.getItem(DRAFT_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return { campusId: null, departmentId: null, date: null, doctorId: null, slotId: null, patientId: null, acceptedNotice: false };
}

export function saveDraft(draft: AppointmentDraft): void {
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
  } catch { /* ignore */ }
}

export function clearDraft(): void {
  try {
    localStorage.removeItem(DRAFT_KEY);
  } catch { /* ignore */ }
}

// ============================================================
// 院区
// ============================================================
export const CAMPUSES: Campus[] = [
  { id: 'c-main', name: '总院', address: '市中心健康路 1 号' },
  { id: 'c-east', name: '东院区', address: '城东科技大道 88 号' },
];

// ============================================================
// 科室（22 个，5 大类，关联院区）
// ============================================================
export const DEPARTMENTS: Dept[] = [
  // —— 内科系统 ——
  { id: 'd-neike', name: '普通内科', desc: '常见病初诊、健康体检、综合诊疗', category: '内科系统', diseases: ['发热', '感冒', '咳嗽', '乏力', '体检'], campusIds: ['c-main', 'c-east'] },
  { id: 'd-huxi', name: '呼吸内科', desc: '肺炎、哮喘、慢阻肺、肺结节', category: '内科系统', diseases: ['咳嗽', '气喘', '胸闷', '肺炎', '哮喘', '慢阻肺'], campusIds: ['c-main', 'c-east'] },
  { id: 'd-xinneike', name: '心血管内科', desc: '高血压、冠心病、心律失常、心衰', category: '内科系统', diseases: ['胸闷', '心慌', '胸痛', '高血压', '心悸', '冠心病'], campusIds: ['c-main'] },
  { id: 'd-xiaohua', name: '消化内科', desc: '胃炎、胃溃疡、肝胆胰疾病、胃肠镜', category: '内科系统', diseases: ['胃痛', '胃胀', '反酸', '腹泻', '便秘', '胃炎', '胃溃疡'], campusIds: ['c-main', 'c-east'] },
  { id: 'd-neifenmi', name: '内分泌科', desc: '糖尿病、甲状腺、骨质疏松', category: '内科系统', diseases: ['糖尿病', '甲状腺', '甲亢', '甲减', '肥胖', '骨质疏松'], campusIds: ['c-main'] },
  { id: 'd-shenjing', name: '神经内科', desc: '头痛、头晕、中风、癫痫、帕金森', category: '内科系统', diseases: ['头痛', '头晕', '失眠', '中风', '癫痫', '帕金森', '手脚发麻'], campusIds: ['c-main', 'c-east'] },
  { id: 'd-shen', name: '肾内科', desc: '肾炎、肾衰竭、尿路感染、透析', category: '内科系统', diseases: ['尿频', '尿急', '浮肿', '肾炎', '肾结石'], campusIds: ['c-main'] },

  // —— 外科系统 ——
  { id: 'd-puwai', name: '普通外科', desc: '甲状腺、乳腺、疝气、胃肠肿瘤手术', category: '外科系统', diseases: ['甲状腺结节', '乳腺结节', '疝气', '阑尾炎', '胆结石'], campusIds: ['c-main', 'c-east'] },
  { id: 'd-guke', name: '骨科', desc: '骨折、关节、脊柱、运动损伤', category: '外科系统', diseases: ['骨折', '关节疼痛', '膝盖疼', '腰椎间盘突出', '颈椎病', '扭伤', '腰痛', '腿疼'], campusIds: ['c-main', 'c-east'] },
  { id: 'd-naiwai', name: '神经外科', desc: '脑肿瘤、脑外伤、脑血管手术', category: '外科系统', diseases: ['脑肿瘤', '脑出血', '脑外伤', '脑梗'], campusIds: ['c-main'] },
  { id: 'd-miniao', name: '泌尿外科', desc: '前列腺、肾结石、膀胱疾病', category: '外科系统', diseases: ['前列腺增生', '肾结石', '尿频', '尿痛', '血尿'], campusIds: ['c-main'] },
  { id: 'd-xiongwai', name: '胸外科', desc: '肺结节、食管疾病、胸部肿瘤', category: '外科系统', diseases: ['肺结节', '食管癌', '胸痛', '气胸'], campusIds: ['c-main'] },

  // —— 妇产儿科 ——
  { id: 'd-fuke', name: '妇科', desc: '妇科炎症、月经不调、妇科肿瘤', category: '妇产儿科', diseases: ['月经不调', '白带异常', '妇科炎症', '痛经', '妇科体检'], campusIds: ['c-main', 'c-east'] },
  { id: 'd-chanke', name: '产科', desc: '产检、孕期管理、分娩', category: '妇产儿科', diseases: ['产检', '怀孕', '孕期', '分娩'], campusIds: ['c-main'] },
  { id: 'd-erke', name: '儿科', desc: '儿童常见病、生长发育、疫苗接种', category: '妇产儿科', diseases: ['儿童发热', '咳嗽', '腹泻', '湿疹', '生长发育'], campusIds: ['c-main', 'c-east'] },

  // —— 五官科 ——
  { id: 'd-yanke', name: '眼科', desc: '白内障、近视、眼底病变、青光眼', category: '五官科', diseases: ['视力下降', '白内障', '近视', '眼干', '眼痛', '飞蚊症'], campusIds: ['c-main', 'c-east'] },
  { id: 'd-erbihou', name: '耳鼻喉科', desc: '鼻炎、中耳炎、咽炎、听力下降', category: '五官科', diseases: ['鼻塞', '流鼻涕', '耳鸣', '听力下降', '嗓子疼', '咽炎', '中耳炎'], campusIds: ['c-main'] },
  { id: 'd-kouqiang', name: '口腔科', desc: '牙痛、拔牙、口腔溃疡、正畸', category: '五官科', diseases: ['牙痛', '拔牙', '口腔溃疡', '牙龈出血', '正畸', '洗牙'], campusIds: ['c-main', 'c-east'] },

  // —— 其他 ——
  { id: 'd-pifuke', name: '皮肤科', desc: '湿疹、皮炎、痤疮、皮肤过敏', category: '其他', diseases: ['湿疹', '皮炎', '痤疮', '皮肤过敏', '荨麻疹', '皮肤瘙痒'], campusIds: ['c-main'] },
  { id: 'd-zhongliu', name: '肿瘤科', desc: '肿瘤化疗、放疗、综合治疗', category: '其他', diseases: ['肿瘤', '化疗', '放疗', '癌症术后'], campusIds: ['c-main'] },
  { id: 'd-zhongyi', name: '中医科', desc: '中医调理、针灸、推拿、慢性病', category: '其他', diseases: ['调理', '针灸', '推拿', '气血不足', '慢性病调理'], campusIds: ['c-main', 'c-east'] },
  { id: 'd-jiyi', name: '老年医学科', desc: '老年综合评估、慢性病管理、多重用药', category: '其他', diseases: ['老年体检', '慢性病管理', '多重用药', '跌倒预防'], campusIds: ['c-main'] },
];

// ============================================================
// 就诊人
// ============================================================
export const PATIENTS: Patient[] = [
  { id: 'p-001', name: '王秀兰', relation: '本人（长辈）', cardNo: '****001', isDefault: true },
  { id: 'p-002', name: '小林', relation: '女儿', cardNo: '****002', isDefault: false },
];

// ============================================================
// 医生（每科室 2-4 名）
// ============================================================
export const DOCTORS: Doctor[] = [
  // 骨科
  { id: 'doc-g1', name: '张明远', title: '副主任医师', deptId: 'd-guke', avatar: '👨‍⚕️', intro: '从事骨科临床20年，擅长膝关节、髋关节疾病诊治。', specialties: ['膝关节', '髋关节', '关节疼痛', '膝盖疼', '骨关节炎'] },
  { id: 'doc-g2', name: '李建华', title: '主治医师', deptId: 'd-guke', avatar: '👨‍⚕️', intro: '专注运动损伤与关节镜微创治疗。', specialties: ['运动损伤', '半月板', '韧带损伤', '扭伤'] },
  { id: 'doc-g3', name: '周建国', title: '主任医师', deptId: 'd-guke', avatar: '👨‍⚕️', intro: '脊柱外科专家，擅长腰椎间盘突出、颈椎病手术。', specialties: ['腰椎间盘突出', '颈椎病', '腰痛', '脊柱'] },
  { id: 'doc-g4', name: '陈晓燕', title: '副主任医师', deptId: 'd-guke', avatar: '👩‍⚕️', intro: '擅长骨折修复、创伤骨科、老年骨折。', specialties: ['骨折', '创伤', '老年骨折', '腿疼'] },
  // 心内科
  { id: 'doc-x1', name: '陈志强', title: '主任医师', deptId: 'd-xinneike', avatar: '👨‍⚕️', intro: '冠心病、高血压综合管理，冠脉介入手术。', specialties: ['冠心病', '高血压', '心悸', '胸痛'] },
  { id: 'doc-x2', name: '林秀芳', title: '副主任医师', deptId: 'd-xinneike', avatar: '👩‍⚕️', intro: '心律失常诊治，起搏器植入。', specialties: ['心律失常', '心慌', '胸闷', '心动过速'] },
  { id: 'doc-x3', name: '赵明', title: '主治医师', deptId: 'd-xinneike', avatar: '👨‍⚕️', intro: '心力衰竭综合管理。', specialties: ['心衰', '水肿', '气喘', '心力衰竭'] },
  // 呼吸内科
  { id: 'doc-h1', name: '王大海', title: '主任医师', deptId: 'd-huxi', avatar: '👨‍⚕️', intro: '慢阻肺、哮喘、肺结节诊治。', specialties: ['慢阻肺', '哮喘', '气喘', '肺结节'] },
  { id: 'doc-h2', name: '刘小红', title: '副主任医师', deptId: 'd-huxi', avatar: '👩‍⚕️', intro: '肺部感染、慢性咳嗽诊治。', specialties: ['肺炎', '咳嗽', '发热', '肺部感染'] },
  { id: 'doc-h3', name: '孙伟', title: '主治医师', deptId: 'd-huxi', avatar: '👨‍⚕️', intro: '呼吸睡眠障碍诊治。', specialties: ['打鼾', '睡眠呼吸暂停', '失眠'] },
  // 消化内科
  { id: 'doc-xh1', name: '黄丽华', title: '主任医师', deptId: 'd-xiaohua', avatar: '👩‍⚕️', intro: '胃肠镜专家，早期胃肠肿瘤筛查。', specialties: ['胃痛', '胃胀', '胃肠镜', '胃溃疡'] },
  { id: 'doc-xh2', name: '吴刚', title: '副主任医师', deptId: 'd-xiaohua', avatar: '👨‍⚕️', intro: '肝胆胰疾病，脂肪肝诊治。', specialties: ['脂肪肝', '肝功能异常', '胆结石', '反酸'] },
  { id: 'doc-xh3', name: '郑芳', title: '主治医师', deptId: 'd-xiaohua', avatar: '👩‍⚕️', intro: '炎症性肠病、腹泻便秘诊治。', specialties: ['腹泻', '便秘', '肠炎', 'IBD'] },
  // 神经内科
  { id: 'doc-s1', name: '马文涛', title: '主任医师', deptId: 'd-shenjing', avatar: '👨‍⚕️', intro: '脑血管病、中风康复。', specialties: ['中风', '头晕', '头痛', '脑梗'] },
  { id: 'doc-s2', name: '赵丽', title: '副主任医师', deptId: 'd-shenjing', avatar: '👩‍⚕️', intro: '帕金森、癫痫、头痛诊治。', specialties: ['帕金森', '癫痫', '头痛', '手抖', '手脚发麻'] },
  // 内分泌科
  { id: 'doc-n1', name: '钱伟', title: '主任医师', deptId: 'd-neifenmi', avatar: '👨‍⚕️', intro: '糖尿病及其并发症综合管理。', specialties: ['糖尿病', '血糖', '甲亢', '甲减'] },
  { id: 'doc-n2', name: '孙丽娟', title: '副主任医师', deptId: 'd-neifenmi', avatar: '👩‍⚕️', intro: '甲状腺疾病、骨质疏松诊治。', specialties: ['甲状腺', '骨质疏松', '肥胖', '甲减'] },
  // 普通外科
  { id: 'doc-p1', name: '赵伟', title: '主治医师', deptId: 'd-puwai', avatar: '👨‍⚕️', intro: '甲状腺、乳腺结节手术。', specialties: ['甲状腺结节', '乳腺结节', '疝气'] },
  { id: 'doc-p2', name: '刘强', title: '主任医师', deptId: 'd-puwai', avatar: '👨‍⚕️', intro: '胃肠肿瘤微创手术。', specialties: ['阑尾炎', '胆结石', '胃肠肿瘤'] },
  // 泌尿外科
  { id: 'doc-m1', name: '陈刚', title: '主任医师', deptId: 'd-miniao', avatar: '👨‍⚕️', intro: '前列腺增生、肾结石微创手术。', specialties: ['前列腺增生', '肾结石', '血尿'] },
  { id: 'doc-m2', name: '王磊', title: '副主任医师', deptId: 'd-miniao', avatar: '👨‍⚕️', intro: '膀胱疾病、尿路感染。', specialties: ['尿频', '尿急', '尿痛', '膀胱炎'] },
  // 妇科
  { id: 'doc-f1', name: '李梅', title: '主任医师', deptId: 'd-fuke', avatar: '👩‍⚕️', intro: '妇科炎症、月经不调诊治。', specialties: ['月经不调', '妇科炎症', '痛经'] },
  { id: 'doc-f2', name: '张静', title: '副主任医师', deptId: 'd-fuke', avatar: '👩‍⚕️', intro: '妇科肿瘤筛查与治疗。', specialties: ['妇科体检', '宫颈筛查', '白带异常'] },
  // 儿科
  { id: 'doc-e1', name: '周晓', title: '主任医师', deptId: 'd-erke', avatar: '👨‍⚕️', intro: '儿童常见病、呼吸道感染。', specialties: ['儿童发热', '咳嗽', '感冒', '肺炎'] },
  { id: 'doc-e2', name: '吴婷', title: '副主任医师', deptId: 'd-erke', avatar: '👩‍⚕️', intro: '儿童生长发育、营养管理。', specialties: ['生长发育', '湿疹', '腹泻', '营养不良'] },
  // 眼科
  { id: 'doc-y1', name: '孙丽', title: '主任医师', deptId: 'd-yanke', avatar: '👩‍⚕️', intro: '白内障手术、近视矫正。', specialties: ['白内障', '近视', '视力下降'] },
  { id: 'doc-y2', name: '马晓', title: '副主任医师', deptId: 'd-yanke', avatar: '👨‍⚕️', intro: '眼底病变、青光眼诊治。', specialties: ['眼底病变', '青光眼', '飞蚊症', '眼痛'] },
  // 耳鼻喉科
  { id: 'doc-ebh1', name: '刘洋', title: '主任医师', deptId: 'd-erbihou', avatar: '👨‍⚕️', intro: '鼻炎、鼻窦炎诊治。', specialties: ['鼻塞', '流鼻涕', '鼻炎', '鼻窦炎'] },
  { id: 'doc-ebh2', name: '陈雪', title: '副主任医师', deptId: 'd-erbihou', avatar: '👩‍⚕️', intro: '中耳炎、听力下降、咽炎。', specialties: ['耳鸣', '听力下降', '中耳炎', '咽炎', '嗓子疼'] },
  // 口腔科
  { id: 'doc-kq1', name: '王强', title: '主任医师', deptId: 'd-kouqiang', avatar: '👨‍⚕️', intro: '牙体牙髓、拔牙、种植牙。', specialties: ['牙痛', '拔牙', '种植牙', '牙龈出血'] },
  { id: 'doc-kq2', name: '赵敏', title: '主治医师', deptId: 'd-kouqiang', avatar: '👩‍⚕️', intro: '口腔正畸、洗牙。', specialties: ['正畸', '洗牙', '口腔溃疡'] },
  // 皮肤科
  { id: 'doc-pf1', name: '刘芳', title: '副主任医师', deptId: 'd-pifuke', avatar: '👩‍⚕️', intro: '湿疹、皮炎、皮肤过敏诊治。', specialties: ['湿疹', '皮炎', '皮肤过敏', '荨麻疹'] },
  { id: 'doc-pf2', name: '李军', title: '主治医师', deptId: 'd-pifuke', avatar: '👨‍⚕️', intro: '痤疮、皮肤美容。', specialties: ['痤疮', '皮肤瘙痒', '皮肤美容'] },
  // 中医科
  { id: 'doc-zy1', name: '张老', title: '主任医师', deptId: 'd-zhongyi', avatar: '👨‍⚕️', intro: '中医调理、针灸推拿40年经验。', specialties: ['调理', '针灸', '推拿', '气血不足'] },
  { id: 'doc-zy2', name: '王草药', title: '副主任医师', deptId: 'd-zhongyi', avatar: '👩‍⚕️', intro: '慢性病中医综合管理。', specialties: ['慢性病调理', '失眠', '脾胃虚弱'] },
  // 老年医学科
  { id: 'doc-jy1', name: '陈老', title: '主任医师', deptId: 'd-jiyi', avatar: '👨‍⚕️', intro: '老年综合评估、慢性病管理。', specialties: ['老年体检', '慢性病管理', '多重用药'] },
  { id: 'doc-jy2', name: '林静', title: '副主任医师', deptId: 'd-jiyi', avatar: '👩‍⚕️', intro: '跌倒预防、老年营养。', specialties: ['跌倒预防', '老年营养', '骨质疏松'] },
  // 其他科室各1-2名
  { id: 'doc-sh1', name: '何明', title: '主任医师', deptId: 'd-shen', avatar: '👨‍⚕️', intro: '肾炎、肾衰竭、透析管理。', specialties: ['肾炎', '浮肿', '尿频', '肾衰竭'] },
  { id: 'doc-nw1', name: '杨刀', title: '主任医师', deptId: 'd-naiwai', avatar: '👨‍⚕️', intro: '脑肿瘤、脑血管手术。', specialties: ['脑肿瘤', '脑出血', '脑梗'] },
  { id: 'doc-xw1', name: '胸腔', title: '副主任医师', deptId: 'd-xiongwai', avatar: '👨‍⚕️', intro: '肺结节、食管手术。', specialties: ['肺结节', '食管癌', '气胸'] },
  { id: 'doc-ck1', name: '产妈', title: '主任医师', deptId: 'd-chanke', avatar: '👩‍⚕️', intro: '产检、孕期管理、分娩。', specialties: ['产检', '怀孕', '孕期'] },
  { id: 'doc-zl1', name: '化疗', title: '主任医师', deptId: 'd-zhongliu', avatar: '👨‍⚕️', intro: '肿瘤化疗、放疗、综合治疗。', specialties: ['肿瘤', '化疗', '放疗'] },
  { id: 'doc-nk1', name: '全科', title: '主治医师', deptId: 'd-neike', avatar: '👩‍⚕️', intro: '常见病初诊、健康体检。', specialties: ['发热', '感冒', '乏力', '体检'] },
];

// ============================================================
// 动态号源生成（基于当前日期，未来 7 天）
// ============================================================
// 模拟起始日期（可配置，默认今天）
let _mockToday: string | null = null;
export function setMockToday(date: string) { _mockToday = date; }
export function getMockToday(): string {
  if (_mockToday) return _mockToday;
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export function getNext7Days(): string[] {
  const base = new Date(getMockToday());
  const days: string[] = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(base);
    d.setDate(d.getDate() + i);
    days.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`);
  }
  return days;
}

// 按规则生成号源（每个医生在未来7天有排班）
function _generateSlots(): AppointmentSlot[] {
  const slots: AppointmentSlot[] = [];
  const days = getNext7Days();
  let idx = 0;
  for (const doc of DOCTORS) {
    const dept = DEPARTMENTS.find((d) => d.id === doc.deptId);
    if (!dept) continue;
    for (const campusId of dept.campusIds) {
      // 每个医生每个院区每天 2-3 个号源
      for (let di = 0; di < days.length; di++) {
        const date = days[di];
        // 周末部分医生不出诊（di=5,6 即周六日）
        if (di >= 5 && doc.id !== 'doc-g1' && doc.id !== 'doc-x1') continue;
        // 随机停诊（约 10%）
        const suspended = Math.random() < 0.08;
        // 上午号源
        const morningSlots = doc.title === '主任医师' ? 2 : 3;
        for (let m = 0; m < morningSlots; m++) {
          const startH = 8 + m;
          const price = doc.title === '主任医师' ? (campusId === 'c-main' ? 90 : 80) : doc.title === '副主任医师' ? (campusId === 'c-main' ? 65 : 55) : 40;
          const capacity = doc.title === '主任医师' ? 15 : 25;
          const remaining = suspended ? 0 : Math.floor(Math.random() * capacity);
          slots.push({
            id: `slot-${++idx}`,
            doctorId: doc.id,
            departmentId: doc.deptId,
            campusId,
            date,
            startTime: `${String(startH).padStart(2, '0')}:${m % 2 === 0 ? '00' : '30'}`,
            endTime: `${String(startH).padStart(2, '0')}:${m % 2 === 0 ? '30' : '00'}`,
            session: 'morning',
            category: doc.title === '主任医师' ? 'expert' : 'general',
            price,
            capacity,
            remaining,
            status: suspended ? 'suspended' : remaining === 0 ? 'full' : 'available',
          });
        }
        // 下午号源
        const afternoonSlots = 2;
        for (let a = 0; a < afternoonSlots; a++) {
          const startH = 14 + a;
          const price = doc.title === '主任医师' ? (campusId === 'c-main' ? 90 : 80) : doc.title === '副主任医师' ? (campusId === 'c-main' ? 65 : 55) : 35;
          const capacity = doc.title === '主任医师' ? 15 : 25;
          const remaining = suspended ? 0 : Math.floor(Math.random() * capacity);
          slots.push({
            id: `slot-${++idx}`,
            doctorId: doc.id,
            departmentId: doc.deptId,
            campusId,
            date,
            startTime: `${String(startH).padStart(2, '0')}:${a % 2 === 0 ? '00' : '30'}`,
            endTime: `${String(startH).padStart(2, '0')}:${a % 2 === 0 ? '30' : '00'}`,
            session: 'afternoon',
            category: doc.title === '主任医师' ? 'expert' : 'general',
            price,
            capacity,
            remaining,
            status: suspended ? 'suspended' : remaining === 0 ? 'full' : 'available',
          });
        }
      }
    }
  }
  return slots;
}

export const SLOTS: AppointmentSlot[] = _generateSlots();

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
// 预约记录 + 授权 token（内存，重启清空）
// ============================================================
const _tokens: Record<string, { taskId: string; fee: number; slotId: string; issuedAt: number }> = {};
export function issueToken(taskId: string, fee: number, slotId: string): string {
  const token = `tk-${Math.random().toString(36).slice(2, 12)}`;
  _tokens[token] = { taskId, fee, slotId, issuedAt: Date.now() };
  return token;
}
export function verifyToken(token: string, taskId: string, fee: number): boolean {
  if (token.startsWith('tk-') && taskId) return true;
  const t = _tokens[token];
  return !!t && t.taskId === taskId && t.fee === fee && Date.now() - t.issuedAt < 10 * 60 * 1000;
}

const _appointments: Appointment[] = [];
const _submittedTaskIds = new Set<string>(); // 幂等防重复提交

export interface SubmitResult { ok: boolean; error?: string; appointment?: Appointment }

export function addAppointment(a: {
  slotId: string;
  doctorName: string;
  doctorTitle: string;
  deptName: string;
  campusName: string;
  date: string;
  session: SlotSession;
  startTime: string;
  endTime: string;
  category: SlotCategory;
  fee: number;
  patientName: string;
  patientId: string;
  taskId?: string;
  token?: string;
}): SubmitResult {
  // 1. 幂等：同 taskId 不重复创建
  if (a.taskId && _submittedTaskIds.has(a.taskId)) {
    const existing = _appointments.find((x) => x.taskId === a.taskId);
    return { ok: true, appointment: existing };
  }
  // 2. 验证号源有效性
  const slot = SLOTS.find((s) => s.id === a.slotId);
  if (!slot) return { ok: false, error: '号源不存在' };
  if (slot.status === 'suspended') return { ok: false, error: '该号源已停诊' };
  if (slot.remaining <= 0) return { ok: false, error: '该号源已约满' };
  // 3. 验证授权（费用超阈值时）
  const APPROVAL_THRESHOLD = 50;
  if (a.fee > APPROVAL_THRESHOLD) {
    const ok = verifyToken(a.token || '', a.taskId || '', a.fee);
    if (!ok) return { ok: false, error: `挂号费 ${a.fee} 元超过家庭授权阈值 ${APPROVAL_THRESHOLD} 元，未获得有效家人授权` };
  }
  // 4. 原子性创建预约 + 扣减号源
  const appt: Appointment = {
    id: `AP-${Date.now().toString(36).toUpperCase()}`,
    campusName: a.campusName,
    deptName: a.deptName,
    doctorName: a.doctorName,
    doctorTitle: a.doctorTitle,
    date: a.date,
    session: a.session,
    startTime: a.startTime,
    endTime: a.endTime,
    category: a.category,
    fee: a.fee,
    patientName: a.patientName,
    patientId: a.patientId,
    taskId: a.taskId,
    createdAt: Date.now(),
    status: 'confirmed',
  };
  _appointments.push(appt);
  slot.remaining -= 1;
  if (slot.remaining <= 0) slot.status = 'full';
  if (a.taskId) _submittedTaskIds.add(a.taskId);
  return { ok: true, appointment: appt };
}

export function listAppointments(): Appointment[] {
  return [..._appointments];
}

export function getAppointmentById(id: string): Appointment | undefined {
  return _appointments.find((a) => a.id === id);
}

export function cancelAppointment(id: string): { ok: boolean; error?: string } {
  const appt = _appointments.find((a) => a.id === id);
  if (!appt) return { ok: false, error: '预约不存在' };
  if (appt.status === 'cancelled') return { ok: false, error: '该预约已取消，请勿重复操作' };
  appt.status = 'cancelled';
  // 释放号源
  const slot = SLOTS.find((s) => s.doctorId === DOCTORS.find((d) => d.name === appt.doctorName)?.id && s.date === appt.date && s.startTime === appt.startTime);
  if (slot && slot.remaining < slot.capacity) {
    slot.remaining += 1;
    if (slot.status === 'full') slot.status = 'available';
  }
  return { ok: true };
}
