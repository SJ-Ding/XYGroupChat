"""家人帮 · 就医守护编排测试：号源确定性、授权与支付、规则/大模型双通道、守护计划、依从性、急症拦截。"""
import pytest
from fastapi.testclient import TestClient

from backend import care, care_seed, democlock
from backend import hospital_data as H
from backend.agent import Agent
from backend.db import DB, Message, User, get
from backend.model import Model


async def no_broadcast(*args):
    pass


class CareModel:
    """按调用阶段返回结构化结果的假模型；记录调用次数。"""

    def __init__(self, booking=None, plan=None, questions=None, hint=None):
        self.booking, self.plan, self.questions, self.hint = booking, plan, questions, hint
        self.calls = []

    async def call(self, messages, tools=None, structured=False):
        system = messages[0]['content']
        self.calls.append(system[:20])
        if '挂号理解' in system and self.booking is not None:
            return dict(self.booking)
        if '病历结构化' in system and self.plan is not None:
            return dict(self.plan)
        if '复诊准备' in system and self.questions is not None:
            return {'questions': self.questions}
        if '需求判断' in system and self.hint is not None:
            return dict(self.hint)
        raise RuntimeError('模型不可用')


@pytest.fixture(autouse=True)
def demo_family():
    care_seed.reset()
    yield
    democlock.reset()


def make_agent(model=None):
    a = Agent(no_broadcast, model or Model(), now=democlock.now)
    care.set_agent(a)
    return a


def message(login, content):
    with DB() as db:
        uid = db.query(User).filter_by(username=login).first().id
        m = Message(group_id=1, user_id=uid, client_id='t-' + content[:20], content=content, attachments='[]')
        db.add(m)
        db.commit()
        return m


def care_cards(ctype):
    return care.cards_of(ctype)


def test_seed_family_profile_and_dashboard():
    d = care.dashboard()
    names = {m['login']: m for m in d['members']}
    assert names['mom']['real_name'] == '王秀兰' and names['child']['name'] == '小林'
    assert names['dad']['adherence']['taken'] == 5 and names['dad']['adherence']['total'] == 7
    assert names['dad']['tag'] == '本周漏服 2 次'
    assert any('张明远' in p['content'] for p in d['profile'])
    assert d['clock']['day'] == 0 and d['clock']['label'].endswith('20:10')


def test_slots_are_deterministic_and_story_slots_pinned():
    first, second = H.generate_slots(), H.generate_slots()
    assert first == second
    tomorrow = democlock.shift_date(democlock.today(), 1)
    familiar = [s for s in H.find_slots('d-guke', tomorrow, 'morning', 'c-main', 'doc-g1')]
    assert any(s['startTime'] == '08:30' and s['status'] == 'available' for s in familiar)
    east = H.find_slots('d-guke', tomorrow, 'morning', 'c-east')
    assert east and all(s['status'] != 'available' for s in east)
    assert H.slot(familiar[0]['id'])['id'] == familiar[0]['id']


def test_booking_without_child_authorization_decrements_slot():
    tomorrow = democlock.shift_date(democlock.today(), 1)
    slot = next(s for s in H.find_slots('d-guke', tomorrow, 'morning', 'c-main', 'doc-g1') if s['startTime'] == '08:30')
    with DB() as db:
        appt = H.create_appointment(db, slot['id'], 'p-001', 'task-1')
        again = H.create_appointment(db, slot['id'], 'p-001', 'task-1')
        db.commit()
    assert again['id'] == appt['id'] and appt['pay_status'] == 'unpaid'
    assert H.slot(slot['id'])['remaining'] == slot['remaining'] - 1


@pytest.mark.asyncio
async def test_one_sentence_booking_ranks_options_with_rules_only(monkeypatch):
    captured = {}
    async def fake_start(agent, user_id, option, meta, **kwargs):
        captured.update(option=option, meta=meta)
        return "task"
    monkeypatch.setattr(care, "start_booking", fake_start)
    a = make_agent()
    m = message('child', '@小艺 帮我妈挂明天上午的号')
    assert await care.on_message(a, 1, m) is True
    assert not care_cards('hospital_options')
    assert captured['meta']['patient'] == 'mom'
    assert captured['meta']['department'] == '骨科'
    assert captured['option']['doctor'] == '张明远'
    assert captured['option']['hospital_id']
    assert not captured['option']['needs_approval']



@pytest.mark.asyncio
async def test_model_fills_slots_when_rules_cannot(monkeypatch):
    captured = {}
    async def fake_start(agent, user_id, option, meta, **kwargs):
        captured.update(meta)
        return "task"
    monkeypatch.setattr(care, "start_booking", fake_start)
    model = CareModel(booking={'patient': 'dad', 'department': '心血管内科', 'date': None, 'session': 'morning',
                               'reply': '好，给爸爸约心内科的号。'})
    a = make_agent(model)
    m = message('child', '@小艺 帮忙挂个号，最近头胀血压高')
    assert await care.on_message(a, 1, m) is True
    assert captured['patient'] == 'dad' and captured['department'] == '心血管内科'
    assert any(s['kind'] == 'llm' for s in care.trace_list()[0]['steps'])


@pytest.mark.asyncio
async def test_rules_reject_negation_and_non_medical_appointments():
    a = make_agent()
    assert await care.on_message(a, 1, message('child', '不用挂号了，妈妈好多了')) is False
    assert await care.on_message(a, 1, message('dad', '我们约了周六3号见')) is False


@pytest.mark.asyncio
async def test_elder_symptom_creates_hint_once_per_two_hours():
    a = make_agent()
    assert await care.on_message(a, 1, message('mom', '今天阴天，膝盖又酸又胀')) is True
    hint = care_cards('need_hint')[-1]['care']['data']
    assert hint['department'] == '骨科' and hint['member'] == 'mom'
    assert await care.on_message(a, 1, message('mom', '膝盖还是疼')) is False


@pytest.mark.asyncio
async def test_emergency_is_rule_based_and_skips_model():
    model = CareModel()
    a = make_agent(model)
    assert care.red_flag('胸口疼得厉害，有点喘不上气')
    assert care.red_flag('他嘴歪了，说话不清楚')
    assert not care.red_flag('今天胸口有点闷，可能没睡好')
    assert await care.on_message(a, 1, message('dad', '胸口疼得厉害，有点喘不上气')) is True
    card = care_cards('emergency')[-1]['care']['data']
    assert card['call'] == '120' and card['notified'] == '小林'
    assert model.calls == []


@pytest.mark.asyncio
async def test_visit_plan_adherence_and_followup_briefing():
    a = make_agent(CareModel(questions=['能开始慢走了吗？', '消炎药还吃吗？', '多久再复查？']))
    await care.complete_visit(a)
    plan = care_cards('care_plan')[-1]
    assert {i['type'] for i in plan['care']['data']['items']} == {'medication', 'rehab', 'followup'}
    await care.act_on_card(a, plan['id'], 'confirm_plan', None, 3)
    follow = care.items('followup')[0]
    # 快进到第 7 天早上：爸爸本周漏服 2 次，今天的还没打卡
    await care.advance_to(a, democlock.at(democlock.shift_date(care_seed.day0(), 7), '08:20'), '测试')
    report = await care.adherence_report('dad')
    d = report['care']['data']
    assert d['missed'] and len(d['missed']) == 2 and d['today_pending']
    await care.act_on_card(a, report['id'], 'nudge', None, 3)
    checkin = care_cards('med_checkin')[-1]
    await care.act_on_card(a, checkin['id'], 'taken', None, 1)
    assert care.card_data(report['id'])['care']['data']['taken'] == d['taken'] + 1
    # 复诊前一天晚上：自动生成简报与上次医生的号
    await care.advance_to(a, follow['briefing_at'] + 30, '测试')
    await care.tick_now(a)
    brief = care_cards('followup')[-1]['care']['data']
    assert brief['option']['doctor'] == '张明远' and brief['day_n'] == 14
    assert brief['medication']['taken'] == 13 and brief['rehab']['taken'] == 12
    assert brief['questions'][0] == '能开始慢走了吗？' and brief['generated_by'] == 'llm'


def test_demo_api_reset_state_and_calendar():
    from backend.app import app
    with TestClient(app) as client:
        client.params = {'user': 'child'}
        headers = {'Origin': 'http://testserver'}
        state = client.post('/api/demo/reset', headers=headers).json()
        assert state['clock']['day'] == 0 and len(state['steps']) == 6
        board = client.get('/api/care/dashboard').json()
        assert len(board['members']) == 3
        hospital = client.get('/api/hospital/state').json()
        assert hospital['today'] == democlock.today() and hospital['slots']
        assert any(a['id'] == 'AP-HIS0001' for a in hospital['appointments'])
        assert client.get('/api/care/calendar/AP-HIS0001.ics').text.startswith('BEGIN:VCALENDAR')
        assert client.post('/api/hospital/appointments/AP-HIS0001/pay', json={'token': 'bad'}, headers=headers).status_code == 403

@pytest.mark.asyncio
async def test_query_department_without_patient_never_books(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError('read-only query must not book')
    monkeypatch.setattr(care, 'start_booking', forbidden)
    a = make_agent()
    m = message('child', '@小艺 查询骨科号源')
    assert await care.on_message(a, 1, m)
    with DB() as db:
        reply = db.query(Message).filter_by(group_id=1, user_id=0).order_by(Message.id.desc()).first()
        assert '模拟号源' in reply.content
        assert all(c['name'] in reply.content for c in H.catalog()['campuses'])
