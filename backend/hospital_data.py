"""模拟医院的后端数据源：号源、预约、支付与电子病历。

医院网页（hospital/）与小艺后端共用这一份数据：
- 号源按“医生 + 院区 + 日期”确定性生成（同一天刷新不会变），预约后真实扣减；
- 预约、支付、病历持久化在 records（kind=hospital_appt, group_id=0）；
- 关键剧情号源被固定（见 PINS），保证演示可复现。
全部数据为虚构，仅用于产品演示。
"""
import hashlib
import hmac
import json
import os
import random
import re
import time
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import democlock
from .db import DB, Record, get, put

CATALOG_PATH = Path(__file__).resolve().parent.parent / 'hospital' / 'src' / 'catalog.json'
KIND = 'hospital_appt'
GID = 0
LOCK_MINUTES = 15
MORNING = {'主任医师': ['08:30', '10:00'], 'default': ['08:00', '08:30', '09:30']}
AFTERNOON = ['14:00', '15:30']
FAMILIAR_DOCTOR = 'doc-g1'  # 张明远：王秀兰的熟悉医生


@lru_cache(maxsize=1)
def catalog():
    return json.loads(CATALOG_PATH.read_text(encoding='utf-8'))


def campus(cid):
    return next((c for c in catalog()['campuses'] if c['id'] == cid), None)


def department(did):
    return next((d for d in catalog()['departments'] if d['id'] == did), None)


def department_by_name(name):
    if not name:
        return None
    exact = next((d for d in catalog()['departments'] if d['name'] == name), None)
    if exact:
        return exact
    return next((d for d in catalog()['departments'] if name in d['name'] or d['name'] in name), None)


def doctor(doc_id):
    return next((d for d in catalog()['doctors'] if d['id'] == doc_id), None)


def doctor_by_name(name):
    return next((d for d in catalog()['doctors'] if d['name'] == name), None)


def patient(pid):
    return next((p for p in catalog()['patients'] if p['id'] == pid), None)


def patient_for_member(username):
    return next((p for p in catalog()['patients'] if p.get('member') == username), None)


def price(title, campus_id, session):
    if title == '主任医师':
        return 90 if campus_id == 'c-main' else 80
    if title == '副主任医师':
        return 65 if campus_id == 'c-main' else 55
    return 40 if session == 'morning' else 35


def _end(start):
    h, m = map(int, start.split(':'))
    m += 30
    return f'{h + m // 60:02d}:{m % 60:02d}'


def window():
    """可预约的 7 天（以演示时钟的今天为第一天）。"""
    today = democlock.today()
    return [democlock.shift_date(today, i) for i in range(7)]


def _rng(*parts):
    seed = int(hashlib.sha256('|'.join(parts).encode()).hexdigest()[:12], 16)
    return random.Random(seed)


def _pin(doc_id, campus_id, date, start, remaining, status):
    """剧情固定号源：明天上午熟悉医生在总院还剩少量号，东院区骨科上午约满。"""
    tomorrow = democlock.shift_date(democlock.today(), 1)
    doc = doctor(doc_id)
    if doc_id == FAMILIAR_DOCTOR and campus_id == 'c-main':
        # 熟悉医生在总院从不停诊，08:30 始终留有号源（复诊也能约到上次的医生）。
        if start == '08:30':
            return max(1, min(remaining, 3)) if date != tomorrow else 2, 'available'
        if date == tomorrow and start == '08:00':
            return 0, 'full'
        return remaining, ('available' if remaining > 0 else 'full')
    if doc and doc['deptId'] == 'd-guke' and campus_id == 'c-east' and date == tomorrow and start < '12:00':
        return 0, 'full'
    if doc_id == 'doc-g2' and campus_id == 'c-main' and date == tomorrow and start == '09:30':
        return 5, 'available'  # 费用更低（¥40，无需授权）的备选
    return remaining, status


def generate_slots(dates=None):
    dates = dates or window()
    now = democlock.now()
    booked = booked_counts()
    slots = []
    for doc in catalog()['doctors']:
        dept = department(doc['deptId'])
        if not dept:
            continue
        for cid in dept['campusIds']:
            for date in dates:
                weekday = democlock.local(democlock.at(date)).weekday()
                # 周末约四成医生出诊；剧情医生（张明远/李建华/陈志强）周末也出诊
                if weekday >= 5 and doc['id'] not in ('doc-g1', 'doc-g2', 'doc-x1') and _rng('weekend', doc['id'], date).random() < 0.6:
                    continue
                rng = _rng(doc['id'], cid, date)
                suspended = rng.random() < 0.06 and doc['id'] not in (FAMILIAR_DOCTOR, 'doc-g2')
                capacity = 15 if doc['title'] == '主任医师' else 25
                times = [(t, 'morning') for t in MORNING.get(doc['title'], MORNING['default'])] + [(t, 'afternoon') for t in AFTERNOON]
                for start, session in times:
                    base = 0 if suspended else rng.randint(0, 9)
                    status = 'suspended' if suspended else ('available' if base > 0 else 'full')
                    base, status = _pin(doc['id'], cid, date, start, base, status)
                    sid = f"S-{doc['id']}-{cid}-{date.replace('-', '')}-{start.replace(':', '')}"
                    remaining = max(0, base - booked.get(sid, 0))
                    if status == 'available' and remaining == 0:
                        status = 'full'
                    if status == 'available' and democlock.at(date, start) <= now:
                        status, remaining = 'full', 0
                    slots.append({
                        'hospitalId': campus(cid).get('hospitalId', 'legacy-hospital'), 'id': sid, 'doctorId': doc['id'], 'departmentId': dept['id'], 'campusId': cid,
                        'date': date, 'startTime': start, 'endTime': _end(start), 'session': session,
                        'category': 'expert' if doc['title'] == '主任医师' else 'general',
                        'price': price(doc['title'], cid, session), 'capacity': capacity,
                        'remaining': remaining, 'status': status,
                    })
    return slots


def slot(slot_id):
    # 号源编号形如 S-doc-g1-c-main-20261104-0830，末尾是日期与时刻。
    m = re.search(r'-(\d{8})-(\d{4})$', slot_id or '')
    if not m:
        return None
    d = m.group(1)
    return next((s for s in generate_slots([f'{d[:4]}-{d[4:6]}-{d[6:]}']) if s['id'] == slot_id), None)


def find_slots(dept_id, date, session=None, campus_id=None, doctor_id=None):
    return [s for s in generate_slots([date])
            if s['departmentId'] == dept_id and (session is None or s['session'] == session)
            and (campus_id is None or s['campusId'] == campus_id)
            and (doctor_id is None or s['doctorId'] == doctor_id)]


def appointments(db=None):
    def load(session):
        rows = session.query(Record).filter_by(kind=KIND, group_id=GID).order_by(Record.id).all()
        return [r.data for r in rows]
    if db is not None:
        return load(db)
    with DB() as session:
        return load(session)


def booked_counts():
    counts = {}
    for a in appointments():
        if a.get('status') != 'cancelled' and a.get('slotId'):
            counts[a['slotId']] = counts.get(a['slotId'], 0) + 1
    return counts


def pay_token(appt_id):
    secret = os.getenv('PAY_SECRET', 'xiaoyi-family-demo').encode()
    return hmac.new(secret, appt_id.encode(), hashlib.sha256).hexdigest()[:16]


def public(appt):
    value = dict(appt)
    value.setdefault('hospitalId', 'legacy-hospital')
    value.setdefault('hospitalName', appt.get('campusName', '历史模拟医院'))
    if value.get('status') == 'confirmed' and value.get('pay_status') == 'unpaid' and value.get('lock_expires') and value['lock_expires'] < democlock.now():
        value['pay_status'] = 'expired'
    value['payToken'] = pay_token(value['id'])
    return value


def create_appointment(db, slot_id, patient_id, task_id='', token='', created=None):
    """创建预约：校验号源、幂等，成功后号源自然扣减。"""
    if task_id:
        for a in appointments(db):
            if a.get('taskId') == task_id and a.get('status') != 'cancelled':
                return a
    s = slot(slot_id)
    if not s:
        raise ValueError('号源不存在')
    if s['date'] not in window():
        raise ValueError('仅支持未来七天内的模拟号源')
    if s['status'] == 'suspended':
        raise ValueError('该号源已停诊')
    if s['remaining'] <= 0 or s['status'] != 'available':
        raise ValueError('该号源已约满，请更换时间')
    p = patient(patient_id)
    if not p:
        raise ValueError('就诊人不存在')
    for a in appointments(db):
        if a.get('patientId') == patient_id and a.get('status') == 'confirmed' and a.get('date') == s['date'] and a.get('session') == s['session']:
            raise ValueError('同一时段每人限约一个号源')
    doc, dept, camp = doctor(s['doctorId']), department(s['departmentId']), campus(s['campusId'])
    now = democlock.now() if created is None else created
    appt_id = 'AP-' + hashlib.sha256(f'{slot_id}:{patient_id}:{task_id}:{time.time()}'.encode()).hexdigest()[:8].upper()
    appt = {
        'hospitalId': camp.get('hospitalId', 'legacy-hospital'), 'hospitalName': camp['name'], 'id': appt_id, 'slotId': slot_id, 'campusId': camp['id'], 'campusName': camp['name'],
        'deptId': dept['id'], 'deptName': dept['name'], 'doctorId': doc['id'], 'doctorName': doc['name'],
        'doctorTitle': doc['title'], 'date': s['date'], 'session': s['session'], 'startTime': s['startTime'],
        'endTime': s['endTime'], 'category': s['category'], 'fee': s['price'], 'patientName': p['name'],
        'patientId': p['id'], 'taskId': task_id or None, 'createdAt': int(now * 1000), 'status': 'confirmed',
        'pay_status': 'unpaid', 'lock_expires': now + LOCK_MINUTES * 60, 'paid_at': None, 'emr': None,
    }
    put(db, KIND, GID, appt_id, appt)
    return appt


def get_appt(db, appt_id):
    r = get(db, KIND, GID, appt_id)
    return r.data if r else None


def save_appt(db, appt):
    put(db, KIND, GID, appt['id'], appt)
    return appt


def history_count(patient_id, campus_id=None, doctor_id=None):
    return sum(1 for a in appointments()
               if a.get('patientId') == patient_id and a.get('status') == 'completed'
               and (campus_id is None or a.get('campusId') == campus_id)
               and (doctor_id is None or a.get('doctorId') == doctor_id))


# ---------------------------------------------------------------- 电子病历模板（虚构）
EMR_TEMPLATES = {
    'd-guke': {
        'complaint': '右膝关节酸胀疼痛 3 天，阴雨天加重，上下楼梯时明显。',
        'diagnosis': '右膝半月板损伤（退行性），轻度骨关节炎',
        'exam': '右膝内侧关节间隙压痛（+），麦氏征（±），无明显肿胀。',
        'advice': [
            '塞来昔布胶囊 0.2g，每日 1 次，饭后服用，连续 14 天',
            '直腿抬高训练：每天 3 组，每组 15 次；股四头肌等长收缩每天 2 组',
            '近两周避免爬山、爬楼梯、久蹲，可冷敷缓解疼痛',
            '两周后骨科门诊复诊，评估是否开始负重训练',
        ],
        'medications': [{'name': '塞来昔布胶囊', 'dosage': '0.2g', 'frequency': '每日1次', 'timing': '饭后', 'days': 14}],
        'rehab': {'name': '直腿抬高训练', 'detail': '每天 3 组 × 15 次', 'days': 14},
        'follow_up_days': 14,
    },
    'd-xinneike': {
        'complaint': '血压控制欠佳，近一周晨起头胀。',
        'diagnosis': '原发性高血压 2 级',
        'exam': '血压 152/94 mmHg，心率 76 次/分。',
        'advice': [
            '氨氯地平片 5mg，每日 1 次，早晨服用，不可自行停药',
            '每日早晚各测一次血压并记录',
            '低盐饮食，每日食盐不超过 5g',
            '两周后心血管内科复诊，带上血压记录',
        ],
        'medications': [{'name': '氨氯地平片', 'dosage': '5mg', 'frequency': '每日1次', 'timing': '早晨', 'days': 14}],
        'rehab': {'name': '血压记录', 'detail': '早晚各测一次', 'days': 14},
        'follow_up_days': 14,
    },
}


def make_emr(appt):
    tpl = EMR_TEMPLATES.get(appt['deptId']) or EMR_TEMPLATES['d-guke']
    return {
        'hospital': '市第一人民医院', 'campus': appt['campusName'], 'department': appt['deptName'],
        'doctor': appt['doctorName'], 'doctor_title': appt['doctorTitle'], 'patient': appt['patientName'],
        'visit_date': appt['date'], **json.loads(json.dumps(tpl, ensure_ascii=False)),
        'note': '本病历为演示用虚构数据，不构成医疗建议。',
    }


# ---------------------------------------------------------------- 医院网页使用的接口
class BookBody(BaseModel):
    slotId: str = Field(min_length=1, max_length=120)
    patientId: str = Field(min_length=1, max_length=40)
    taskId: str = Field(default='', max_length=128)
    token: str = Field(default='', max_length=128)


class PayBody(BaseModel):
    token: str = Field(min_length=1, max_length=64)
    method: str = Field(default='family', max_length=40)


router = APIRouter(prefix='/api/hospital', tags=['模拟医院'])


@router.get('/state')
def state():
    with DB() as db:
        rows = [public(a) for a in appointments(db)]
    return {'today': democlock.today(), 'now': democlock.now(), 'hospital': catalog()['hospital'],
            'campuses': catalog()['campuses'], 'hospitals': catalog().get('hospitals', []), 'slots': generate_slots(), 'appointments': rows}


@router.post('/appointments')
def book(body: BookBody):
    with DB() as db:
        try:
            appt = create_appointment(db, body.slotId, body.patientId, body.taskId, body.token)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        db.commit()
        return public(appt)


@router.get('/appointments/{appt_id}')
def detail(appt_id: str):
    with DB() as db:
        appt = get_appt(db, appt_id)
    if not appt:
        raise HTTPException(404, '预约不存在')
    return public(appt)


@router.post('/appointments/{appt_id}/cancel')
def cancel(appt_id: str):
    with DB() as db:
        appt = get_appt(db, appt_id)
        if not appt:
            raise HTTPException(404, '预约不存在')
        if appt['status'] != 'confirmed':
            raise HTTPException(409, '当前状态不可取消')
        appt['status'] = 'cancelled'
        save_appt(db, appt)
        db.commit()
    return public(appt)


@router.post('/appointments/{appt_id}/pay')
async def pay(appt_id: str, body: PayBody):
    """模拟收银台：支付只能由用户在收银台页面点击完成，小艺无法代付。"""
    if not hmac.compare_digest(body.token, pay_token(appt_id)):
        raise HTTPException(403, '支付凭证无效')
    with DB() as db:
        appt = get_appt(db, appt_id)
        if not appt:
            raise HTTPException(404, '订单不存在')
        if appt['pay_status'] == 'paid':
            return public(appt)
        if appt['status'] != 'confirmed':
            raise HTTPException(409, '订单已取消，无法支付')
        if public(appt)['pay_status'] == 'expired':
            raise HTTPException(409, '锁号已超时，请重新预约')
        appt.update(pay_status='paid', paid_at=democlock.now(), pay_method=body.method)
        save_appt(db, appt)
        db.commit()
    from .care import on_paid
    await on_paid(appt)
    return public(appt)


@router.get('/appointments/{appt_id}/emr')
def emr(appt_id: str):
    with DB() as db:
        appt = get_appt(db, appt_id)
    if not appt or not appt.get('emr'):
        raise HTTPException(404, '暂无病历')
    return appt['emr']
