import uuid
import pytest
from backend.appointment_intent import appointment_operation,appointment_time
from backend import care,care_seed,democlock,hospital_data as H
from backend.agent import Agent
from backend.db import DB,Message,User,get,put,records
from backend.model import Model
from backend.hospital_simulator import hospital_simulator
from backend.skills import SkillContext

@pytest.mark.parametrize('text',[
    '明天下午四点的号有吗','明天下午4点的号还有吗','明天16:00的号能约吗',
])
def test_time_first_availability_questions_are_queries(text):
    assert appointment_operation(text)=='query'

@pytest.mark.parametrize('text,expected',[
    ('明天下午四点','16:00'),('下午四点半','16:30'),('上午九点十五分','09:15'),
    ('16:00','16:00'),('下午4:05','16:05'),('明天下午','None'),('25:00','None'),
])
def test_exact_time_parser(text,expected):
    assert appointment_time(text)==(None if expected=='None' else expected)

@pytest.fixture
def family():
    care_seed.reset()
    yield
    democlock.reset()

async def no_broadcast(*args):pass

@pytest.mark.asyncio
@pytest.mark.parametrize('has_exact_slot',[True,False])
async def test_original_message_searches_exact_time_without_booking(family,monkeypatch,has_exact_slot):
    tomorrow=democlock.shift_date(democlock.today(),1)
    slot=next(s for s in H.find_slots('d-guke',tomorrow,'afternoon','c-main') if s['status']=='available')
    nearby={**slot,'id':'nearby','startTime':'14:00','status':'available'}
    exact={**slot,'id':'exact','startTime':'16:00','status':'available'}
    full={**slot,'id':'full','startTime':'16:00','status':'full','remaining':0}
    monkeypatch.setattr(H,'generate_slots',lambda dates=None:[nearby,full]+([exact] if has_exact_slot else []))
    async def forbidden(*args,**kw):raise AssertionError('an availability question must not book')
    monkeypatch.setattr(care,'start_booking',forbidden)
    a=Agent(no_broadcast,Model(),now=democlock.now)
    with DB() as db:
        uid=db.query(User).filter_by(username='mom').one().id
        m=Message(group_id=1,user_id=uid,client_id=uuid.uuid4().hex,content='明天下午四点的号有吗',attachments='[]')
        db.add(m);db.flush()
        put(db,'job',1,str(m.id),{'source':m.id,'mention':False,'status':'pending','analyzed':False,'settings':get(db,'group',1,'settings').data})
        db.commit()
    await a.process(1,str(m.id))
    with DB() as db:
        text=db.query(Message).filter_by(user_id=0).order_by(Message.id.desc()).first().content
        assert '16:00' in text and '14:00' not in text
        assert ('余' in text) == has_exact_slot
        if not has_exact_slot:assert '暂无符合条件' in text
        assert get(db,'job',1,str(m.id)).data['care_handled']
    assert any('family-appointment' in s['label'] for t in care.trace_list() for s in t['steps'])
    assert not care.cards_of('hospital_apps')
    await a.close()

@pytest.mark.asyncio
async def test_query_tool_honors_exact_time(family,monkeypatch):
    tomorrow=democlock.shift_date(democlock.today(),1)
    slot=next(s for s in H.find_slots('d-guke',tomorrow,'afternoon','c-main') if s['status']=='available')
    monkeypatch.setattr(H,'generate_slots',lambda dates=None:[{**slot,'startTime':'14:00'},{**slot,'startTime':'16:00'}])
    result=await hospital_simulator(SkillContext(1,3,'clock-query',0),{'action':'query','department':'骨科','date':tomorrow,'time':'16:00'})
    assert result['slots'] and all(s['startTime']=='16:00' for s in result['slots'])


def test_24_hour_clock_keeps_afternoon_even_without_period_word():
    slots=care.rule_slots('明天16:00的号有吗','mom')
    assert slots['time']=='16:00' and slots['session']=='afternoon'
