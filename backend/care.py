"""家庭就医守护编排（“家人帮”主线）。

把“一句话挂号 → 锁号 → 支付 → 就诊后守护 → 用药依从 → 复诊简报”串成可演示的闭环：
- 规则保底、大模型增强：槽位抽取、需求判断、病历结构化、简报问题优先请大模型完成，
  模型未配置、超时或输出不合规时用规则兜底，演示不中断。
- 模型负责想、代码负责做：锁号由家人点确认卡后由浏览器执行器提交；支付只能本人在收银台完成；
  急症识别只走规则，不依赖模型。
- 每一步写入思考轨迹（care_trace），前端“小艺在想什么”实时展示。
"""
import asyncio
import json
import math
import os
import re
import time
import uuid
from datetime import datetime

from fastapi import Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import democlock
from . import hospital_data as H
from .care_seed import FAMILY, CAREGIVER, ELDERS, HOME, GID, day0
from .db import DB, Message, User, get, put, records
from .memory import save_memory, list_profile

_AGENT = None
_last_tick = 0.0
_running_briefings = set()


def set_agent(agent):
    global _AGENT
    _AGENT = agent


def agent_ref():
    if _AGENT is None:
        from .app import agent
        return agent
    return _AGENT


# ---------------------------------------------------------------- 基础工具
def ids():
    with DB() as db:
        return {u.username: u.id for u in db.query(User).all()}


def login_of(user_id):
    return next((k for k, v in ids().items() if v == user_id), None)


def display(login):
    return FAMILY.get(login, {}).get('name', '家人')


def real_name(login):
    return FAMILY.get(login, {}).get('real_name', display(login))


def model_ready(agent):
    from .model import Model
    return bool(os.getenv('DEEPSEEK_API_KEY')) or not isinstance(agent.model, Model)


async def broadcast(event):
    agent = agent_ref()
    await agent.broadcast(GID, event)


class Trace:
    """一次编排的思考轨迹：每一步记录类型、标题、细节与耗时。"""

    def __init__(self, title, source=None):
        self.turn = uuid.uuid4().hex[:10]
        self.title = title
        self.source = source
        self.n = 0
        self.mark = time.monotonic()

    async def step(self, kind, label, detail='', ms=None):
        self.n += 1
        elapsed = round((time.monotonic() - self.mark) * 1000) if ms is None else ms
        self.mark = time.monotonic()
        with DB() as db:
            put(db, 'care_trace', GID, f'{self.turn}:{self.n:02d}', {
                'turn': self.turn, 'title': self.title, 'source': self.source, 'n': self.n, 'kind': kind,
                'label': label, 'detail': str(detail)[:400], 'ms': elapsed, 'at': democlock.now(), 'real_at': time.time()})
            db.commit()
        await broadcast({'type': 'care_trace', 'turn': self.turn})


async def say(text, key):
    return await agent_ref().send(GID, text, key)


async def post_card(key, ctype, title, data, actions, status='active'):
    from .cards import save_card, notify
    with DB() as db:
        card = save_card(db, GID, key, {'title': title, 'care': {'type': ctype, 'data': data, 'actions': actions}},
                         kind='care', status=status)
        db.commit()
    await notify(GID, card)
    await broadcast({'type': 'message', 'id': card['message_id']})
    return card


async def update_card(key, *, status=None, data=None, actions=None, title=None):
    from .cards import notify
    with DB() as db:
        r = get(db, 'card', GID, key)
        if not r:
            return None
        card = r.data
        if data:
            card['care']['data'].update(data)
        if actions is not None:
            card['care']['actions'] = actions
        if status:
            card['status'] = status
        if title:
            card['title'] = title
        card['version'] += 1
        put(db, 'card', GID, key, card)
        db.commit()
    await notify(GID, card)
    return card


def card_data(key):
    with DB() as db:
        r = get(db, 'card', GID, key)
        return r.data if r else None


async def llm_json(agent, phase, system, payload, timeout=18):
    """结构化调用大模型；未配置/超时/格式不对时返回 (None, 原因)，由调用方走规则兜底。"""
    if not model_ready(agent):
        return None, '模型未配置，使用规则兜底'
    from .debugging import traced_call
    try:
        result = await asyncio.wait_for(traced_call(agent, GID, 0, phase, [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}], structured=True), timeout)
        return result, None
    except asyncio.TimeoutError:
        return None, '模型超时，使用规则兜底'
    except Exception as exc:  # noqa: BLE001 - 任何模型异常都降级为规则
        return None, f'模型不可用（{type(exc).__name__}），使用规则兜底'


def model_name():
    return os.getenv('DEEPSEEK_MODEL', 'deepseek-flash')


# ---------------------------------------------------------------- 规则：急症 / 挂号 / 症状 / 打卡
RED_FLAGS = [
    (re.compile(r'(胸口|胸|心口).{0,6}(疼|痛|闷|压|紧).{0,12}(喘不上|喘不过|呼吸困难|憋气|透不过气|出冷汗|大汗)|'
                r'(喘不上|喘不过|呼吸困难|憋气).{0,12}(胸口|胸|心口).{0,6}(疼|痛|闷)'), '胸痛伴呼吸困难，属于心脏急症信号'),
    (re.compile(r'嘴歪|口角歪|说话不清|口齿不清|半边.{0,4}(麻|没力|不能动|动不了)|一边.{0,6}(没力气|麻|动不了)|一侧.{0,4}(无力|麻木)'), '口角歪斜/单侧无力，可能是卒中信号'),
    (re.compile(r'叫不醒|昏迷|晕倒了|不省人事|抽搐'), '意识不清或抽搐，属于急症'),
    (re.compile(r'大出血|血止不住|吐血|咳血'), '大量出血，属于急症'),
    (re.compile(r'头.{0,3}(疼|痛)得.{0,4}(裂|受不了|从没)|剧烈头痛'), '突发剧烈头痛，需要排除急症'),
]
BOOKING_RE = re.compile(r'挂.{0,10}号|约.{0,10}号|挂个|预约.{0,12}(医生|门诊|号|专家|复诊|科)|挂(骨科|心内|专家|门诊)|看.{0,8}号')
NEGATION_RE = re.compile(r'(不要|不用|别|先别|不想|不必)(帮|给)?.{0,4}(挂|约|预约)|取消')
SYMPTOM_RE = re.compile(r'疼|痛|酸|胀|麻|晕|咳|喘|不舒服|难受|发烧|发热|没力气|睡不着|心慌|胸闷|拉肚子|肿')
CHECKIN_RE = re.compile(r'(药.{0,4}(吃了|吃过|吃完|已吃))|(吃(过|了|完)药)|(已经吃了)')
SYMPTOMS = {
    '膝盖': '骨科', '膝': '骨科', '关节': '骨科', '腰': '骨科', '腿': '骨科', '颈椎': '骨科', '扭': '骨科', '骨': '骨科',
    '咳': '呼吸内科', '喘': '呼吸内科', '心慌': '心血管内科', '胸闷': '心血管内科', '血压': '心血管内科',
    '胃': '消化内科', '拉肚子': '消化内科', '腹泻': '消化内科', '头晕': '神经内科', '头疼': '神经内科', '头痛': '神经内科',
    '失眠': '神经内科', '睡不着': '神经内科', '眼': '眼科', '牙': '口腔科', '皮肤': '皮肤科', '痒': '皮肤科',
}
PATIENT_PATTERNS = [
    ('mom', re.compile(r'我妈|妈妈|老妈|俺妈|母亲|王秀兰|王阿姨|外婆|姥姥|奶奶')),
    ('dad', re.compile(r'我爸|爸爸|老爸|俺爸|父亲|林志强|林叔|外公|姥爷|爷爷')),
]


def red_flag(text):
    for pattern, reason in RED_FLAGS:
        if pattern.search(text):
            return reason
    return None


def symptom_of(text):
    for word, dept in SYMPTOMS.items():
        if word in text:
            return word, dept
    return None, None


def parse_date(text, base=None):
    base = base or democlock.today()
    if '大后天' in text:
        return democlock.shift_date(base, 3)
    if '后天' in text:
        return democlock.shift_date(base, 2)
    if '明天' in text or '明早' in text or '明儿' in text:
        return democlock.shift_date(base, 1)
    if '今天' in text or '今儿' in text:
        return base
    m = re.search(r'(?:周|星期|礼拜)([一二三四五六日天])', text)
    if m:
        target = '一二三四五六日天'.index(m.group(1))
        target = 6 if target == 7 else target
        weekday = democlock.local(democlock.at(base)).weekday()
        return democlock.shift_date(base, (target - weekday) % 7 or 7)
    m = re.search(r'(\d{1,2})月(\d{1,2})[日号]', text) or re.search(r'(\d{1,2})[号日]', text)
    if m:
        year = int(base[:4])
        month, dayn = (int(m.group(1)), int(m.group(2))) if m.lastindex == 2 else (int(base[5:7]), int(m.group(1)))
        try:
            value = datetime(year, month, dayn).date().isoformat()
        except ValueError:
            return None
        # 已经过去的日期按明年/下个月理解不可靠，直接交给默认值
        return value if value >= base else None
    return None


def parse_session(text):
    if re.search(r'下午|午后|晚', text):
        return 'afternoon'
    if re.search(r'上午|早上|早点|明早|一早', text):
        return 'morning'
    return None


def rule_slots(text, speaker):
    patient = next((login for login, p in PATIENT_PATTERNS if p.search(text)), None)
    if patient is None and speaker in ELDERS and re.search(r'帮我|给我|我想|我要', text):
        patient = speaker
    dept = next((d['name'] for d in sorted(H.catalog()['departments'], key=lambda d: -len(d['name'])) if d['name'] in text), None)
    if dept is None:
        dept = {'心内': '心血管内科', '骨': '骨科'}.get(next((k for k in ('心内', '骨') if k + '科' in text), ''), None)
    symptom, symptom_dept = symptom_of(text)
    return {'patient': patient, 'department': dept or symptom_dept, 'symptom': symptom,
            'date': parse_date(text), 'session': parse_session(text)}


def recent_symptom(login, hours=48):
    """从该成员最近的聊天里找症状（例如妈妈前面说过膝盖酸）。"""
    uid = ids().get(login)
    since = democlock.now() - hours * 3600
    with DB() as db:
        rows = db.query(Message).filter(Message.group_id == GID, Message.user_id == uid, Message.created >= since).order_by(Message.id.desc()).limit(10).all()
    for m in rows:
        word, dept = symptom_of(m.content)
        if dept:
            return word, dept, m.content
    return None, None, None


def profile_of(login):
    uid = ids().get(login)
    with DB() as db:
        return list_profile(db, GID, uid, 'medical', now=democlock.now()) if uid else []


def familiar_doctor(login, dept_id):
    for p in profile_of(login):
        prof = p.get('profile') or {}
        doc = H.doctor(prof.get('doctor_id', '')) or H.doctor_by_name(prof.get('doctor', ''))
        if doc and doc['deptId'] == dept_id:
            return doc
    pid = FAMILY.get(login, {}).get('patient_id')
    done = [a for a in H.appointments() if a.get('patientId') == pid and a.get('deptId') == dept_id and a.get('status') == 'completed']
    return H.doctor(done[-1]['doctorId']) if done else None


def prefers_session(login):
    with DB() as db:
        from .memory import list_memories
        for m in list_memories(db, GID, None, democlock.now()):
            if FAMILY.get(login, {}).get('name', '') in ''.join(m.get('subjects', [])) and '上午' in m['content']:
                return 'morning'
    return None


# ---------------------------------------------------------------- 地图：距离 / 天气 / 附近急诊（高德 MCP，失败则估算）
_DIST_CACHE = {}
_WEATHER_CACHE = {}
_ER_CACHE = {}


def haversine(lng1, lat1, lng2, lat2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


async def amap(name, arguments, timeout=15):
    if not os.getenv('AMAP_MCP_URL'):
        return None
    from .amap_mcp import amap_mcp
    try:
        result = await asyncio.wait_for(amap_mcp(None, {'action': 'call', 'name': name, 'arguments': arguments}), timeout)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(result, dict) or 'error' in result:
        return None
    try:
        return json.loads(result.get('content') or '{}')
    except ValueError:
        return None


def _estimate(camp):
    km = haversine(HOME['lng'], HOME['lat'], camp['lng'], camp['lat']) * 1.35
    return (km, max(3, round(km / 22 * 60)), '直线距离估算')


async def fetch_distances(campus_ids):
    """调用高德驾车距离；院区与家的位置固定，结果永久缓存。"""
    todo = [c for c in campus_ids if c not in _DIST_CACHE or _DIST_CACHE[c][2] != '高德地图']
    if not todo:
        return 0
    started = time.monotonic()
    camps = [H.campus(c) for c in todo]
    data = await amap('maps_distance', {'origins': '|'.join(f"{c['lng']},{c['lat']}" for c in camps),
                                        'destination': f"{HOME['lng']},{HOME['lat']}", 'type': '1'})
    results = (data or {}).get('results') or []
    for i, camp in enumerate(camps):
        row = next((r for r in results if str(r.get('origin_id')) == str(i + 1)), None)
        try:
            _DIST_CACHE[camp['id']] = (float(row['distance']) / 1000, max(1, round(float(row['duration']) / 60)), '高德地图')
        except (TypeError, KeyError, ValueError):
            _DIST_CACHE.setdefault(camp['id'], _estimate(camp))
    return round((time.monotonic() - started) * 1000)


async def distances(campus_ids, trace):
    cached = all(c in _DIST_CACHE and _DIST_CACHE[c][2] == '高德地图' for c in campus_ids)
    ms = 0 if cached else await fetch_distances(campus_ids)
    for c in campus_ids:
        _DIST_CACHE.setdefault(c, _estimate(H.campus(c)))
    source = _DIST_CACHE[campus_ids[0]][2]
    label = '高德地图 · maps_distance' + ('（启动时已预取）' if cached else '')
    await trace.step('tool', label if source == '高德地图' else '距离估算（高德未配置或不可用）', '；'.join(
        f"家 → {H.campus(c)['name']} {_DIST_CACHE[c][0]:.1f}km / 驾车约{_DIST_CACHE[c][1]}分钟" for c in campus_ids), ms or 1)
    return {c: _DIST_CACHE[c] for c in campus_ids}


async def fetch_weather():
    data = await amap('maps_weather', {'city': HOME['city']})
    try:
        today = (data or {}).get('forecasts', [])[0]
        info = {'city': data.get('city', HOME['city']), 'weather': today.get('dayweather'),
                'temp': f"{today.get('nighttemp')}~{today.get('daytemp')}℃"}
    except (IndexError, AttributeError, TypeError):
        return None
    _WEATHER_CACHE[HOME['city']] = (time.time(), info)
    return info


async def weather(trace):
    cached = _WEATHER_CACHE.get(HOME['city'])
    started = time.monotonic()
    info = cached[1] if cached and time.time() - cached[0] < 3 * 3600 else await fetch_weather()
    if info:
        await trace.step('tool', '高德地图 · maps_weather' + ('（缓存）' if cached else ''), f"{info['city']}今天{info['weather']}，{info['temp']}",
                         round((time.monotonic() - started) * 1000) or 1)
    else:
        await trace.step('tool', '高德地图 · 天气', '未配置或查询失败，跳过天气关联')
    return info


ER_EXCLUDE = re.compile(r'新生儿|儿童|妇幼|妇产|口腔|眼科|中医|社区|卫生服务|卫生院|诊所|门诊部|药房|体检|康复|美容|宠物|导医')


async def fetch_er():
    """周边检索综合医院（高德类型码 090101），排除专科/社区机构，取第一家作为就近急诊。"""
    for keywords in ('综合医院', '医院'):
        data = await amap('maps_around_search', {'keywords': keywords, 'location': f"{HOME['lng']},{HOME['lat']}", 'radius': '5000'})
        pois = [p for p in (data or {}).get('pois') or [] if str(p.get('typecode', '')).startswith('090101') and not ER_EXCLUDE.search(p.get('name', ''))]
        if pois:
            poi = pois[0]
            _ER_CACHE['home'] = {'name': poi.get('name'), 'address': poi.get('address') or '', 'source': '高德地图周边检索（综合医院）'}
            break
    return _ER_CACHE.get('home')


async def nearest_er(trace):
    started = time.monotonic()
    er = _ER_CACHE.get('home') or await fetch_er()
    if er:
        await trace.step('tool', '高德地图 · maps_around_search', f"家附近急诊：{er['name']}（{er['address'] or '地址见地图'}）",
                         round((time.monotonic() - started) * 1000) or 1)
        return er
    camp = H.campus('c-main')
    km = _DIST_CACHE.get('c-main', _estimate(camp))[0]
    await trace.step('tool', '附近急诊（本地兜底）', f"市第一人民医院总院急诊科 约{km:.1f}km")
    return {'name': '市第一人民医院总院 · 急诊科', 'address': camp['address'], 'distance_km': round(km, 1), 'source': '演示数据'}


async def warmup():
    """启动/重置后在后台预取高德数据（距离、天气、附近急诊），演示时直接命中缓存。"""
    if not os.getenv('AMAP_MCP_URL'):
        return
    try:
        await asyncio.gather(fetch_distances([c['id'] for c in H.catalog()['campuses']]), fetch_weather(), fetch_er())
    except Exception:  # noqa: BLE001 - 预取失败时演示中实时查询或估算
        pass


# ---------------------------------------------------------------- 号源排序
WEIGHTS = {'distance': 0.45, 'familiar': 0.30, 'continuity': 0.15, 'title': 0.10}
TITLE_SCORE = {'主任医师': 1.0, '副主任医师': 0.8, '主治医师': 0.6}


def session_label(session):
    return '上午' if session == 'morning' else '下午'


def option_from_slot(s, dist, visits, fam_doc, rank_note=''):
    doc, camp = H.doctor(s['doctorId']), H.campus(s['campusId'])
    km, minutes, source = dist
    parts = {
        'distance': round(max(0.0, 1 - km / 10), 3),
        'familiar': round(min(1.0, 0.4 + 0.2 * visits) if visits else 0.0, 3),
        'continuity': 1.0 if fam_doc and doc['id'] == fam_doc['id'] else 0.0,
        'title': TITLE_SCORE.get(doc['title'], 0.6),
    }
    score = round(100 * sum(WEIGHTS[k] * v for k, v in parts.items()))
    reasons = [f'{km:.1f} 公里 · 驾车约 {minutes} 分钟']
    reasons.append(f'去过 {visits} 次，病历都在这' if visits else '之前没来过这个院区')
    if parts['continuity']:
        reasons.append(f'上次就是{doc["name"]}医生看的，熟悉病情')
    reasons.append(f"{s['startTime']} 还剩 {s['remaining']} 个号")
    return {'id': s['id'], 'available': True, 'slot_id': s['id'], 'campus_id': camp['id'], 'campus': camp['name'],
            'doctor_id': doc['id'], 'doctor': doc['name'], 'title': doc['title'], 'date': s['date'],
            'date_label': democlock.date_label(s['date']), 'session': s['session'], 'time': s['startTime'],
            'fee': s['price'], 'remaining': s['remaining'], 'distance_km': round(km, 1), 'eta_min': minutes,
            'distance_source': source, 'visits': visits, 'score': score, 'score_parts': parts, 'reasons': reasons,
            'note': rank_note, 'needs_approval': s['price'] > H.APPROVAL_THRESHOLD}


def pick_slot(avail, fam_doc):
    if fam_doc:
        mine = [s for s in avail if s['doctorId'] == fam_doc['id']]
        if mine:
            return sorted(mine, key=lambda s: (s['startTime'] != '08:30', s['startTime']))[0]
    return sorted(avail, key=lambda s: (-TITLE_SCORE.get(H.doctor(s['doctorId'])['title'], 0.5), s['startTime']))[0]


async def build_options(login, dept_id, date, session, trace):
    dept = H.department(dept_id)
    pid = FAMILY[login]['patient_id']
    fam_doc = familiar_doctor(login, dept_id)
    dists = await distances(dept['campusIds'], trace)
    started = time.monotonic()
    available, blocked, scanned = [], [], 0
    for cid in dept['campusIds']:
        slots = H.find_slots(dept_id, date, session, cid)
        scanned += len(slots)
        avail = [s for s in slots if s['status'] == 'available']
        visits = H.history_count(pid, cid)
        if not avail:
            km, minutes, source = dists[cid]
            blocked.append({'id': 'none-' + cid, 'available': False, 'campus_id': cid, 'campus': H.campus(cid)['name'],
                            'distance_km': round(km, 1), 'eta_min': minutes, 'distance_source': source, 'visits': visits,
                            'date_label': democlock.date_label(date), 'session': session,
                            'note': f"离家最近，但{democlock.date_label(date)}{session_label(session)}{dept['name']}已约满",
                            'reasons': [f'{km:.1f} 公里 · 驾车约 {minutes} 分钟', f"{session_label(session)}号源 0"]})
            continue
        best = pick_slot(avail, fam_doc)
        available.append(option_from_slot(best, dists[cid], visits, fam_doc))
        others = [s for s in avail if s['doctorId'] != best['doctorId']]
        if others:
            alt = sorted(others, key=lambda s: (s['price'], s['startTime']))[0]
            available.append(option_from_slot(alt, dists[cid], visits, fam_doc, '费用更低的选择'))
    available.sort(key=lambda o: -o['score'])
    available = available[:3]
    for i, o in enumerate(available):
        o['rank'] = i + 1
    # 比推荐项更近却没号的院区作为“对比项”，说明为什么没选它
    best_km = available[0]['distance_km'] if available else 99
    compare = [b for b in blocked if b['distance_km'] <= best_km + 0.01] or blocked[:1]
    await trace.step('tool', '查询号源 · 市第一人民医院预约平台', f"{dept['name']} {democlock.date_label(date)}{session_label(session)}："
                     f"扫描 {scanned} 个号源，可约 {len(available)} 个方案，约满 {len(blocked)} 个院区", round((time.monotonic() - started) * 1000))
    if available:
        top = available[0]
        await trace.step('rule', '多因子排序（代码打分，结果可复现）', f"①{top['campus']}·{top['doctor']} {top['score']}分 = 距离{WEIGHTS['distance']:.0%}×{top['score_parts']['distance']:.2f} + "
                         f"熟悉度{WEIGHTS['familiar']:.0%}×{top['score_parts']['familiar']:.2f} + 医生连续性{WEIGHTS['continuity']:.0%}×{top['score_parts']['continuity']:.0f} + 职称{WEIGHTS['title']:.0%}×{top['score_parts']['title']:.1f}")
    return available, compare, fam_doc


# ---------------------------------------------------------------- 主入口：群消息
async def on_message(agent, gid, message):
    """就医场景的快速通道。返回 True 表示已由就医编排接管（不再走通用回复）。"""
    if gid != GID or message.user_id == 0:
        return False
    text_ = (message.content or '').strip()
    if not text_ or text_.startswith('【演示】'):
        return False
    speaker = login_of(message.user_id)
    if speaker not in FAMILY:
        return False
    set_agent(agent)
    reason = red_flag(text_)
    if reason:
        await handle_emergency(message, speaker, text_, reason)
        return True
    if speaker in ELDERS and CHECKIN_RE.search(text_) and await handle_checkin_text(message, speaker):
        return True
    medical = re.search(r'挂.{0,10}号', text_) or re.search(r'医院|医生|门诊|科|复诊|专家|看病|号源', text_)
    if BOOKING_RE.search(text_) and medical and not NEGATION_RE.search(text_):
        await handle_booking_request(agent, message.user_id, text_, source=message.id, speaker=speaker)
        return True
    if speaker in ELDERS and SYMPTOM_RE.search(text_) and symptom_of(text_)[1]:
        return await handle_need_hint(agent, message, speaker, text_)
    return False


# ---------------------------------------------------------------- 主动发现：长辈说不舒服
HINT_SYSTEM = '''你是家庭就医守护助手“小艺”的需求判断模块，只输出 JSON。
判断长辈这句话是否是身体不适、值得提醒照护人（子女）帮忙看医生。不要诊断疾病，不要推荐药物。
输出：{"is_health_need":true/false,"symptom":"简短症状","department":"建议科室（从给定科室中选）","hint":"给照护人的一句话提醒，口语、温暖、不超过45字，结尾问要不要帮看明天的号"}'''


async def handle_need_hint(agent, message, speaker, text_):
    now = democlock.now()
    with DB() as db:
        last = get(db, 'care_hint', GID, speaker)
        if last and now - last.data.get('at', 0) < 2 * 3600:
            return False
        put(db, 'care_hint', GID, speaker, {'at': now, 'source': message.id})
        db.commit()
    trace = Trace(f'主动关怀 · {display(speaker)}说不舒服', message.id)
    word, dept_name = symptom_of(text_)
    await trace.step('rule', '旁听群聊：长辈提到身体不适（未@小艺）', f'“{text_[:40]}” → 症状关键词「{word}」')
    history = [p['content'] for p in profile_of(speaker)][:3]
    if history:
        await trace.step('memory', f'读取医疗档案 · {real_name(speaker)}', '；'.join(history))
    wx = await weather(trace) if re.search(r'阴|雨|变天|潮|冷|湿', text_) or dept_name == '骨科' else None
    names = [d['name'] for d in H.catalog()['departments']]
    result, err = await llm_json(agent, 'care_hint', HINT_SYSTEM, {
        'speaker': f'{display(speaker)}（{real_name(speaker)}，{FAMILY[speaker]["age"]}岁）', 'message': text_,
        'medical_history': history, 'weather': wx, 'departments': names, 'caregiver': display(CAREGIVER)})
    hint = None
    if result and result.get('is_health_need') is not False:
        if result.get('department') in names:
            dept_name = result['department']
        hint = str(result.get('hint') or '').strip()[:80] or None
        await trace.step('llm', f'大模型判断需求 · {model_name()}', f"症状：{result.get('symptom') or word} → 建议{dept_name}")
    else:
        await trace.step('rule', '需求判断（规则）', err or '模型认为不需要提醒，按规则保守提醒一次')
    weather_part = f"，{wx['city']}今天{wx['weather']}" if wx and wx.get('weather') else ''
    hint = hint or f'{display(CAREGIVER)}，{display(speaker)}说{word}不舒服{weather_part}，可能是旧伤反应。要我帮她看看明天上午{dept_name}的号吗？'
    tomorrow = democlock.shift_date(democlock.today(), 1)
    session = prefers_session(speaker) or 'morning'
    await say(hint, f'care:hint:{message.id}')
    await post_card(f'hint:{message.id}', 'need_hint', f'要帮{display(speaker)}看看{dept_name}的号吗？', {
        'member': speaker, 'member_name': display(speaker), 'real_name': real_name(speaker), 'symptom': word,
        'quote': text_[:60], 'department': dept_name, 'date': tomorrow, 'date_label': democlock.date_label(tomorrow),
        'session': session, 'weather': wx, 'history': history[:2], 'for': CAREGIVER}, ['accept', 'dismiss'])
    await trace.step('card', '推送「小艺建议」卡给照护人', f'{display(CAREGIVER)}点「好的」即可进入一句话挂号')
    return True


# ---------------------------------------------------------------- 一句话挂号
BOOKING_SYSTEM = '''你是家庭就医守护助手“小艺”的挂号理解模块，只输出 JSON，不输出其他文字。
根据家庭成员名单、医疗档案和最新消息，理解这次要给谁挂什么科、哪天、上午还是下午。
规则：就诊人只能是 mom/dad/child 之一；科室必须从 departments 中选择；日期用 YYYY-MM-DD，today 已给出；
信息不明确时优先用医疗档案和偏好补全（例如膝盖旧伤→骨科、偏好上午），实在无法确定填 null。不诊断、不推荐药物。
输出：{"patient":"mom/dad/child/null","department":"科室名/null","date":"YYYY-MM-DD/null","session":"morning/afternoon/null",
"symptom":"简短症状/null","reply":"给家人的一句话回复，口语、温暖、不超过40字，说明你按什么去找号"}'''


async def handle_booking_request(agent, user_id, text_, *, source=None, speaker=None, preset=None, trace=None):
    speaker = speaker or login_of(user_id)
    trace = trace or Trace('一句话挂号', source)
    await trace.step('rule', '意图识别：挂号请求', f'“{text_[:40]}”' if text_ else '来自「小艺建议」卡')
    from .skill_library import load_instructions
    skill = load_instructions('family-appointment')
    await trace.step('skill', '加载 Skill · family-appointment', '门诊预约方法：症状→科室对照、补全四要素、50 元授权规则')
    slots = {**rule_slots(text_ or '', speaker), **{k: v for k, v in (preset or {}).items() if v}}
    await trace.step('rule', '规则抽取槽位', '，'.join(f'{k}={v}' for k, v in slots.items() if v) or '未抽到明确槽位')
    reply = None
    if not preset:
        names = [d['name'] for d in H.catalog()['departments']]
        result, err = await llm_json(agent, 'care_booking', BOOKING_SYSTEM + '\n\n可参考的挂号技能说明（节选）：\n' + skill['instructions'][:1400], {
            'today': democlock.today(), 'now': democlock.label(), 'speaker': speaker, 'message': text_,
            'family': {k: {'name': v['name'], 'real_name': v['real_name'], 'age': v['age'], 'conditions': v['conditions']} for k, v in FAMILY.items()},
            'medical_profile': {k: [p['content'] for p in profile_of(k)] for k in ELDERS}, 'departments': names})
        if result:
            if result.get('patient') in FAMILY and not slots['patient']:
                slots['patient'] = result['patient']
            if result.get('department') in names and not slots['department']:
                slots['department'] = result['department']
            if isinstance(result.get('date'), str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', result['date']) and not slots['date']:
                slots['date'] = result['date']
            if result.get('session') in ('morning', 'afternoon') and not slots['session']:
                slots['session'] = result['session']
            reply = str(result.get('reply') or '').strip()[:80] or None
            await trace.step('llm', f'大模型理解请求 · {model_name()}', '，'.join(f'{k}={result.get(k)}' for k in ('patient', 'department', 'date', 'session') if result.get(k)))
        else:
            await trace.step('rule', '大模型理解（跳过）', err)
    patient = slots['patient']
    if not patient:
        word, dept_name, quote = None, None, None
        for login in ELDERS:
            word, dept_name, quote = recent_symptom(login)
            if dept_name:
                patient = login
                await trace.step('memory', '结合上下文认人', f'{display(login)}刚说过“{quote[:20]}”，判断是给{display(login)}挂号')
                break
    if not patient:
        await say('这次是给妈妈还是爸爸挂号呀？说一声我就去找号。', f'care:ask:{source or uuid.uuid4().hex}')
        await trace.step('rule', '缺少就诊人，追问一次', '最多追问 1 次，不让家人填表')
        return None
    dept_name = slots['department']
    if not dept_name:
        word, dept_name, quote = recent_symptom(patient)
        if dept_name:
            await trace.step('memory', '结合近况补全科室', f'{display(patient)}最近说“{quote[:20]}” → {dept_name}')
    if not dept_name and FAMILY[patient].get('dept'):
        dept_name = H.department(FAMILY[patient]['dept'])['name']
        await trace.step('memory', '用医疗档案补全科室', f"{real_name(patient)}：{'、'.join(FAMILY[patient]['conditions'])} → {dept_name}")
    dept = H.department_by_name(dept_name or '')
    if not dept:
        await say(f'{display(patient)}是哪里不舒服呀？告诉我症状，我来对应科室。', f'care:ask-dept:{source or uuid.uuid4().hex}')
        return None
    date = slots['date'] or democlock.shift_date(democlock.today(), 1)
    session = slots['session'] or prefers_session(patient) or 'morning'
    if not slots['session']:
        await trace.step('memory', '用偏好补全时段', f"{display(patient)}{'上午精神好，喜欢约上午' if session == 'morning' else '默认上午'}")
    profile = profile_of(patient)
    if profile:
        await trace.step('tool', f'medical_profile({real_name(patient)})', '；'.join(p['content'] for p in profile[:3]))
    options, compare, fam_doc = await build_options(patient, dept['id'], date, session, trace)
    if not options:
        await say(f'{democlock.date_label(date)}{session_label(session)}{dept["name"]}都约满了，我再看看后一天的号。', f'care:full:{source}:{date}')
        return await handle_booking_request(agent, user_id, '', source=source, speaker=speaker, trace=trace,
                                            preset={'patient': patient, 'department': dept['name'], 'date': democlock.shift_date(date, 1), 'session': session})
    top = options[0]
    reply = reply or (f"好，{display(patient)}{'膝盖旧伤' if dept['id'] == 'd-guke' and patient == 'mom' else ''}的事我来办。"
                      f"按{'上次看的' + fam_doc['name'] + '医生' if fam_doc else '距离和医生职称'}帮你找了{democlock.date_label(date)}{session_label(session)}的号：")
    key = f"options:{source or uuid.uuid4().hex}:{date}:{session}"
    await say(reply, 'care:reply:' + key)
    await post_card(key, 'hospital_options', f"{dept['name']} · {democlock.date_label(date)}{session_label(session)}号源", {
        'patient': patient, 'patient_name': display(patient), 'real_name': real_name(patient), 'patient_id': FAMILY[patient]['patient_id'],
        'department': dept['name'], 'department_id': dept['id'], 'date': date, 'date_label': democlock.date_label(date),
        'session': session, 'options': options, 'compare': compare, 'weights': WEIGHTS,
        'familiar_doctor': fam_doc['name'] if fam_doc else None, 'requested_by': speaker,
        'approval_threshold': H.APPROVAL_THRESHOLD}, ['choose', 'next_day'])
    await trace.step('card', '推送号源对比卡', f"推荐①{top['campus']}·{top['doctor']} {top['date_label']}{top['time']} ¥{top['fee']}，等家人选择")
    return key


async def start_booking(agent, user_id, option, meta, *, origin_key, trace=None):
    """家人选定号源后：启动可观看的浏览器任务，走到核对页停下等确认。"""
    from .skills import SkillContext, execute
    trace = trace or Trace('浏览器代办挂号', None)
    patient_name = meta['real_name']
    args = {'action': 'book', 'instruction': f"为{patient_name}预约{option['campus']}{meta['department']}{option['doctor']}{option['date']} {option['time']}",
            'department': meta['department'], 'patient_name': patient_name, 'preferred_time': session_label(option['session']),
            'slot_id': option['slot_id'], 'campus_id': option['campus_id'], 'doctor_id': option['doctor_id'],
            'date': option['date'], 'patient_id': meta['patient_id']}
    ctx = SkillContext(GID, user_id, f'care:{origin_key}', 0, False, grants=[], selected={'hospital_simulator'}, now=democlock.now())
    await say(f"好，我这就去市一院官网给{display(meta['patient'])}挂{option['doctor']}医生{option['date_label']}{option['time']}的号。"
              f"旁边浏览器会自动填写，提交前会请你确认{'（挂号费超过 50 元需要你授权）' if option.get('needs_approval') else ''}。",
              f'care:booking:{origin_key}:{option["slot_id"]}')
    await trace.step('tool', 'hospital_simulator · book（浏览器自动化）', f"打开市一院官网：{option['campus']} → {meta['department']} → {option['doctor']} → {option['time']} → 就诊人{patient_name}")
    result = await execute('hospital_simulator', args, ctx)
    if 'error' in result:
        await say('打开医院网站出了点问题：' + result['error'], f'care:book-error:{origin_key}')
        await trace.step('error', '浏览器任务启动失败', result['error'])
        return None
    with DB() as db:
        run = get(db, 'run', GID, result['task_id'])
        if run:
            run.set({**run.data, 'care': True, 'care_meta': {**meta, 'option': option, 'origin': origin_key}})
            db.commit()
    await trace.step('rule', '人在回路：提交前暂停', '浏览器停在核对页 → 发确认卡；模型没有提交与支付能力')
    return result['task_id']


async def on_booked(gid, run_key, appointment):
    """浏览器提交成功（锁号）后由执行器回调：推送支付卡。"""
    appt_id = (appointment or {}).get('id')
    with DB() as db:
        appt = H.get_appt(db, appt_id) if appt_id else None
        run = get(db, 'run', gid, run_key)
        meta = (run.data.get('care_meta') if run else None) or {}
    if not appt:
        return
    trace = Trace('锁号成功 → 支付', None)
    await trace.step('tool', '浏览器提交预约', f"市一院返回预约编号 {appt['id']}，号源已扣减，锁号 15 分钟")
    who = next((k for k, v in FAMILY.items() if v['patient_id'] == appt['patientId']), 'mom')
    await say(f"锁号成功！{display(who)}的号已经占住了，15 分钟内付款就行 👇", f"care:locked:{appt['id']}")
    await post_card(f"pay:{appt['id']}", 'payment', '挂号费待支付', {
        'appt_id': appt['id'], 'patient': who, 'patient_name': appt['patientName'], 'campus': appt['campusName'],
        'department': appt['deptName'], 'doctor': appt['doctorName'], 'title': appt['doctorTitle'], 'date': appt['date'],
        'date_label': democlock.date_label(appt['date']), 'time': appt['startTime'], 'fee': appt['fee'],
        'expires_at': appt['lock_expires'], 'pay_url': f"/hospital/pay/{appt['id']}?t={H.pay_token(appt['id'])}",
        'pay_status': 'unpaid'}, ['pay'])
    await trace.step('card', '推送支付卡', '支付只能本人在收银台点击完成；收银台成功后回调小艺')


async def on_paid(appt):
    """收银台支付成功（模拟 webhook）：更新支付卡、发凭证卡、设就诊提醒、写入就诊档案。"""
    trace = Trace('支付成功 → 凭证与提醒', None)
    await trace.step('tool', '收到收银台支付回调', f"订单 {appt['id']} 已支付 ¥{appt['fee']}")
    await update_card(f"pay:{appt['id']}", status='done', data={'pay_status': 'paid', 'paid_at': appt.get('paid_at')}, actions=[])
    who = next((k for k, v in FAMILY.items() if v['patient_id'] == appt['patientId']), 'mom')
    visit_at = democlock.at(appt['date'], appt['startTime'])
    with DB() as db:
        put(db, 'reminder', GID, f"visit:{appt['id']}", {
            'content': f"{display(who)}今天 {appt['startTime']} 在市一院{appt['campusName']}{appt['deptName']}看{appt['doctorName']}医生，记得带医保卡和以前的病历。",
            'at': visit_at - 3600, 'sent': False, 'user_id': 0, 'channel': 'group', 'status': 'active', 'version': 1,
            'category': 'medical_visit', 'grace_seconds': 1800})
        save_memory(db, GID, f"{real_name(who)}已预约{democlock.date_label(appt['date'])}{appt['startTime']}市一院{appt['campusName']}{appt['deptName']}{appt['doctorName']}医生（已支付）",
                    [], [display(who)], key=f"visit-{appt['id']}", manual=True, explicit=True, domain='medical',
                    profile={'record_type': 'hospital', 'hospital': '市第一人民医院', 'campus': appt['campusName'], 'department': appt['deptName'],
                             'doctor': appt['doctorName'], 'doctor_id': appt['doctorId'], 'visit_date': visit_at, 'member_id': ids().get(who)},
                    metadata={'subject_ids': [ids().get(who)], 'category': 'medical'}, now=democlock.now())
        db.commit()
    await trace.step('memory', '写入就诊档案 + 就诊前 1 小时提醒', f"{real_name(who)} {appt['date']} {appt['startTime']} {appt['doctorName']}")
    await say(f"{display(who)}的号挂好了 🎉 {democlock.date_label(appt['date'])} {appt['startTime']}，市一院{appt['campusName']}{appt['deptName']}{appt['doctorName']}医生。"
              f"已加入日历，就诊前 1 小时我会提醒；看完病我也会继续盯着复诊和用药。", f"care:paid:{appt['id']}")
    await post_card(f"receipt:{appt['id']}", 'receipt', '挂号凭证', {
        'appt_id': appt['id'], 'patient_name': appt['patientName'], 'campus': appt['campusName'], 'department': appt['deptName'],
        'doctor': appt['doctorName'], 'title': appt['doctorTitle'], 'date': appt['date'], 'date_label': democlock.date_label(appt['date']),
        'time': appt['startTime'], 'fee': appt['fee'], 'paid_at': appt.get('paid_at'), 'address': H.campus(appt['campusId'])['address'],
        'calendar_url': f"/api/care/calendar/{appt['id']}.ics", 'reminder': '就诊前 1 小时提醒'}, ['calendar'], status='done')
    await trace.step('card', '推送挂号凭证（含日历文件）', '闭环完成：一句话 → 选号 → 确认 → 锁号 → 支付 → 凭证')


# ---------------------------------------------------------------- 就诊完成 → 守护计划
PLAN_SYSTEM = '''你是家庭就医守护助手“小艺”的病历结构化模块，只输出 JSON。
从电子病历医嘱中提取就诊后两周的守护计划，只能使用病历里写明的信息，不新增药物、不改剂量、不诊断。
输出：{"diagnosis":"诊断原文","items":[{"type":"medication|rehab|followup","title":"药名+剂量 / 训练名 / 复诊","detail":"频次与注意事项","days":14,"follow_up_days":14}],"summary":"一句话总结，不超过40字"}'''


def latest_visit_appt(patient_id='p-001', statuses=('confirmed',)):
    rows = [a for a in H.appointments() if a.get('patientId') == patient_id and a.get('status') in statuses and not a.get('history')]
    rows.sort(key=lambda a: (a.get('pay_status') == 'paid', a.get('createdAt', 0)))
    return rows[-1] if rows else None


def ensure_demo_appointment():
    """演示兜底：如果还没完成挂号，直接生成一张已支付的明早预约（避免现场卡住）。"""
    appt = latest_visit_appt()
    if appt:
        return appt, False
    tomorrow = democlock.shift_date(democlock.today(), 1)
    slots = [s for s in H.find_slots('d-guke', tomorrow, 'morning', 'c-main', 'doc-g1') if s['status'] == 'available']
    with DB() as db:
        appt = H.create_appointment(db, slots[0]['id'], 'p-001', 'demo-fallback-' + tomorrow, 'tk-demo')
        appt.update(pay_status='paid', paid_at=democlock.now())
        H.save_appt(db, appt)
        db.commit()
    return appt, True


def plan_from_emr(emr):
    med = emr['medications'][0]
    items = [
        {'type': 'medication', 'title': f"{med['name']} {med['dosage']}", 'detail': f"{med['frequency']} · {med.get('timing', '')}", 'days': med.get('days', 14)},
        {'type': 'rehab', 'title': emr['rehab']['name'], 'detail': emr['rehab']['detail'], 'days': emr['rehab'].get('days', 14)},
        {'type': 'followup', 'title': f"{emr['department']}复诊", 'detail': f"{emr['follow_up_days']} 天后找{emr['doctor']}医生复查", 'follow_up_days': emr['follow_up_days']},
    ]
    return {'diagnosis': emr['diagnosis'], 'items': items, 'summary': f"两周守护：按时吃药、每天康复训练、{emr['follow_up_days']}天后复诊"}


async def complete_visit(agent):
    trace = Trace('就诊完成 → 守护计划', None)
    appt, fallback = ensure_demo_appointment()
    if fallback:
        await trace.step('rule', '演示兜底', '尚未完成挂号，自动生成一次已支付的预约以继续演示')
    visit_ts = democlock.at(appt['date'], '11:20')
    if democlock.now() < visit_ts:
        old = democlock.now()
        democlock.set_now(visit_ts)
        filled = simulate(old, visit_ts)
        await say(f'—— 时间来到 {democlock.label(visit_ts)}（{display("mom")}刚看完门诊）——', f'care:clock:{int(visit_ts)}')
        await trace.step('rule', 'DemoClock 拨到就诊当天', f'{democlock.label()}，补齐 {filled} 条打卡记录')
    with DB() as db:
        appt = H.get_appt(db, appt['id'])
        appt['status'] = 'completed'
        appt['emr'] = H.make_emr(appt)
        H.save_appt(db, appt)
        db.commit()
    emr = appt['emr']
    who = next((k for k, v in FAMILY.items() if v['patient_id'] == appt['patientId']), 'mom')
    await trace.step('tool', '同步电子病历 · 市一院预约平台', f"{emr['department']} {emr['doctor']}：{emr['diagnosis']}")
    result, err = await llm_json(agent, 'care_plan', PLAN_SYSTEM, {'emr': {k: emr[k] for k in ('department', 'doctor', 'diagnosis', 'advice')}})
    plan, by_llm = None, False
    if result and isinstance(result.get('items'), list):
        items = [i for i in result['items'] if isinstance(i, dict) and i.get('type') in ('medication', 'rehab', 'followup') and i.get('title')]
        if {i['type'] for i in items} >= {'medication', 'followup'}:
            plan = {'diagnosis': str(result.get('diagnosis') or emr['diagnosis'])[:120], 'items': items[:5], 'summary': str(result.get('summary') or '')[:80]}
            by_llm = True
            await trace.step('llm', f'大模型结构化医嘱 · {model_name()}', '；'.join(f"{i['type']}:{i['title']}" for i in items[:4]))
    if not plan:
        plan = plan_from_emr(emr)
        await trace.step('rule', '医嘱结构化（规则）', err or '模型输出缺少必要字段，改用病历结构化字段')
    clocks = {'medication': '12:30', 'rehab': '19:00', 'followup': '08:30'}
    follow_days = next((int(i.get('follow_up_days') or 14) for i in plan['items'] if i['type'] == 'followup'), 14)
    follow_date = democlock.shift_date(appt['date'], max(3, min(30, follow_days)))
    rows = []
    for i, item in enumerate(plan['items']):
        row = {'key': f'{item["type"]}-{i}', 'type': item['type'], 'title': str(item['title'])[:40], 'detail': str(item.get('detail', ''))[:60],
               'clock': clocks[item['type']], 'enabled': True}
        if item['type'] == 'followup':
            row['date'] = follow_date
            row['schedule'] = f"{democlock.date_label(follow_date)} 08:30 · {appt['doctorName']}医生"
        else:
            days = max(1, min(30, int(item.get('days') or 14)))
            row['days'] = days
            row['schedule'] = f"每天 {row['clock']} · 连续 {days} 天"
        rows.append(row)
    await say(f"{display(who)}看完了。根据{emr['doctor']}医生的医嘱，我整理了一份两周守护计划，你看看合不合适：", f"care:visit:{appt['id']}")
    await post_card(f"plan:{appt['id']}", 'care_plan', '就诊后守护计划', {
        'appt_id': appt['id'], 'patient': who, 'patient_name': display(who), 'real_name': real_name(who),
        'source': f"市第一人民医院 · {emr['department']} · {emr['doctor']} · 电子病历", 'diagnosis': plan['diagnosis'],
        'summary': plan.get('summary'), 'advice': emr['advice'], 'items': rows, 'follow_date': follow_date,
        'doctor_id': appt['doctorId'], 'campus_id': appt['campusId'], 'dept_id': appt['deptId'],
        'extracted_by': 'llm' if by_llm else 'rule'},
        ['confirm_plan', 'dismiss'])
    await trace.step('card', '推送守护计划卡', '每项可单独开关，家属确认后才生效')
    return appt['id']


def confirm_plan_items(card):
    d = card['care']['data']
    visit = next((a for a in H.appointments() if a['id'] == d['appt_id']), None)
    start = visit['date'] if visit else democlock.today()
    who = d['patient']
    created = []
    with DB() as db:
        for row in d['items']:
            if not row.get('enabled', True):
                continue
            key = f"plan-{d['appt_id']}-{row['type']}"
            if row['type'] in ('medication', 'rehab'):
                days = row.get('days', 14)
                misses = [democlock.shift_date(start, 4)] if row['type'] == 'medication' else [democlock.shift_date(start, 3), democlock.shift_date(start, 8)]
                put(db, 'care_item', GID, key, {'key': key, 'member': who, 'type': row['type'], 'title': row['title'], 'detail': row['detail'],
                    'clock': row['clock'], 'start': start, 'end': democlock.shift_date(start, days - 1), 'status': 'active',
                    'source': d['source'], 'miss_dates': misses, 'plan': d['appt_id']})
            else:
                put(db, 'care_item', GID, key, {'key': key, 'member': who, 'type': 'followup', 'title': row['title'], 'detail': row['detail'],
                    'date': row['date'], 'clock': '08:30', 'status': 'active', 'source': d['source'], 'plan': d['appt_id'],
                    'doctor_id': d['doctor_id'], 'campus_id': d['campus_id'], 'dept_id': d['dept_id'],
                    'briefing_at': democlock.at(democlock.shift_date(row['date'], -1), '20:00'), 'briefing_sent': False, 'visit_start': start})
                save_memory(db, GID, f"{real_name(who)}{democlock.date_label(row['date'])}需要复诊（{row['detail']}）", [], [display(who)],
                            key=f"followup-{d['appt_id']}", manual=True, explicit=True, domain='medical',
                            profile={'record_type': 'followup', 'follow_up_date': democlock.at(row['date'], '08:30'), 'member_id': ids().get(who)},
                            metadata={'subject_ids': [ids().get(who)], 'category': 'medical'}, now=democlock.now())
            if row['type'] == 'medication':
                save_memory(db, GID, f"{real_name(who)}正在服用{row['title']}（{row['detail']}），{d['source']}", [], [display(who)],
                            key=f"med-{d['appt_id']}", manual=True, explicit=True, domain='medical',
                            profile={'record_type': 'medication', 'medications': [{'name': row['title'], 'frequency': row['detail']}], 'member_id': ids().get(who)},
                            metadata={'subject_ids': [ids().get(who)], 'category': 'medical'}, now=democlock.now())
            created.append(row)
        db.commit()
    return created


# ---------------------------------------------------------------- 用药/康复打卡与依从性
def items(kind=None, member=None, active=True):
    with DB() as db:
        rows = [r.data for r in records(db, 'care_item', GID)]
    return [i for i in rows if (kind is None or i['type'] in ((kind,) if isinstance(kind, str) else kind))
            and (member is None or i['member'] == member) and (not active or i.get('status') == 'active')]


def logs(item_key):
    with DB() as db:
        return {r.data['date']: r.data for r in records(db, 'care_log', GID) if r.data.get('item') == item_key}


def occurrences(item, until=None):
    """截至 until 已经到点的每日事项日期列表。"""
    until = democlock.now() if until is None else until
    out = []
    date = item['start']
    end = item.get('end') or democlock.today(until)
    while date <= end:
        if democlock.at(date, item['clock']) <= until:
            out.append(date)
        date = democlock.shift_date(date, 1)
        if len(out) > 400:
            break
    return out


def stats(item, days=None):
    occ = occurrences(item)
    if days:
        cutoff = democlock.shift_date(democlock.today(), -(days - 1))
        occ = [d for d in occ if d >= cutoff]
    got = logs(item['key'])
    # 今天到点但还没打卡的不算漏服，等家人打卡
    occ = [d for d in occ if d in got or d != democlock.today()]
    taken = sum(1 for d in occ if got.get(d, {}).get('status') == 'taken')
    return {'taken': taken, 'total': len(occ), 'rate': round(100 * taken / len(occ)) if occ else None,
            'missed': [d for d in occ if got.get(d, {}).get('status') != 'taken']}


def log(item_key, member, date, status, by):
    with DB() as db:
        put(db, 'care_log', GID, f'{item_key}:{date}', {'item': item_key, 'member': member, 'date': date, 'status': status,
            'at': democlock.now(), 'by': by})
        db.commit()


def simulate(old, new, leave_recent=1800):
    """演示时钟快进时，按预设模式补齐跳过这几天的打卡记录（不在群里刷屏）。
    快进终点前 30 分钟内到点的事项不补，留给家人现场打卡。"""
    count = 0
    for item in items(('medication', 'rehab')):
        got = logs(item['key'])
        for date in occurrences(item, new):
            if date in got:
                continue
            occ = democlock.at(date, item['clock'])
            if old < occ <= new - leave_recent:
                status = 'missed' if date in item.get('miss_dates', []) else 'taken'
                with DB() as db:
                    put(db, 'care_log', GID, f"{item['key']}:{date}", {'item': item['key'], 'member': item['member'], 'date': date,
                        'status': status, 'at': occ + (0 if status == 'missed' else 900), 'by': 'simulated'})
                    db.commit()
                count += 1
    return count


async def send_checkin(item, reason='到点提醒'):
    date = democlock.today()
    key = f"checkin:{item['key']}:{date}"
    if card_data(key):
        return None
    who = item['member']
    verb = '吃' if item['type'] == 'medication' else '做'
    await say(f"{display(who)}，{'今天的' + item['title'] + '该吃啦' if item['type'] == 'medication' else '该做' + item['title'] + '啦'}～{verb}完点一下「已{verb}」就行。",
              f'care:checkin-text:{key}')
    return await post_card(key, 'med_checkin', f"{display(who)} · {item['title']}", {
        'member': who, 'member_name': display(who), 'item': item['key'], 'kind': item['type'], 'title': item['title'],
        'detail': item['detail'], 'time': item['clock'], 'date': date, 'reason': reason}, ['taken', 'snooze'])


async def handle_checkin_text(message, speaker):
    meds = items('medication', speaker)
    if not meds:
        return False
    item = meds[0]
    date = democlock.today()
    log(item['key'], speaker, date, 'taken', 'chat')
    key = f"checkin:{item['key']}:{date}"
    if card_data(key):
        await update_card(key, status='done', data={'result': 'taken'}, actions=[])
    s = stats(item, 7)
    await say(f"好嘞，记下了 ✓ {display(speaker)}这周按时吃药 {s['taken']}/{s['total']} 天。", f'care:checkin-ack:{message.id}')
    trace = Trace(f'{display(speaker)}用药打卡', message.id)
    await trace.step('rule', '识别为用药打卡（自然语言）', f"“{message.content[:30]}” → 记录 {item['title']} 已服")
    return True


def week_days(item, n=7):
    got = logs(item['key'])
    occ = set(occurrences(item))
    out = []
    for i in range(n - 1, -1, -1):
        date = democlock.shift_date(democlock.today(), -i)
        weekday = democlock.WEEKDAYS[democlock.local(democlock.at(date)).weekday()]
        status = got.get(date, {}).get('status') if date in occ else 'pending'
        if status not in ('taken', 'missed'):
            # 今天到点但还没打卡算“待打卡”，往日没有记录算漏服
            status = 'pending' if date == democlock.today() or date not in occ else 'missed'
        out.append({'date': date, 'label': f'{int(date[5:7])}/{int(date[8:])}', 'weekday': weekday, 'status': status})
    return out


async def refresh_adherence(item):
    """家人打卡后，同步更新照护人那张依从性卡上的数字。"""
    rows = [c for c in cards_of('adherence') if c['care']['data'].get('item') == item['key']]
    if not rows:
        return
    days = week_days(item)
    done = [d for d in days if d['status'] != 'pending']
    taken = sum(1 for d in done if d['status'] == 'taken')
    rate = round(100 * taken / len(done)) if done else 0
    await update_card(rows[-1]['id'], data={'days': days, 'taken': taken, 'total': len(done), 'rate': rate, 'today_pending': False,
                                            'level': 'good' if rate >= 90 else 'warn' if rate >= 70 else 'bad'})


async def adherence_report(member='dad'):
    item = next(iter(items('medication', member)), None)
    if not item:
        return None
    trace = Trace(f'用药周报 · {display(member)}', None)
    days = week_days(item)
    done = [d for d in days if d['status'] != 'pending']
    taken = sum(1 for d in done if d['status'] == 'taken')
    missed = [d['weekday'] for d in done if d['status'] == 'missed']
    rate = round(100 * taken / len(done)) if done else 0
    await trace.step('rule', '统计近 7 天打卡', f"{item['title']}：已服 {taken}/{len(done)} 天，漏服 {('、'.join(missed)) or '无'}")
    level = 'good' if rate >= 90 else 'warn' if rate >= 70 else 'bad'
    today_pending = days[-1]['status'] == 'pending' and democlock.at(democlock.today(), item['clock']) <= democlock.now()
    text_ = (f"{display(CAREGIVER)}，{display(member)}这周的{item['title'].split()[0]}有 {len(missed)} 次没按时吃（{'、'.join(missed)}）"
             + ('，今天早上的也还没打卡：' if today_pending else '：')
             if missed else f"{display(CAREGIVER)}，{display(member)}这周按时吃药，一次没落下 👍")
    await say(text_, f"care:adherence-text:{item['key']}:{democlock.today()}")
    card = await post_card(f"adherence:{item['key']}:{democlock.today()}", 'adherence', f"{display(member)}本周用药情况", {
        'member': member, 'member_name': display(member), 'real_name': real_name(member), 'item': item['key'], 'title': item['title'],
        'detail': item['detail'], 'days': days, 'taken': taken, 'total': len(done), 'rate': rate, 'missed': missed, 'level': level,
        'today_pending': today_pending, 'for': CAREGIVER}, ['nudge', 'dismiss'])
    await trace.step('card', '推送依从性卡给照护人', f'依从率 {rate}%（≥90% 绿色 / 70–90% 黄色 / <70% 红色）')
    return card


# ---------------------------------------------------------------- 复诊前一天：简报 + 预约
BRIEF_SYSTEM = '''你是家庭就医守护助手“小艺”的复诊准备模块，只输出 JSON。
根据病历和两周的用药、康复打卡数据，给家属准备 3 个就诊时可以问医生的问题，具体、口语化，每个不超过 22 字。
不诊断、不给用药建议。输出：{"questions":["...","...","..."]}'''


async def followup_briefing(agent, item):
    trace = Trace(f'复诊前一天 · {display(item["member"])}', None)
    who = item['member']
    with DB() as db:
        visit = H.get_appt(db, item['plan'])
    emr = (visit or {}).get('emr') or {}
    meds = [i for i in items('medication', who) if i.get('plan') == item['plan']]
    rehab = [i for i in items('rehab', who) if i.get('plan') == item['plan']]
    med_s = stats(meds[0]) if meds else None
    rehab_s = stats(rehab[0]) if rehab else None
    day_n = (democlock.local(democlock.at(democlock.today())) - democlock.local(democlock.at(item['visit_start']))).days + 1
    await trace.step('rule', 'DemoClock 到点：复诊前一天 20:00', f"{real_name(who)}康复第 {day_n} 天，明天 {item['date']} 复诊")
    await trace.step('rule', '汇总两周打卡', f"用药 {med_s['taken']}/{med_s['total']} · 康复 {rehab_s['taken']}/{rehab_s['total']}" if med_s and rehab_s else '无打卡数据')
    slots = [s for s in H.find_slots(item['dept_id'], item['date'], 'morning', item['campus_id'], item['doctor_id']) if s['status'] == 'available']
    slots.sort(key=lambda s: (s['startTime'] != '08:30', s['startTime']))
    dists = await distances([item['campus_id']], trace)
    option = option_from_slot(slots[0], dists[item['campus_id']], H.history_count(FAMILY[who]['patient_id'], item['campus_id']),
                              H.doctor(item['doctor_id'])) if slots else None
    if option:
        await trace.step('tool', '查询上次医生的号源', f"{option['doctor']} {option['date_label']} {option['time']} 还剩 {option['remaining']} 个")
    result, err = await llm_json(agent, 'care_briefing', BRIEF_SYSTEM, {
        'diagnosis': emr.get('diagnosis'), 'advice': emr.get('advice'), 'medication': med_s, 'rehab': rehab_s})
    questions = [str(q)[:30] for q in (result or {}).get('questions', []) if str(q).strip()][:3] if result else []
    if len(questions) == 3:
        await trace.step('llm', f'大模型生成“建议问医生” · {model_name()}', ' / '.join(questions))
    else:
        questions = ['现在可以开始负重训练、慢慢上下楼了吗？', '消炎药还需要继续吃吗？', '下次复查隔多久，平时疼了怎么办？']
        await trace.step('rule', '建议问医生（模板）', err or '模型输出不足 3 条，使用模板')
    doctor_name = option['doctor'] if option else emr.get('doctor', '')
    await say(f"{display(CAREGIVER)}，{real_name(who)}康复第 {day_n} 天，明天该复查了。我已经看好了上次{doctor_name}医生的号，简报也准备好了：",
              f"care:followup-text:{item['key']}")
    await post_card(f"followup:{item['key']}", 'followup', '复诊提醒 · 就诊简报', {
        'patient': who, 'patient_name': display(who), 'real_name': real_name(who), 'patient_id': FAMILY[who]['patient_id'],
        'department': emr.get('department', ''), 'diagnosis': emr.get('diagnosis', ''), 'day_n': day_n, 'option': option,
        'medication': {**med_s, 'title': meds[0]['title']} if med_s else None, 'rehab': {**rehab_s, 'title': rehab[0]['title']} if rehab_s else None,
        'questions': questions, 'generated_by': 'llm' if len(questions) == 3 and result else 'rule', 'date': item['date']},
        ['book', 'reschedule'] if option else ['reschedule'])
    await trace.step('card', '推送复诊简报卡', '确认后沿用同一条“浏览器锁号 → 支付”闭环')


async def tick(agent):
    """每 5 秒由调度器调用：到点打卡卡片、复诊前一天简报。"""
    global _last_tick
    if time.monotonic() - _last_tick < 5:
        return
    _last_tick = time.monotonic()
    set_agent(agent)
    now = democlock.now()
    for item in items(('medication', 'rehab')):
        date = democlock.today()
        if date < item['start'] or (item.get('end') and date > item['end']):
            continue
        occ = democlock.at(date, item['clock'])
        if occ <= now <= occ + 900 and date not in logs(item['key']):
            await send_checkin(item)
    for item in items('followup'):
        if not item.get('briefing_sent') and now >= item['briefing_at'] and item['key'] not in _running_briefings:
            _running_briefings.add(item['key'])
            with DB() as db:
                r = get(db, 'care_item', GID, item['key'])
                r.set({**r.data, 'briefing_sent': True})
                db.commit()
            try:
                await followup_briefing(agent, item)
            finally:
                _running_briefings.discard(item['key'])


# ---------------------------------------------------------------- 急症拦截（只走规则）
async def handle_emergency(message, speaker, text_, reason):
    trace = Trace(f'急症拦截 · {display(speaker)}', message.id)
    await trace.step('rule', '红旗症状规则命中（不经过大模型）', f'“{text_[:40]}” → {reason}', 1)
    er = await nearest_er(trace)
    await say(f"⚠️ {display(speaker)}，这种情况不能等门诊！请马上拨打 120。先坐下或半躺别走动，把门打开方便急救人员进来。",
              f'care:emergency:{message.id}')
    await post_card(f'emergency:{message.id}', 'emergency', '急症提醒：请立即就医', {
        'member': speaker, 'member_name': display(speaker), 'quote': text_[:60], 'reason': reason, 'nearest': er,
        'advice': ['立即拨打 120，说清地址和症状', '原地坐下或半躺，不要走动、不要自己开车', '家里有人就陪在旁边，打开门方便急救进入'],
        'notified': display(CAREGIVER) if speaker != CAREGIVER else None, 'call': '120'}, ['called', 'safe'])
    if speaker != CAREGIVER:
        await say(f"@{display(CAREGIVER)} {display(speaker)}说“{text_[:24]}”，属于急症信号，我已经提醒立即拨打 120，请尽快联系家里。",
                  f'care:emergency-notify:{message.id}')
    await trace.step('card', '推送急诊卡 + 通知照护人', '该劝去急诊时不挂门诊号——这是产品底线')


# ---------------------------------------------------------------- 看板 / 轨迹 / 演示控制
def dashboard():
    uid = ids()
    members = []
    with DB() as db:
        mems = [dict(key=r.key, **r.data) for r in records(db, 'memory', GID) if not r.data.get('deleted') and r.data.get('status', 'active') == 'active']
    upcoming = []
    for login, f in FAMILY.items():
        meds = items('medication', login)
        adh = None
        if meds:
            s = stats(meds[0], 7)
            adh = {'title': meds[0]['title'], **s}
        plan = [i for i in items(('medication', 'rehab'), login) if i.get('plan')]
        follow = items('followup', login)
        appts = [a for a in H.appointments() if a.get('patientId') == f['patient_id'] and a.get('status') == 'confirmed' and a.get('date', '') >= democlock.today()]
        if f['role'] == 'caregiver':
            tag, level = '照护人 · 在上海', 'info'
        elif appts:
            a = appts[-1]
            tag, level = f"已约 {democlock.date_label(a['date'])} {a['doctorName']}", 'info'
        elif plan:
            start = plan[0]['start']
            n = (democlock.local(democlock.at(democlock.today())) - democlock.local(democlock.at(start))).days + 1
            tag, level = f'康复中 · 第 {n} 天', 'good'
        elif adh and adh['rate'] is not None and adh['rate'] < 90:
            tag, level = f"本周漏服 {adh['total'] - adh['taken']} 次", 'warn'
        elif recent_hint(login):
            tag, level = '刚说身体不舒服', 'warn'
        else:
            tag, level = '状态平稳', 'muted'
        for a in appts:
            upcoming.append({'at': democlock.at(a['date'], a['startTime']), 'label': f"{display(login)} · {a['deptName']} {a['doctorName']}", 'kind': 'visit',
                             'when': f"{democlock.date_label(a['date'])} {a['startTime']}", 'paid': a.get('pay_status') == 'paid'})
        for fo in follow:
            upcoming.append({'at': democlock.at(fo['date'], '08:30'), 'label': f"{display(login)} · {fo['title']}", 'kind': 'followup',
                             'when': f"{democlock.date_label(fo['date'])} 08:30"})
        for it in items(('medication', 'rehab'), login):
            nxt = next_occurrence(it)
            if nxt:
                upcoming.append({'at': nxt, 'label': f"{display(login)} · {it['title']}", 'kind': it['type'], 'when': democlock.label(nxt)[democlock.label(nxt).find(' ') + 1:]})
        members.append({'login': login, 'id': uid.get(login), 'name': f['name'], 'real_name': f['real_name'], 'age': f['age'], 'role': f['role'],
                        'conditions': f['conditions'], 'allergies': f['allergies'], 'tag': tag, 'level': level, 'adherence': adh,
                        'plan': [{'title': i['title'], 'type': i['type'], **stats(i)} for i in plan], 'note': f['note']})
    profile = [{'content': m['content'], 'domain': m.get('domain', 'general'), 'type': (m.get('profile') or {}).get('record_type'),
                'subject': (m.get('subjects') or [''])[0]} for m in mems]
    profile.sort(key=lambda m: (m['domain'] != 'medical',))
    upcoming.sort(key=lambda x: x['at'])
    week_start = democlock.now() - 7 * 86400
    with DB() as db:
        checkins = sum(1 for r in records(db, 'care_log', GID) if r.data.get('status') == 'taken' and r.data.get('at', 0) >= week_start)
        cards = [r.data for r in records(db, 'card', GID) if r.data.get('kind') == 'care']
    bookings = sum(1 for a in H.appointments() if not a.get('history') and a.get('createdAt', 0) / 1000 >= week_start and a.get('status') != 'cancelled')
    return {'clock': {'ts': democlock.now(), 'label': democlock.label(), 'day': day_index()}, 'members': members,
            'profile': profile[:12], 'upcoming': [u for u in upcoming if u['at'] >= democlock.now() - 600][:6],
            'week': {'bookings': bookings, 'checkins': checkins, 'cards': len(cards),
                     'emergencies': sum(1 for c in cards if c['care']['type'] == 'emergency')}}


def recent_hint(login, hours=24):
    with DB() as db:
        r = get(db, 'care_hint', GID, login)
    return bool(r and democlock.now() - r.data.get('at', 0) < hours * 3600)


def next_occurrence(item):
    now = democlock.now()
    date = democlock.today()
    for _ in range(3):
        if (not item.get('end') or date <= item['end']) and date >= item['start']:
            ts = democlock.at(date, item['clock'])
            if ts > now:
                return ts
        date = democlock.shift_date(date, 1)
    return None


def day_index():
    try:
        d0 = day0()
        return (democlock.local(democlock.at(democlock.today())) - democlock.local(democlock.at(d0))).days
    except (ValueError, TypeError):
        return 0


def trace_list(limit=12):
    with DB() as db:
        rows = [r.data for r in records(db, 'care_trace', GID)]
    turns = {}
    for row in rows:
        t = turns.setdefault(row['turn'], {'turn': row['turn'], 'title': row['title'], 'at': row['at'], 'real_at': row.get('real_at', 0), 'steps': []})
        t['steps'].append(row)
        t['real_at'] = max(t['real_at'], row.get('real_at', 0))
    out = sorted(turns.values(), key=lambda t: -t['real_at'])[:limit]
    for t in out:
        t['steps'].sort(key=lambda s: s['n'])
        t['ms'] = sum(s.get('ms') or 0 for s in t['steps'])
    return out


DEMO_STEPS = [
    {'key': 'hint', 'title': '妈妈说膝盖不舒服', 'actor': 'mom', 'desc': '妈妈在群里随口一句（没 @小艺），小艺结合病史和天气主动提醒小林',
     'say': ('mom', '今天阴天，膝盖又酸又胀，下楼都费劲……'), 'next': '在「小艺建议」卡上点「好的，帮挂号」，或者执行下一步'},
    {'key': 'booking', 'title': '小林一句话挂号', 'actor': 'child', 'desc': '不说医院、不说科室，小艺用档案补全并给出排序后的号源',
     'say': ('child', '@小艺 帮我妈挂明天上午的号'), 'next': '选号 → 浏览器自动填表 → 确认卡点「确认并继续」→ 去收银台支付'},
    {'key': 'visit', 'title': '看完病 → 守护计划', 'actor': 'system', 'desc': '时钟拨到就诊当天，医院同步电子病历，小艺生成两周守护计划',
     'next': '在守护计划卡上点「确认计划」'},
    {'key': 'week', 'title': '快进 7 天 · 爸爸用药周报', 'actor': 'system', 'desc': '统计爸爸一周降压药打卡，发现漏服 2 次，提醒照护人',
     'next': '点「提醒爸爸吃药」，在爸爸的窗口点「已吃」'},
    {'key': 'followup', 'title': '快进到复诊前一天', 'actor': 'system', 'desc': '复诊前一晚：自动查上次医生的号 + 就诊简报 + 建议问医生',
     'next': '点「确认挂号」再走一遍锁号支付闭环'},
    {'key': 'emergency', 'title': '爸爸突发胸痛', 'actor': 'dad', 'desc': '红旗症状规则命中：不挂门诊，直接劝 120 并通知照护人',
     'say': ('dad', '胸口疼得厉害，有点喘不上气'), 'next': '演示结束，可以打开「小艺在想什么」讲技术链路'},
]


def demo_state():
    with DB() as db:
        state = get(db, 'demo', GID, 'state')
        done = (state.data.get('steps') if state else {}) or {}
    return {'clock': {'ts': democlock.now(), 'label': democlock.label(), 'day': day_index(), 'offset': democlock.offset()},
            'steps': [{**{k: v for k, v in s.items() if k != 'say'}, 'done': s['key'] in done,
                       'line': s.get('say', (None, None))[1]} for s in DEMO_STEPS],
            'model': {'configured': bool(os.getenv('DEEPSEEK_API_KEY')), 'name': model_name()},
            'amap': bool(os.getenv('AMAP_MCP_URL')),
            'browser_headless': os.getenv('HOSPITAL_HEADLESS', '').lower() in ('1', 'true', 'yes')}


def mark_step(key):
    with DB() as db:
        state = get(db, 'demo', GID, 'state')
        d = state.data if state else {'day0': democlock.today(), 'steps': {}}
        d.setdefault('steps', {})[key] = democlock.now()
        put(db, 'demo', GID, 'state', d)
        db.commit()


async def advance_to(agent, ts, reason):
    old = democlock.now()
    if ts <= old:
        return 0
    democlock.set_now(ts)
    n = simulate(old, ts)
    trace = Trace(f'DemoClock 快进 · {reason}', None)
    await trace.step('rule', 'DemoClock 快进', f'{democlock.label(old)} → {democlock.label(ts)}，补齐 {n} 条打卡记录（模拟这几天的作息）')
    await say(f'—— 时间快进到 {democlock.label(ts)}（{reason}）——', f'care:clock:{int(ts)}')
    await broadcast({'type': 'refresh'})
    return n


async def run_step(agent, key, user):
    step = next((s for s in DEMO_STEPS if s['key'] == key), None)
    if not step:
        raise HTTPException(404, '未知演示步骤')
    set_agent(agent)
    if step.get('say'):
        login, line = step['say']
        await post_as(agent, login, line)
    elif key == 'visit':
        await complete_visit(agent)
    elif key == 'week':
        target = democlock.at(democlock.shift_date(day0(), 7), '08:20')
        await advance_to(agent, max(target, democlock.now() + 60), '第 7 天早上')
        await adherence_report('dad')
    elif key == 'followup':
        follow = items('followup')
        if not follow:
            pending = [c for c in cards_of('care_plan') if c['status'] == 'active']
            if not pending:
                await complete_visit(agent)
                pending = [c for c in cards_of('care_plan') if c['status'] == 'active']
            if pending:
                await act_on_card(agent, pending[-1]['id'], 'confirm_plan', None, ids()[CAREGIVER])
            follow = items('followup')
        if follow:
            item = follow[-1]
            await advance_to(agent, max(item['briefing_at'] + 30, democlock.now() + 60), '复诊前一天晚上')
            await tick_now(agent)
    mark_step(key)
    return demo_state()


async def tick_now(agent):
    global _last_tick
    _last_tick = 0
    await tick(agent)


def cards_of(ctype):
    with DB() as db:
        return [r.data for r in records(db, 'card', GID) if r.data.get('kind') == 'care' and r.data['care']['type'] == ctype]


async def post_as(agent, login, content):
    """以某位家人的身份发群消息（演示导演台用），与真实发消息走同一条管线。"""
    from .intent import direct_mention
    with DB() as db:
        user = db.query(User).filter_by(username=login).first()
        settings = get(db, 'group', GID, 'settings').data
        m = Message(group_id=GID, user_id=user.id, client_id='demo:' + uuid.uuid4().hex, content=content, attachments='[]')
        db.add(m)
        db.flush()
        put(db, 'job', GID, str(m.id), {'source': m.id, 'mention': direct_mention(content, settings['agent_name']),
            'settings': settings, 'status': 'pending', 'analyzed': False})
        db.commit()
        mid = m.id
    await agent.broadcast(GID, {'type': 'message', 'id': mid})
    return mid


# ---------------------------------------------------------------- 卡片动作
async def act_on_card(agent, card_id, action, payload, user_id):
    set_agent(agent)
    card = card_data(card_id)
    if not card or card.get('kind') != 'care':
        raise HTTPException(404, '卡片不存在')
    ctype, d = card['care']['type'], card['care']['data']
    if card['status'] != 'active' and action not in ('calendar',):
        return card
    allowed = card['care']['actions']
    if action not in allowed:
        raise HTTPException(409, '卡片已更新，请查看最新状态')
    who = login_of(user_id)
    if ctype == 'need_hint':
        if action == 'dismiss':
            return await update_card(card_id, status='done', data={'result': '先不挂号'}, actions=[])
        await update_card(card_id, status='done', data={'result': f'{display(who)}：好的，帮挂号'}, actions=[])
        trace = Trace('「小艺建议」→ 一句话挂号', card['message_id'])
        await handle_booking_request(agent, user_id, '', source=card['message_id'], speaker=who, trace=trace,
                                     preset={'patient': d['member'], 'department': d['department'], 'date': d['date'], 'session': d['session']})
    elif ctype == 'hospital_options':
        if action == 'next_day':
            await update_card(card_id, status='done', data={'result': '看看后一天'}, actions=[])
            await handle_booking_request(agent, user_id, '', source=card['message_id'], speaker=who,
                                         preset={'patient': d['patient'], 'department': d['department'], 'date': democlock.shift_date(d['date'], 1), 'session': d['session']})
        else:
            option = next((o for o in d['options'] if o['id'] == (payload or {}).get('option')), None)
            if not option:
                raise HTTPException(422, '请选择一个可预约的号源')
            fresh = H.slot(option['slot_id'])
            if not fresh or fresh['status'] != 'available':
                await say('哎呀，这个号刚被约走了，我再帮你看看别的。', f'care:gone:{card_id}:{option["id"]}')
                await update_card(card_id, status='done', data={'result': '号源已变化'}, actions=[])
                return await handle_booking_request(agent, user_id, '', source=card['message_id'], speaker=who,
                                                    preset={'patient': d['patient'], 'department': d['department'], 'date': d['date'], 'session': d['session']})
            await update_card(card_id, status='done', data={'chosen': option['id'], 'result': f"已选 {option['campus']} · {option['doctor']} {option['time']}"}, actions=[])
            trace = Trace('选定号源 → 浏览器代办', card['message_id'])
            await trace.step('rule', '锁号前复查号源', f"{option['doctor']} {option['time']} 仍可约（剩 {fresh['remaining']} 个）")
            await start_booking(agent, user_id, option, {k: d[k] for k in ('patient', 'real_name', 'patient_id', 'department')}, origin_key=card_id, trace=trace)
    elif ctype == 'care_plan':
        if action == 'dismiss':
            return await update_card(card_id, status='done', data={'result': '暂不启用'}, actions=[])
        enabled = set((payload or {}).get('enabled') or [r['key'] for r in d['items']])
        rows = [{**r, 'enabled': r['key'] in enabled} for r in d['items']]
        await update_card(card_id, data={'items': rows})
        created = confirm_plan_items(card_data(card_id))
        await update_card(card_id, status='done', data={'result': f'已启用 {len(created)} 项'}, actions=[])
        trace = Trace('守护计划生效', card['message_id'])
        await trace.step('memory', '写入照护事项与医疗档案', '；'.join(f"{r['title']}（{r['schedule']}）" for r in created))
        med = next((r for r in created if r['type'] == 'medication'), None)
        rehab = next((r for r in created if r['type'] == 'rehab'), None)
        follow = next((r for r in created if r['type'] == 'followup'), None)
        parts = []
        if med:
            parts.append(f"每天 {med['clock']} 提醒{d['patient_name']}吃药")
        if rehab:
            parts.append(f"晚上 {rehab['clock']} 提醒康复训练")
        if follow:
            parts.append('复诊前一天我会提前把号和就诊简报准备好')
        await say('好，计划已生效 ✓ ' + '，'.join(parts) + '。', f'care:plan-ok:{card_id}')
    elif ctype == 'med_checkin':
        if action == 'snooze':
            await update_card(card_id, data={'result': '30 分钟后再提醒'}, actions=['taken'])
            await say(f"好的，{display(d['member'])}，过会儿我再叫你～", f"care:snooze:{card_id}")
        else:
            log(d['item'], d['member'], d['date'], 'taken', 'card')
            await update_card(card_id, status='done', data={'result': '已打卡'}, actions=[])
            item = next((i for i in items(member=d['member']) if i['key'] == d['item']), None)
            if item:
                await refresh_adherence(item)
            s = stats(item, 7) if item else {'taken': 1, 'total': 1}
            await say(f"好嘞 ✓ {display(d['member'])}真棒！这周按时{'吃药' if d['kind'] == 'medication' else '训练'} {s['taken']}/{s['total']} 天。", f'care:taken:{card_id}')
    elif ctype == 'adherence':
        if action == 'dismiss':
            return await update_card(card_id, status='done', data={'result': '稍后再说'}, actions=[])
        await update_card(card_id, status='done', data={'result': f"已提醒{d['member_name']}"}, actions=[])
        item = next(iter(items('medication', d['member'])), None)
        if item:
            with DB() as db:
                old = get(db, 'card', GID, f"checkin:{item['key']}:{democlock.today()}")
                if old:
                    db.delete(old)
                    db.commit()
            await send_checkin(item, '照护人提醒')
    elif ctype == 'followup':
        option = d.get('option')
        if action == 'reschedule' or not option:
            await update_card(card_id, status='done', data={'result': '改约其他时间'}, actions=[])
            await handle_booking_request(agent, user_id, '', source=card['message_id'], speaker=who,
                                         preset={'patient': d['patient'], 'department': d['department'], 'date': democlock.shift_date(d['date'], 1), 'session': 'morning'})
        else:
            await update_card(card_id, status='done', data={'result': f"已确认 {option['doctor']} {option['time']}"}, actions=[])
            trace = Trace('复诊 → 浏览器代办', card['message_id'])
            await start_booking(agent, user_id, option, {'patient': d['patient'], 'real_name': d['real_name'], 'patient_id': d['patient_id'],
                                                         'department': d['department']}, origin_key=card_id, trace=trace)
    elif ctype == 'emergency':
        result = '已拨打 120' if action == 'called' else '已确认安全'
        await update_card(card_id, status='done', data={'result': f'{display(who)}：{result}'}, actions=[])
        await say('收到。我会一直在，有需要随时叫我。' if action == 'safe' else '好，急救车在路上了。我已经把爸爸的病史和用药整理好，到医院可以直接给医生看。', f'care:er-ack:{card_id}')
    return card_data(card_id)


# ---------------------------------------------------------------- 日历文件
def calendar_ics(appt_id):
    with DB() as db:
        appt = H.get_appt(db, appt_id)
    if not appt:
        raise HTTPException(404, '预约不存在')
    start = democlock.local(democlock.at(appt['date'], appt['startTime']))
    end = democlock.local(democlock.at(appt['date'], appt['endTime']))
    fmt = lambda d: d.strftime('%Y%m%dT%H%M%S')
    body = '\r\n'.join([
        'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//xiaoyi//family//CN', 'BEGIN:VEVENT', f'UID:{appt_id}@xiaoyi',
        f'DTSTART;TZID=Asia/Shanghai:{fmt(start)}', f'DTEND;TZID=Asia/Shanghai:{fmt(end)}',
        f"SUMMARY:{appt['patientName']} · {appt['deptName']} {appt['doctorName']}",
        f"LOCATION:市第一人民医院{appt['campusName']}（{H.campus(appt['campusId'])['address']}）",
        f"DESCRIPTION:预约编号 {appt_id}，请提前 15 分钟到院取号。",
        'BEGIN:VALARM', 'TRIGGER:-PT60M', 'ACTION:DISPLAY', 'DESCRIPTION:就诊提醒', 'END:VALARM',
        'END:VEVENT', 'END:VCALENDAR', ''])
    return Response(body, media_type='text/calendar; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{appt_id}.ics"'})


# ---------------------------------------------------------------- 路由
class ActBody(BaseModel):
    action: str = Field(min_length=1, max_length=40)
    option: str | None = Field(default=None, max_length=200)
    enabled: list[str] | None = None


class ClockBody(BaseModel):
    advance_minutes: int | None = Field(default=None, ge=1, le=60 * 24 * 30)


class SayBody(BaseModel):
    user: str = Field(pattern='^(dad|mom|child)$')
    content: str = Field(min_length=1, max_length=500)


def install_routes(app, current, access, agent):
    set_agent(agent)

    @app.get('/api/care/dashboard')
    def care_dashboard(user=Depends(current)):
        access(GID, user)
        return dashboard()

    @app.get('/api/care/trace')
    def care_trace(user=Depends(current)):
        access(GID, user)
        return trace_list()

    @app.post('/api/care/cards/{card_id}/act')
    async def care_act(card_id: str, body: ActBody, user=Depends(current)):
        access(GID, user)
        payload = {'option': body.option, 'enabled': body.enabled}
        return await act_on_card(agent, card_id, body.action, payload, user['id'])

    @app.get('/api/care/calendar/{appt_id}.ics')
    def care_calendar(appt_id: str):
        return calendar_ics(appt_id)

    @app.get('/api/demo/state')
    def demo_state_route(user=Depends(current)):
        access(GID, user)
        return demo_state()

    @app.post('/api/demo/reset')
    async def demo_reset(user=Depends(current)):
        access(GID, user)
        from .care_seed import reset
        reset()
        asyncio.create_task(warmup())
        await agent.broadcast(GID, {'type': 'refresh'})
        await agent.broadcast(GID, {'type': 'reset'})
        return demo_state()

    @app.post('/api/demo/steps/{key}')
    async def demo_step(key: str, user=Depends(current)):
        access(GID, user)
        return await run_step(agent, key, user)

    @app.post('/api/demo/clock')
    async def demo_clock(body: ClockBody, user=Depends(current)):
        access(GID, user)
        await advance_to(agent, democlock.now() + (body.advance_minutes or 60) * 60, f'+{body.advance_minutes or 60} 分钟')
        await tick_now(agent)
        return demo_state()

    @app.post('/api/demo/say')
    async def demo_say(body: SayBody, user=Depends(current)):
        access(GID, user)
        return {'id': await post_as(agent, body.user, body.content)}


# ---------------------------------------------------------------- 给大模型的只读工具：家庭健康概况
async def family_health(ctx, args):
    data = dashboard()
    return {'clock': data['clock']['label'], 'members': [{k: m[k] for k in ('name', 'real_name', 'age', 'conditions', 'allergies', 'tag', 'adherence', 'plan')} for m in data['members']],
            'upcoming': data['upcoming'], 'profile': [p['content'] for p in data['profile'] if p['domain'] == 'medical']}


def _register():
    from .skills import Tool, register, schema, REGISTRY
    if 'family_health' in REGISTRY:
        return
    register(Tool('family_health', '只读：查看家里每个人的健康概况——病史、在吃的药、本周用药依从率、守护计划进度、即将到来的就诊与复诊。',
                  schema({}), family_health))
    REGISTRY['family_health'].instructions = ('家人问“爸这周药吃了吗”“妈下次什么时候复查”“家里最近谁看过病”时调用。'
                                              '按返回数据简短回答，不诊断、不调整用药；没有记录就说没有记录。')


_register()
