"""“家人帮”演示数据：一键重置到可复现的初始状态。

人物、病史、医生和号源均为虚构；医院名称与地址来自高德公开数据，仅用于产品演示。
重置会清空聊天、记忆与任务记录（账号与群成员保留），并把演示时钟拨到“今天 20:10”。
"""
import time
from datetime import datetime

from sqlalchemy import text

from . import democlock
from .db import DB, Message, User, get, put
from .memory import save_memory
from .persona import DEFAULT_AGENT_NAME, DEFAULT_PROMPT

GID = 1
START_CLOCK = '20:10'
PRIMARY_CAMPUS = 'c-jsph'

# 家庭画像（演示用）。username 与 URL 身份一致：dad / mom / child。
FAMILY = {
    'mom': {'name': '妈妈', 'real_name': '王秀兰', 'relation': '妈妈', 'age': 62, 'role': 'elder',
            'patient_id': 'p-001', 'conditions': ['右膝半月板损伤（2024）'], 'allergies': ['青霉素'],
            'dept': 'd-guke', 'note': '一个人住在南京，阴雨天膝盖容易酸痛'},
    'dad': {'name': '爸爸', 'real_name': '林志强', 'relation': '爸爸', 'age': 65, 'role': 'elder',
            'patient_id': 'p-003', 'conditions': ['高血压'], 'allergies': [],
            'dept': 'd-xinneike', 'note': '每天早上 8 点吃降压药，偶尔会忘'},
    'child': {'name': '小林', 'real_name': '林晓', 'relation': '女儿', 'age': 34, 'role': 'caregiver',
              'patient_id': 'p-002', 'conditions': [], 'allergies': [],
              'dept': None, 'note': '在上海工作，远程照顾爸妈'},
}
CAREGIVER = 'child'
ELDERS = ('mom', 'dad')
HOME = {'address': '南京市鼓楼区中山北路（道路级位置）', 'city': '南京', 'lng': 118.761667, 'lat': 32.078348}


def user_ids(db):
    return {u.username: u.id for u in db.query(User).all()}


def day0(db=None):
    def read(session):
        state = get(session, 'demo', GID, 'state')
        return state.data.get('day0') if state else democlock.today()
    if db is not None:
        return read(db)
    with DB() as session:
        return read(session)


def _message(db, uid, content, created, key):
    m = Message(group_id=GID, user_id=uid, client_id='seed:' + key, content=content, attachments='[]', created=created)
    db.add(m)
    db.flush()
    return m.id


def _memory(db, ids, key, member, content, domain='general', profile=None, category='fact'):
    uid = ids[member]
    save_memory(db, GID, content, [], [FAMILY[member]['name']], key=key, manual=True, explicit=True,
                domain=domain, profile=({**profile, 'member_id': uid, 'member_name': FAMILY[member]['real_name']} if profile else None),
                metadata={'subject_ids': [uid], 'category': category}, now=democlock.now())


def _appointment(db, appt_id, patient, campus, dept, doctor, date, start, fee, created):
    from . import hospital_data as H
    camp, dep, doc, pat = H.campus(campus), H.department(dept), H.doctor(doctor), H.patient(patient)
    hosp = H.hospital_of(campus)
    put(db, H.KIND, H.GID, appt_id, {
        'id': appt_id, 'slotId': None, 'campusId': campus, 'campusName': camp['name'], 'deptId': dept,
        'hospitalId': hosp['id'], 'hospitalName': hosp['name'],
        'deptName': dep['name'], 'doctorId': doctor, 'doctorName': doc['name'], 'doctorTitle': doc['title'],
        'date': date, 'session': 'morning', 'startTime': start, 'endTime': H._end(start), 'category': 'general',
        'fee': fee, 'patientName': pat['name'], 'patientId': patient, 'taskId': None,
        'createdAt': int(created * 1000), 'status': 'completed', 'pay_status': 'paid', 'lock_expires': None,
        'paid_at': created, 'emr': None, 'history': True,
    })


def seed(db):
    d0 = democlock.today()
    now = democlock.now()
    shift = lambda days: democlock.shift_date(d0, days)
    ids = user_ids(db)
    names = {'dad': '爸爸', 'mom': '妈妈', 'child': '小林'}
    for login, name in names.items():
        u = db.query(User).filter_by(username=login).first()
        if u:
            u.name = name
    put(db, 'demo', GID, 'state', {'day0': d0, 'reset_at': now, 'steps': {}})

    # 家庭档案：结构化医疗记忆（domain=medical，带 profile）+ 日常偏好
    _memory(db, ids, 'seed-mom-history', 'mom', '妈妈（王秀兰，62岁）2024年右膝半月板损伤，阴雨天和久走后容易酸痛',
            'medical', {'record_type': 'history', 'condition': '右膝半月板损伤', 'department': '骨科'}, 'medical')
    from . import hospital_data as H
    campus = H.campus(PRIMARY_CAMPUS)
    hospital_name = H.hospital_of(PRIMARY_CAMPUS)['name']
    _memory(db, ids, 'seed-mom-hospital', 'mom', f'妈妈常去{hospital_name}骨科，近一年模拟就诊过3次',
            'medical', {'record_type': 'hospital', 'hospital': hospital_name, 'hospital_id': campus.get('hospitalId'), 'campus': campus['name'], 'campus_id': PRIMARY_CAMPUS,
                        'department': '骨科', 'visits': 3}, 'medical')
    _memory(db, ids, 'seed-mom-doctor', 'mom', '妈妈上次看的是骨科张明远副主任医师，对他很信任',
            'medical', {'record_type': 'doctor', 'doctor': '张明远', 'doctor_id': 'doc-g1', 'department': '骨科'}, 'medical')
    _memory(db, ids, 'seed-mom-allergy', 'mom', '妈妈对青霉素过敏，就诊时要提醒医生',
            'medical', {'record_type': 'history', 'allergy': '青霉素'}, 'medical')
    _memory(db, ids, 'seed-mom-pref', 'mom', '妈妈上午精神好，看病喜欢约上午的号', category='preference')
    _memory(db, ids, 'seed-mom-home', 'mom', '妈妈和爸爸住在南京鼓楼区中山北路，附近有两家综合医院，位置精度为道路级', category='fact')
    _memory(db, ids, 'seed-dad-history', 'dad', '爸爸（林志强，65岁）高血压多年，每天早上8点吃氨氯地平5mg',
            'medical', {'record_type': 'medication', 'condition': '高血压', 'department': '心血管内科',
                        'medications': [{'name': '氨氯地平', 'dosage': '5mg', 'frequency': '每日一次 08:00'}]}, 'medical')
    _memory(db, ids, 'seed-dad-hospital', 'dad', f'爸爸在{hospital_name}模拟心血管内科看陈志强主任，每三个月复查一次血压',
            'medical', {'record_type': 'doctor', 'doctor': '陈志强', 'doctor_id': 'doc-x1', 'department': '心血管内科'}, 'medical')
    _memory(db, ids, 'seed-dad-habit', 'dad', '爸爸不爱去大医院排队，降压药偶尔会忘吃', category='preference')
    _memory(db, ids, 'seed-child', 'child', '小林在上海工作，是家里的照护人，平时远程帮爸妈办事', category='fact')

    # 历史就诊（医院平台记录）
    _appointment(db, 'AP-HIS0001', 'p-001', PRIMARY_CAMPUS, 'd-guke', 'doc-g1', shift(-300), '08:30', 65, now - 300 * 86400)
    _appointment(db, 'AP-HIS0002', 'p-001', PRIMARY_CAMPUS, 'd-guke', 'doc-g1', shift(-150), '09:30', 65, now - 150 * 86400)
    _appointment(db, 'AP-HIS0003', 'p-001', PRIMARY_CAMPUS, 'd-guke', 'doc-g1', shift(-45), '08:30', 65, now - 45 * 86400)
    _appointment(db, 'AP-HIS0004', 'p-003', PRIMARY_CAMPUS, 'd-xinneike', 'doc-x1', shift(-80), '08:30', 90, now - 80 * 86400)

    # 照护事项：爸爸长期服用降压药（每天 08:00），本周已有两次漏服
    put(db, 'care_item', GID, 'dad-med', {
        'key': 'dad-med', 'member': 'dad', 'type': 'medication', 'title': '氨氯地平 5mg', 'detail': '每日 1 次 · 早上 8 点',
        'clock': '08:00', 'start': shift(-60), 'end': None, 'status': 'active', 'source': '心血管内科长期医嘱',
        'miss_dates': [shift(2), shift(4), shift(9), shift(11)]})
    for offset in range(-6, 1):
        date = shift(offset)
        missed = offset in (-5, -3)
        put(db, 'care_log', GID, f'dad-med:{date}', {'item': 'dad-med', 'member': 'dad', 'date': date,
            'status': 'missed' if missed else 'taken', 'at': democlock.at(date, '08:00') + (0 if missed else 600), 'by': 'seed'})

    # 近几天的家庭群聊天（真实感背景，不触发分析任务）
    lines = [
        (-2, '19:31', 'mom', '今天广场舞跳得久了点，膝盖有点不舒服'),
        (-2, '19:35', 'child', '妈你悠着点，旧伤别又犯了'),
        (-2, '19:36', 'dad', '我盯着她呢，放心😄'),
        (-1, '08:05', None, '林叔叔早～今天的降压药记得吃哦'),
        (-1, '08:20', 'dad', '吃了吃了'),
        (-1, '20:12', 'child', '这周末项目上线回不去了，你们照顾好自己'),
        (-1, '20:15', 'mom', '忙你的，我们好着呢'),
        (0, '18:40', 'dad', '晚饭吃的饺子，你妈包的'),
    ]
    for i, (offset, clock, login, content) in enumerate(lines):
        _message(db, ids[login] if login else 0, content, democlock.at(shift(offset), clock), f'chat-{i}')


def reset(clear_clock=True):
    """清空并重新写入演示数据。保留账号、群成员与模型配置。"""
    from .hospital_simulator import reset_sessions
    reset_sessions()
    with DB() as db:
        old = get(db, 'group', GID, 'settings')
        settings = dict(old.data) if old else {}
        db.execute(text('DELETE FROM messages'))
        db.execute(text('DELETE FROM records'))
        db.execute(text('DELETE FROM memory_fts'))
        db.commit()
    if clear_clock:
        real_today = datetime.now(democlock.TZ).date().isoformat()
        democlock.reset()
        democlock.set_now(democlock.at(real_today, START_CLOCK))
    with DB() as db:
        settings.update({'name': settings.get('name') or '我们一家', 'agent_name': DEFAULT_AGENT_NAME,
                         'prompt': settings.get('prompt') or DEFAULT_PROMPT, 'active': True,
                         'wait_seconds': settings.get('wait_seconds', 30), 'memory_auto': True,
                         'memory_short_days': settings.get('memory_short_days', 7),
                         'memory_review_seconds': settings.get('memory_review_seconds', 21600),
                         'version': settings.get('version', 0) + 1})
        put(db, 'group', GID, 'settings', settings)
        seed(db)
        db.commit()


def autoseed():
    """首次启动（群里还没有任何消息）时自动写入演示数据。"""
    import os
    if os.getenv('DEMO_AUTOSEED', 'true').lower() in ('0', 'false', 'no'):
        return False
    with DB() as db:
        if db.query(Message).filter_by(group_id=GID).first() or get(db, 'demo', GID, 'state'):
            return False
    reset()
    return True
