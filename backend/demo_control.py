"""Opt-in controls for the seeded demo family; never grant business permissions."""
import asyncio
import time
from fastapi import HTTPException
from pydantic import BaseModel
from .db import DB, get, put, records

GID = 1


def controls():
    with DB() as db:
        r = get(db, 'demo_control', GID, 'state')
        return r.data if r else {'enabled': False, 'model': False, 'amap': False, 'slow': True}


def fault(name, gid=GID):
    state = controls() if gid == GID else {}
    return bool(state.get('enabled') and state.get(name))


class ControlBody(BaseModel):
    enabled: bool | None = None
    model: bool | None = None
    amap: bool | None = None
    slow: bool | None = None


def configure(body):
    with DB() as db:
        if not get(db, 'demo', GID, 'state'):
            raise HTTPException(409, '请先初始化演示家庭')
        value = {**controls(), **body.model_dump(exclude_none=True)}
        if not value['enabled']:
            value.update(model=False, amap=False)
        put(db, 'demo_control', GID, 'state', value)
        db.commit()
    return value


# These buttons enqueue ordinary messages, not alternate business implementations.
BRANCHES = [
    ('query', 'P0', '指定医院查号', 'child', '@小艺 鼓楼医院骨科明天还有号吗'),
    ('book', 'P0', '一句话挂号', 'child', '@小艺 帮妈妈挂明天上午江苏省人民医院骨科的号'),
    ('time', 'P0', '改成下午', 'child', '@小艺 换成下午的吧，先核对原预约状态'),
    ('hospital', 'P0', '换一家医院', 'child', '@小艺 换另一家医院看看，先核对原预约状态'),
    ('cancel', 'P0', '取消挂号', 'child', '@小艺 算了，取消刚才的挂号'),
    ('full', 'P0', '今天没有号', 'child', '@小艺 帮妈妈查今天的骨科号'),
    ('missing', 'P0', '信息不全', 'child', '@小艺 帮我挂个号'),
    ('pay', 'P0', '请求代付', 'child', '@小艺 直接帮我付挂号费'),
    ('diagnose', 'P0', '请求诊断', 'child', '@小艺 帮我看看妈妈这是什么病'),
    ('medicine', 'P0', '请求买药', 'child', '@小艺 帮妈妈买点止痛药'),
    ('emergency', 'P0', '急症插队', 'dad', '胸口疼得厉害，有点喘不上气'),
    ('text_record', 'P1', '文字医嘱', 'child', '医生开了醋氯芬酸片 0.1g 每日2次 吃3天，1周后骨科复诊'),
    ('refuse', 'P1', '长辈拒绝就医', 'mom', '我不想去医院，排队太麻烦了'),
    ('chat', 'P1', '普通闲聊', 'child', '@小艺 今晚吃什么好'),
    ('source', 'P1', '追问记忆来源', 'child', '@小艺 你怎么知道妈妈有半月板旧伤'),
    ('forget', 'P1', '删除刚才的记忆', 'child', '@小艺 忘掉刚才那条记忆'),
]


def branches():
    return [{'key': k, 'priority': p, 'title': t, 'actor': a, 'line': s} for k,p,t,a,s in BRANCHES] + [
        {'key': 'slot_taken', 'priority': 'P0', 'title': '注入号源被抢', 'actor': 'system', 'line': '在浏览器填表时占满选中号源'},
        {'key': 'double_click', 'priority': 'P2', 'title': '同时点击两次选号', 'actor': 'system', 'line': '需要一张有效号源卡'},
        {'key': 'dual', 'priority': 'P2', 'title': '两人同时提出挂号', 'actor': 'system', 'line': '发送两位成员的请求，观察任务隔离'},
    ]


async def run_branch(agent, key):
    if not controls().get('enabled'):
        raise HTTPException(409, '请先启用演示控制')
    from . import care, hospital_data as H
    care.set_agent(agent)
    branch = next((b for b in BRANCHES if b[0] == key), None)
    if branch:
        await care.post_as(agent, branch[3], branch[4])
    elif key == 'slot_taken':
        from .hospital_simulator import automation
        with automation._lock:
            sessions = [s for s in automation.sessions.values() if s.gid == GID and s.status == 'starting' and not s.stop.is_set() and s.context.get('slot_id')]
        if len(sessions) != 1:
            raise HTTPException(409, '需要唯一一个正在填表的浏览器任务')
        with DB() as db:
            try:
                count = H.occupy_slot(db, sessions[0].context['slot_id'])
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from None
            db.commit()
        await care.Trace('演示注入：号源被抢').step('rule', '模拟号源被其他患者占满', f'占用 {count} 个号，提交时由医院校验')
    elif key == 'double_click':
        cards = [c for c in care.cards_of('hospital_options') if c['status'] == 'active' and c['care']['data'].get('options')]
        if not cards:
            raise HTTPException(409, '请先生成一张有效号源卡')
        card = cards[-1]
        results = await asyncio.gather(*(care.act_on_card(agent, card['id'], 'choose', {'option': card['care']['data']['options'][0]['id']}, care.ids()[care.CAREGIVER]) for _ in range(2)), return_exceptions=True)
        await care.Trace('演示验证：重复点击').step('rule', '同一卡片并发点击', f'{sum(not isinstance(r, Exception) for r in results)} 次正常返回；实际任务请查看执行链')
    elif key == 'dual':
        await asyncio.gather(care.post_as(agent, 'mom', '@小艺 帮我挂明天上午江苏省人民医院骨科的号'), care.post_as(agent, 'child', '@小艺 给爸爸挂明天上午江苏省人民医院心内科的号'))
    else:
        raise HTTPException(404, '未知演示支线')
    await agent.broadcast(GID, {'type': 'refresh'})
    return {'ok': True}


def status():
    from . import care
    from .care_aftercare import vision_model
    from .hospital_simulator import automation, AppointmentManager
    with DB() as db:
        calls = records(db, 'metric', GID)
        last = calls[-1].data if calls else None
        maps = get(db, 'demo_service', GID, 'amap')
    with automation._lock:
        sessions = [dict(s.snapshot(), run_key=s.run_key) for s in automation.sessions.values() if s.gid == GID]
    return {'controls': controls(), 'branches': branches(), 'vision': vision_model(),
            'model_last': {'failed': last.get('failed'), 'at': last.get('at')} if last else None,
            'amap_last': maps.data if maps else None,
            'distance_sources': sorted({v[2] for v in care._DIST_CACHE.values()}),
            'browser_pause_ms': AppointmentManager._pause(), 'browser_tasks': sessions[-5:]}


def record_map(ok):
    with DB() as db:
        put(db, 'demo_service', GID, 'amap', {'ok': ok, 'at': time.time()})
        db.commit()


def install_routes(app, current, access, agent):
    from fastapi import Depends
    @app.post('/api/demo/control')
    async def control(body: ControlBody, user=Depends(current)):
        access(GID, user)
        value = configure(body)
        await agent.broadcast(GID, {'type': 'refresh'})
        return value

    @app.post('/api/demo/branches/{key}')
    async def branch(key: str, user=Depends(current)):
        access(GID, user)
        return await run_branch(agent, key)
