"""就诊后守护：读取病历 / 药单图片或文字医嘱 → 结构化 → 守护计划卡 → 定时提醒 → 医疗记忆。

- 识图沿用 DeepSeek 接口（DEEPSEEK_BASE_URL / DEEPSEEK_API_KEY），模型名可用 DEEPSEEK_VISION_MODEL 单独指定，
  留空则用 DEEPSEEK_MODEL。识别结果按图片内容哈希缓存（DATA_DIR/vision_cache.json，演示重置不清空），
  同一张图第二次秒出，也不会重复写记忆。
- 红线：只抄写病历上写明的内容，不新增药物、不改剂量、不推断疗程；看不清的字段标“待核对”交给家人确认。
- 没配模型、超时或识别失败时不报错退出：请家人把病历文字发过来，文字医嘱走规则解析。
"""
import asyncio
import hashlib
import json
import os
import re
import time
from datetime import datetime

from . import democlock
from . import hospital_data as H
from .db import DATA, DB, get, put
from .memory import save_memory

VISION_SYSTEM = '''你是家庭就医守护助手“小艺”的病历/药单识别模块，只输出 JSON。
只抄写图片中写明的内容，不推断、不补全、不给医疗建议；看不清或被遮挡的字段填 null，并把字段名写进 uncertain。
doc_type：medical_record（门诊/住院病历）、prescription（处方/药单）、lab_report（化验/检查报告）、other（不是医疗文书）。
输出：{"doc_type":"medical_record|prescription|lab_report|other","confidence":0-1,"patient":{"name":null,"age":null,"gender":null},
"hospital":null,"department":null,"doctor":null,"doctor_title":null,"visit_date":null,"diagnosis":null,"allergies":[],
"medications":[{"name":"药名","spec":"规格","dose":"每次剂量","frequency":"频次原文","route":"用法","days":"疗程原文或null","timing":"饭前/饭后/睡前或null"}],
"follow_up":{"after_days":"如“1周”或null","date":null,"department":null,"doctor":null,"note":null},
"advice":["医嘱/处理意见逐条"],"rehab":["康复训练逐条"],"uncertain":["看不清的字段"],"summary":"一句话概括，不超过40字"}'''

TEXT_SYSTEM = VISION_SYSTEM.replace('病历/药单识别模块', '文字医嘱整理模块').replace('图片中写明', '家人发来的文字中写明')
MEDICAL_HINT = re.compile(r'病历|药单|处方|医嘱|化验|检查|报告|单子|开的药|看看|帮我记|记一下|识别|安排|整理|看完')
TEXT_ORDER_HINT = re.compile(r'医嘱|医生说|医生让|处方|病历|开了|开的药|诊断')
MED_RE = re.compile(r'([一-龥A-Za-z]{2,14}?(?:缓释片|肠溶片|分散片|片|胶囊|颗粒|丸|口服液|滴丸|软膏))\s*[，,、 ]?\s*'
                    r'(?:(?:每次|一次)?\s*([\d.]+\s*(?:mg|g|毫克|克|ml|毫升|片|粒|袋|丸)))?[^。；;\n]{0,24}?'
                    r'(每日|每天|一天|一日|日)\s*([一二两三四1-4])\s*次')
DAYS_RE = re.compile(r'(?:连续|疗程|连吃|吃)\s*([\d一二两三四五六七八九十]+)\s*(天|日|周)')
FOLLOW_RE = re.compile(r'([\d一二两三四五六七八九十]+)\s*(天|日|周|个月)后?[^\d一二两三四五六七八九十，,。；;]{0,6}(复诊|复查|随诊)')
CN_NUM = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
TIMES = {1: ['08:30'], 2: ['08:30', '18:30'], 3: ['08:00', '12:30', '18:30'], 4: ['08:00', '12:00', '17:00', '21:00']}
_CACHE_LOCK = asyncio.Lock()
FIELD_LABELS = {'visit_date': '就诊日期', 'diagnosis': '诊断', 'hospital': '医院', 'department': '科室', 'doctor': '医生', 'doctor_title': '医生职称',
                'patient': '患者信息', 'medications': '处方', 'follow_up': '复诊安排', 'follow_up.date': '复诊日期', 'advice': '医嘱', 'allergies': '过敏史',
                'rehab': '康复', 'days': '疗程', 'dose': '剂量', 'frequency': '频次'}


def C():
    from . import care
    return care


def vision_model():
    return os.getenv('DEEPSEEK_VISION_MODEL') or os.getenv('DEEPSEEK_MODEL', 'deepseek-flash')


def _cache_path():
    return DATA / 'vision_cache.json'


def _cache_get(digest):
    try:
        return json.loads(_cache_path().read_text(encoding='utf-8')).get(digest)
    except (OSError, ValueError):
        return None


async def _cache_put(digest, value):
    async with _CACHE_LOCK:
        path = _cache_path()
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = {}
        data[digest] = value
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        temp.replace(path)


def number(text, default=None):
    if text is None:
        return default
    m = re.search(r'\d+', str(text))
    if m:
        return int(m.group(0))
    for ch in str(text):
        if ch in CN_NUM:
            return CN_NUM[ch]
    return default


def course_days(text):
    """疗程原文 → 天数（“3天”→3，“1周”→7）；没写疗程返回 None（不推断）。"""
    if not text:
        return None
    n = number(text)
    if n is None:
        return None
    return n * 7 if '周' in str(text) else n * 30 if '月' in str(text) else n


def follow_days(follow):
    if not follow:
        return None
    raw = follow.get('after_days') or follow.get('note') or ''
    n = number(raw)
    if n is None:
        return None
    return n * 7 if '周' in str(raw) else n * 30 if '月' in str(raw) else n


def times_of(frequency, timing=None):
    f = str(frequency or '')
    if re.search(r'睡前|qn', f + str(timing or ''), re.I):
        return ['21:00']
    n = 2 if re.search(r'bid|b\.i\.d', f, re.I) else 3 if re.search(r'tid|t\.i\.d', f, re.I) else 1 if re.search(r'qd|q\.d', f, re.I) else None
    if n is None:
        m = re.search(r'(每日|每天|一天|一日|日)\s*([一二两三四1-4])\s*次', f)
        n = number(m.group(2), 1) if m else 1
    return TIMES.get(n, TIMES[1])


async def read_image(agent, path, mime, trace):
    """识图：返回 (结构化结果 或 None, 失败原因, 是否命中缓存)。"""
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    cached = _cache_get(digest)
    if cached:
        await trace.step('tool', '识图结果缓存命中', f"同一张图之前识别过（{cached.get('model')}，{cached.get('ms')}ms），直接复用", 1)
        return cached['result'], None, digest
    if not C().model_ready(agent):
        return None, '还没有配置大模型', digest
    import base64
    from .model import Model
    from .debugging import traced_call
    messages = [{'role': 'system', 'content': VISION_SYSTEM},
                {'role': 'user', 'content': [{'type': 'text', 'text': '请识别这张图片，按要求输出 JSON。'},
                                             {'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,' + base64.b64encode(raw).decode()}}]}]
    timeout = int(os.getenv('VISION_TIMEOUT', '120'))
    extra = {'model_override': vision_model(), 'timeout': timeout} if isinstance(agent.model, Model) else {}
    started = time.monotonic()
    try:
        result = await asyncio.wait_for(traced_call(agent, C().GID, 0, 'care_vision', messages, structured=True, **extra), timeout + 5)
    except asyncio.TimeoutError:
        return None, f'识别超时（超过 {timeout} 秒）', digest
    except Exception as exc:  # noqa: BLE001 - 任何模型异常都降级为请家人发文字
        return None, f'识别失败（{type(exc).__name__}）', digest
    ms = round((time.monotonic() - started) * 1000)
    result = {k: v for k, v in result.items() if not k.startswith('_')}
    await _cache_put(digest, {'result': result, 'model': vision_model(), 'ms': ms, 'at': time.time()})
    await trace.step('llm', f'视觉识别 · {vision_model()}', f"{result.get('doc_type')} · 置信度 {result.get('confidence')} · {result.get('summary') or ''}", ms)
    return result, None, digest


def patient_of(doc, text_, speaker):
    name = ((doc or {}).get('patient') or {}).get('name') or ''
    for login, f in C().FAMILY.items():
        if name and (f['real_name'] in name or name in f['real_name']):
            return login
    slots = C().rule_slots(text_ or '', speaker)
    if slots['patient']:
        return slots['patient']
    return 'mom' if speaker == C().CAREGIVER else speaker


def resolve_place(doc):
    """病历上的医院/科室/医生 → 系统里的医院（用高德别名匹配）、科室、医生。"""
    hosp = H.find_hospital(doc.get('hospital') or '')
    dept = H.department_by_name(doc.get('department') or (doc.get('follow_up') or {}).get('department') or '')
    name = (doc.get('follow_up') or {}).get('doctor') or doc.get('doctor') or ''
    doc_row = H.doctor_by_name(name) if name else None
    if doc_row and dept and doc_row['deptId'] != dept['id']:
        doc_row = None
    campus_id = doc_row['campusId'] if doc_row else (H.campuses_of(hosp['id'])[0]['id'] if hosp else None)
    return hosp, dept, doc_row, campus_id


def plan_rows(doc, start):
    rows = []
    for i, m in enumerate(doc.get('medications') or []):
        if not m.get('name'):
            continue
        times = times_of(m.get('frequency'), m.get('timing'))
        days = course_days(m.get('days'))
        uncertain = days is None
        days = days or 7
        dose = m.get('dose') or m.get('spec') or ''
        rows.append({'key': f'med-{i}', 'type': 'medication', 'title': f"{m['name']} {dose}".strip()[:40],
                     'detail': ' · '.join(x for x in (m.get('frequency'), m.get('route'), m.get('timing')) if x)[:60],
                     'times': times, 'clock': times[0], 'days': days, 'enabled': True,
                     'schedule': f"每天 {'、'.join(times)} · 连续 {days} 天" + ('（疗程未写明，先按 7 天，待核对）' if uncertain else ''),
                     'uncertain': uncertain})
    for i, r in enumerate(doc.get('rehab') or []):
        rows.append({'key': f'rehab-{i}', 'type': 'rehab', 'title': str(r)[:40], 'detail': '按医嘱', 'clock': '19:00', 'days': 14,
                     'enabled': True, 'schedule': '每天 19:00 · 连续 14 天'})
    f = doc.get('follow_up') or {}
    fdays = follow_days(f)
    explicit_date = None
    try:
        explicit_date = datetime.strptime(str(f.get('date')), '%Y-%m-%d').date().isoformat() if f.get('date') else None
    except ValueError:
        explicit_date = None
    if explicit_date or fdays:
        date = explicit_date or democlock.shift_date(start, max(1, min(60, fdays)))
        who = f.get('doctor') or doc.get('doctor') or ''
        rows.append({'key': 'followup', 'type': 'followup', 'title': f"{f.get('department') or doc.get('department') or ''}复诊".strip(),
                     'detail': ((f"{fdays} 天后" if fdays else '按病历日期') + (f"找{who}医生" if who else '') + '复查')[:60], 'date': date, 'clock': '08:30', 'enabled': True,
                     'schedule': f"{democlock.date_label(date)} 08:30" + (f" · {who}医生" if who else '') +
                                 ('（复诊日期按“' + str(f.get('after_days')) + '后”推算，待核对）' if not explicit_date else '')})
    return rows


async def post_plan(agent, doc, *, who, speaker, source_label, extracted_by, source_id, digest, trace):
    hosp, dept, doc_row, campus_id = resolve_place(doc)
    start = democlock.today()
    rows = plan_rows(doc, start)
    if hosp:
        await trace.step('rule', '医院名匹配（高德别名）', f"病历上的“{doc.get('hospital')}” → {hosp['name']}（别名：{'、'.join(hosp['aliases'][:4])}…）")
    if not rows:
        await C().say(f"{C().display(who)}这份{'病历' if doc.get('doc_type') == 'medical_record' else '单子'}上没看到用药和复诊安排，我已经把诊断记到医疗档案里了。",
                      f'care:doc-norows:{digest[:12]}:{source_id}')
        return None
    plan_id = 'DOC-' + digest[:8].upper()
    uncertain = [FIELD_LABELS.get(str(u), str(u)) for u in (doc.get('uncertain') or [])][:6]
    advice = [str(a) for a in (doc.get('advice') or [])][:6]
    title = doc.get('diagnosis') or '就诊后守护'
    await C().say(f"看完了。{C().real_name(who)}这份{'门诊病历' if doc.get('doc_type') == 'medical_record' else '药单'}"
                  f"{'（' + (hosp['name'] if hosp else doc.get('hospital') or '') + (dept['name'] if dept else '') + '）' if hosp or doc.get('hospital') else ''}"
                  f"我整理成了守护计划，{'有 ' + str(len(uncertain)) + ' 处看不清，标了“待核对”，' if uncertain else ''}你确认一下：",
                  f'care:doc-plan-text:{plan_id}:{source_id}')
    card = await C().post_card(f'plan:{plan_id}:{source_id}', 'care_plan', '就诊后守护计划', {
        'appt_id': plan_id, 'patient': who, 'patient_name': C().display(who), 'real_name': C().real_name(who),
        'source': source_label, 'diagnosis': title, 'summary': doc.get('summary'), 'advice': advice, 'items': rows,
        'follow_date': next((r['date'] for r in rows if r['type'] == 'followup'), None), 'start': start,
        'doctor_id': doc_row['id'] if doc_row else None, 'campus_id': campus_id, 'dept_id': dept['id'] if dept else None,
        'doctor': (doc.get('follow_up') or {}).get('doctor') or doc.get('doctor'), 'hospital': hosp['name'] if hosp else doc.get('hospital'),
        'allergies': doc.get('allergies') or [], 'uncertain': uncertain, 'extracted_by': extracted_by, 'simulate_misses': False,
        'days': max([r.get('days', 0) for r in rows if r['type'] != 'followup'] or [7])},
        ['confirm_plan', 'dismiss'])
    await trace.step('card', '推送守护计划卡', f"{len(rows)} 项（{'、'.join(r['title'] for r in rows[:4])}）；家属确认后才创建提醒")
    return card


def remember_document(doc, *, who, speaker, digest, source_id, source_label):
    """B3：识别结果写入结构化医疗档案（来源标注“小艺整理”），同一张图只写一条。"""
    C_ = C()
    uid = C_.ids().get(who)
    meds = '、'.join(f"{m.get('name')}{(' ' + m['dose']) if m.get('dose') else ''}{('，' + m['frequency']) if m.get('frequency') else ''}"
                    for m in doc.get('medications') or [] if m.get('name'))
    hosp = H.find_hospital(doc.get('hospital') or '')
    parts = [f"{C_.real_name(who)}的{'门诊病历' if doc.get('doc_type') == 'medical_record' else '药单'}（{source_label}）",
             f"医院：{hosp['name'] if hosp else doc.get('hospital') or '未写明'}{(' ' + doc['department']) if doc.get('department') else ''}"
             f"{(' ' + doc['doctor'] + '医生') if doc.get('doctor') else ''}"]
    if doc.get('diagnosis'):
        parts.append('诊断：' + str(doc['diagnosis']))
    if meds:
        parts.append('处方：' + meds)
    if (doc.get('follow_up') or {}).get('after_days'):
        parts.append(f"复诊：{doc['follow_up']['after_days']}后" + (f"找{doc['follow_up'].get('doctor')}" if doc['follow_up'].get('doctor') else ''))
    if doc.get('allergies'):
        parts.append('过敏：' + '、'.join(map(str, doc['allergies'])))
    content = '；'.join(parts)[:600]
    with DB() as db:
        save_memory(db, C_.GID, content, [source_id] if source_id else [], [C_.display(who)], key=f'doc-{digest[:16]}', manual=True, explicit=True,
                    domain='medical', profile={'record_type': 'emr', 'hospital': hosp['name'] if hosp else doc.get('hospital'),
                                               'department': doc.get('department'), 'doctor': doc.get('doctor'), 'diagnosis': doc.get('diagnosis'),
                                               'medications': doc.get('medications') or [], 'follow_up': doc.get('follow_up'),
                                               'allergies': doc.get('allergies') or [], 'member_id': uid, 'source': '小艺整理',
                                               'image': digest[:16]},
                    metadata={'subject_ids': [uid], 'category': 'medical', 'origin': 'assistant', 'source_label': source_label},
                    now=democlock.now())
        db.commit()
    return content


def mark_visit_done(who, doc, digest):
    """主线：妈妈刚看完门诊，把她最近一次预约标为已就诊，并把识别出的病历挂到医院“我的预约”里。"""
    pid = C().FAMILY[who]['patient_id']
    appt = C().latest_visit_appt(pid)
    if not appt or appt['date'] > democlock.today():
        return None
    with DB() as db:
        appt = H.get_appt(db, appt['id'])
        appt['status'] = 'completed'
        appt['emr'] = {'hospital': appt.get('hospitalName') or H.place(appt['campusId']), 'campus': appt['campusName'], 'department': appt['deptName'],
                       'doctor': doc.get('doctor') or appt['doctorName'], 'doctor_title': doc.get('doctor_title') or appt['doctorTitle'],
                       'patient': appt['patientName'], 'visit_date': appt['date'], 'complaint': '（见门诊病历照片）',
                       'diagnosis': doc.get('diagnosis') or '', 'exam': '', 'advice': [str(a) for a in doc.get('advice') or []],
                       'medications': doc.get('medications') or [], 'follow_up_days': follow_days(doc.get('follow_up')) or 7,
                       'note': f'由家属上传的病历照片识别整理（{digest[:8]}），演示数据，不构成医疗建议。'}
        H.save_appt(db, appt)
        db.commit()
    return appt


async def handle_images(agent, message, speaker, text_, attachments):
    """群里发来图片：像病历/药单就识别并生成守护计划；明显无关的图片交给通用对话。"""
    if text_ and not MEDICAL_HINT.search(text_):
        return False
    with DB() as db:
        upload = get(db, 'upload', C().GID, attachments[0])
    if not upload:
        return False
    path = DATA / 'uploads' / upload.data['file']
    if not path.exists():
        return False
    trace = C().Trace(f'就诊后守护 · {C().display(speaker)}发来图片', message.id)
    await trace.step('rule', '识别为病历/药单图片', f"“{text_[:30] or '（只发了图片）'}” + {len(attachments)} 张图")
    from .skill_library import load_instructions
    load_instructions('family-aftercare')
    await trace.step('skill', '加载 Skill · family-aftercare', '识图 → 结构化 → 守护计划（待确认）→ 定时提醒 → 写入医疗档案')
    await C().say('收到，我看看这张图，稍等一下～', f'care:doc-ack:{message.id}')
    doc, err, digest = await read_image(agent, path, upload.data['mime'], trace)
    if doc is None:
        await trace.step('rule', '识图不可用 → 请家人发文字', err)
        await C().say(f"这张图我现在看不了（{err}）。可以把病历上的诊断、药名和用法打字发给我，比如“醋氯芬酸片 0.1g 每日2次 吃3天，1周后复诊”，我照样能整理成提醒。",
                      f'care:doc-fail:{message.id}')
        return True
    if doc.get('doc_type') == 'other' or float(doc.get('confidence') or 0) < 0.5:
        await trace.step('rule', '不是病历/药单，不编造字段', f"{doc.get('doc_type')} · 置信度 {doc.get('confidence')} · {doc.get('summary') or ''}")
        await C().say(f"这张图看起来不是病历或药单（{(doc.get('summary') or '没认出医疗内容')[:30]}），我没法从里面整理用药。"
                      f"要是想让我记病历，拍清楚一点再发一次，或者直接把药名和用法打字告诉我。", f'care:doc-other:{message.id}')
        return True
    who = patient_of(doc, text_, speaker)
    source_label = f"{democlock.date_label(democlock.today())}{C().display(speaker)}发的病历照片 · 小艺识图整理"
    with DB() as db:
        r = get(db, 'upload', C().GID, attachments[0])
        r.set({**r.data, 'parsed': {'digest': digest, 'doc_type': doc.get('doc_type'), 'summary': doc.get('summary'), 'patient': who,
                                    'model': vision_model(), 'at': democlock.now(), 'result': doc}})
        db.commit()
    content = remember_document(doc, who=who, speaker=speaker, digest=digest, source_id=message.id, source_label=source_label)
    await trace.step('memory', '写入医疗档案（来源：小艺整理）', content[:160])
    appt = mark_visit_done(who, doc, digest)
    if appt:
        await trace.step('tool', '关联到医院预约记录', f"{appt['id']} 标为已就诊，病历挂到医院“我的预约”")
    await post_plan(agent, doc, who=who, speaker=speaker, source_label=source_label,
                    extracted_by='vision', source_id=message.id, digest=digest, trace=trace)
    return True


def rule_parse_orders(text_):
    meds = []
    for m in MED_RE.finditer(text_):
        tail = text_[m.end():m.end() + 16]
        days = DAYS_RE.search(text_[m.start():m.end()] + tail)
        name = re.split(r'开了|开的|服用|医嘱|处方|还有|[:：，,、]', m.group(1))[-1]
        meds.append({'name': name, 'dose': (m.group(2) or '').replace(' ', ''), 'frequency': f"{m.group(3)}{m.group(4)}次",
                     'route': None, 'days': (days.group(1) + days.group(2)) if days else None, 'timing': '饭后' if '饭后' in tail else None})
    f = FOLLOW_RE.search(text_)
    diag = re.search(r'诊断[:：是为]?\s*([^，。；;\n]{2,30})', text_)
    return {'doc_type': 'prescription', 'confidence': 0.8, 'patient': {}, 'hospital': (H.find_hospital(text_) or {}).get('name'),
            'department': None, 'doctor': None, 'diagnosis': diag.group(1) if diag else None, 'allergies': [],
            'medications': meds, 'follow_up': {'after_days': f.group(1) + f.group(2) if f else None, 'note': f.group(0) if f else None},
            'advice': [], 'rehab': [], 'uncertain': [], 'summary': '家人发来的文字医嘱'}


async def handle_text_orders(agent, message, speaker, text_):
    """文字医嘱（家人打字或转发）：有药名 + 频次时，整理成守护计划。"""
    if not TEXT_ORDER_HINT.search(text_) or not MED_RE.search(text_):
        return False
    from .skill_library import load_instructions
    load_instructions('family-aftercare')
    trace = C().Trace(f'就诊后守护 · {C().display(speaker)}发来文字医嘱', message.id)
    await trace.step('skill', '加载 Skill · family-aftercare', '文字医嘱 → 结构化 → 守护计划（待确认）→ 定时提醒')
    await trace.step('rule', '识别为文字医嘱', f'“{text_[:40]}”')
    doc = rule_parse_orders(text_)
    timeout = int(os.getenv('CARE_LLM_TIMEOUT', '30'))
    result, err = await C().llm_json(agent, 'care_text_orders', TEXT_SYSTEM, {'text': text_}, timeout=timeout)
    if result and isinstance(result.get('medications'), list) and result['medications']:
        doc = {**doc, **{k: v for k, v in result.items() if v not in (None, [], '') and not k.startswith('_')}}
        await trace.step('llm', f'大模型整理医嘱 · {C().model_name()}', '、'.join(str(m.get('name')) for m in doc['medications'][:4]))
    else:
        await trace.step('rule', '医嘱结构化（规则）', err or '模型输出缺少用药，改用规则解析')
    who = patient_of(doc, text_, speaker)
    digest = hashlib.sha256(text_.encode()).hexdigest()
    source_label = f"{democlock.date_label(democlock.today())}{C().display(speaker)}发的文字医嘱 · 小艺整理"
    content = remember_document(doc, who=who, speaker=speaker, digest=digest, source_id=message.id, source_label=source_label)
    await trace.step('memory', '写入医疗档案（来源：小艺整理）', content[:160])
    await post_plan(agent, doc, who=who, speaker=speaker, source_label=source_label,
                    extracted_by='llm' if result else 'rule', source_id=message.id, digest=digest, trace=trace)
    return True
