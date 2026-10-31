import json
import uuid
import pytest
from backend.addressing import direct_mention, strip_assistant_address
from backend.appointment_intent import appointment_operation
from backend.authorization import command_grants
from backend.contracts import ConversationEvent, Intent
from backend.participation import decide
from backend import care, care_seed, democlock, prognosis
from backend.agent import Agent
from backend.db import DB, Message, User, get, put, records

@pytest.mark.parametrize('text',[
    '预定明天下午的号@小艺', '帮我@小艺查一下号源', '@小艺预订明天骨科的号',
    '明天的号帮我看一下，@小艺，谢谢', '帮我预订门诊＠小艺', '@小忆，查一下号源',
    '小艺，今天有点累', '这张药单@小艺识别一下', '@小艺分析一下刚才的方案', '“有人说明天没号” @小艺，帮我查一下',
])
def test_mentions_in_actual_text(text):
    assert direct_mention(text,'小艺')

@pytest.mark.parametrize('text',[
    '妈妈说小艺今天很忙', '妈妈说：“预定明天的号@小艺”', '> @小艺 帮忙挂号',
    '引用：@小艺 记住这件事', '```\n@小艺 帮忙挂号\n```', '@小艺术 帮忙',
    '“@小艺 帮忙挂号', '他说“@小艺”', 'mail@小艺.example',
])
def test_quoted_or_other_addresses_are_not_mentions(text):
    assert not direct_mention(text,'小艺')

@pytest.mark.parametrize('text,operation',[
    ('预定明天下午的号@小艺','book'), ('预订一个骨科门诊','book'), ('帮妈妈排个门诊','book'),
    ('帮我约明天的号','book'), ('明天下午骨科还有号吗','query'), ('查询挂号号源','query'),
    ('看看明天有没有号@小艺','query'), ('先查骨科号源然后帮我挂号','book'),
    ('我们约了周六3号见',None), ('妈妈已经挂好了号',None), ('不要预定明天的号',None),
    ('“预定明天的号@小艺”',None), ('假设要预约明天骨科的号',None), ('预定明天的电影票',None),
])
def test_shared_appointment_phrases(text,operation):
    assert appointment_operation(text)==operation


def test_inline_address_stripping_preserves_quoted_data_and_reminder_grants():
    assert strip_assistant_address('记住她说“@小艺 你好”@小艺','小艺') == '记住她说“@小艺 你好”'
    grants=command_grants('五分钟后提醒我吃药@小艺','小艺',1000)
    assert grants[0]['tool']=='group_reminder'
    assert grants[0]['arguments']=={'content':'吃药','at':1300}
    assert not command_grants('妈妈说：“五分钟后提醒我吃药@小艺”','小艺',1000)


def test_clear_semantic_requests_do_not_need_fixed_words():
    event=ConversationEvent(1,2,3,'这份方案压缩成三条',1000)
    intent=Intent(kind='request',target='agent',confidence=.95,assistant_helpful=True)
    assert decide(event,intent,{'active':False}).action=='reply'
    assert decide(event,Intent(kind='discussion',confidence=.99),{'active':True}).action=='silent'


class RoutingModel:
    def __init__(self, operation='book', quoted=False):
        self.operation=operation;self.quoted=quoted;self.calls=[]
    async def call(self,messages,structured=False,**kwargs):
        self.calls.append(messages)
        if '决定本次预约' in messages[0]['content']:
            payload=json.loads(messages[-1]['content'])
            department=next(d for d in payload['catalog']['departments'] if d['name']=='骨科')
            slot=next(s for s in payload['available_slots']
                      if s['departmentId']==department['id'] and s['session']=='afternoon')
            return {'patient':'mom','slot_id':slot['id'],'reason':'测试选择下午骨科号源'}
        if '挂号理解' in messages[0]['content']:
            return {'patient':'mom','department':'骨科','date':democlock.shift_date(democlock.today(),1),'session':'afternoon'}
        if structured:
            return {'intent':{'kind':'request','target':'agent','confidence':.95,'quoted':self.quoted,
                'assistant_helpful':True,'scene':'family-appointment','operation':self.operation},'memories':[],'updates':[],'new_need':None}
        return {'role':'assistant','content':'请告诉我还缺的关键信息。'}

async def no_broadcast(*args):pass

@pytest.fixture
def family():
    care_seed.reset()
    yield
    democlock.reset()


def source(login,text,mention=None):
    with DB() as db:
        uid=db.query(User).filter_by(username=login).one().id
        settings=get(db,'group',1,'settings').data
        m=Message(group_id=1,user_id=uid,client_id=uuid.uuid4().hex,content=text,attachments='[]')
        db.add(m);db.flush()
        put(db,'job',1,str(m.id),{'source':m.id,'mention':direct_mention(text,settings['agent_name']) if mention is None else mention,
            'settings':settings,'status':'pending','analyzed':False})
        db.commit()
        return m

@pytest.mark.asyncio
async def test_original_utterance_uses_agent_and_preserves_afternoon(family,monkeypatch):
    captured={}
    async def fake_start(agent,user_id,option,meta,**kwargs):
        captured.update(option=option,meta=meta)
        return 'task'
    monkeypatch.setattr(care,'start_booking',fake_start)
    model=RoutingModel();a=Agent(no_broadcast,model,now=democlock.now)
    m=source('mom','预定明天下午的号@小艺')
    await a.process(1,str(m.id))
    assert captured['option']['session']=='afternoon'
    assert captured['meta']['patient']=='mom'
    assert not care.cards_of('hospital_apps')
    assert any('family-appointment' in s['label'] for turn in care.trace_list() for s in turn['steps'])
    assert not [call for call in model.calls if '家庭会话理解器' in call[0]['content']]
    await a.close()

@pytest.mark.asyncio
@pytest.mark.parametrize('operation,kind',[('query','hospital_options'),('book','hospital_apps')])
async def test_semantic_scene_routes_paraphrases_without_fast_keywords(family,monkeypatch,operation,kind):
    captured={}
    async def fake_start(agent,user_id,option,meta,**kwargs):
        captured.update(option=option,meta=meta)
        return 'task'
    monkeypatch.setattr(care,'start_booking',fake_start)
    a=Agent(no_broadcast,RoutingModel(operation),now=democlock.now)
    m=source('child','妈妈膝盖这件事，明天下午给她安排一下@小艺')
    assert not appointment_operation(m.content)
    await a.process(1,str(m.id))
    if operation=='query':
        assert care.cards_of(kind)
        assert not care.cards_of('hospital_apps')
        assert not captured
    else:
        assert captured['meta']['patient']=='mom'
        assert captured['option']['session']=='afternoon'
        assert not care.cards_of('hospital_apps')
        assert not care.cards_of('hospital_options')
    with DB() as db:
        assert get(db,'job',1,str(m.id)).data['replied']
    await a.close()

@pytest.mark.asyncio
async def test_missing_patient_gets_clarification_instead_of_silence(family):
    class UnknownPatient(RoutingModel):
        async def call(self,messages,**kwargs):
            if '决定本次预约' in messages[0]['content']:
                return {'question':'给妈妈还是爸爸预约？'}
            return await super().call(messages,**kwargs)
    a=Agent(no_broadcast,UnknownPatient(),now=democlock.now)
    m=source('child','预定明天下午的号@小艺')
    await a.process(1,str(m.id))
    with DB() as db:
        reply=db.query(Message).filter_by(user_id=0).order_by(Message.id.desc()).first()
        assert '给妈妈还是爸爸' in reply.content
        assert not care.cards_of('hospital_apps')
    await a.close()

@pytest.mark.asyncio
async def test_stale_mention_flag_cannot_override_quoted_decision(family):
    a=Agent(no_broadcast,RoutingModel(quoted=True),now=democlock.now)
    m=source('child','妈妈说：“预定明天下午的号@小艺”',mention=True)
    await a.process(1,str(m.id))
    with DB() as db:
        assert get(db,'job',1,str(m.id)).data['decision']['action']=='silent'
        assert not db.query(Message).filter_by(client_id='mention:'+str(m.id)).first()
    assert not care.cards_of('hospital_apps')
    await a.close()

@pytest.mark.asyncio
async def test_emergency_precedes_pending_prognosis(family,monkeypatch):
    a=Agent(no_broadcast,RoutingModel(),now=democlock.now)
    m=source('dad','胸口疼得厉害，有点喘不上气')
    with DB() as db:
        put(db,'prognosis_pending',1,str(m.user_id),{'active':True,'at':democlock.now()});db.commit()
    async def forbidden(*args):raise AssertionError('urgent message must not enter prognosis model')
    monkeypatch.setattr(prognosis,'handle_request',forbidden)
    await a.process(1,str(m.id))
    assert care.cards_of('emergency')
    await a.close()

@pytest.mark.asyncio
async def test_explicit_reminder_bypasses_medical_plan_parser(family,monkeypatch):
    a=Agent(no_broadcast,RoutingModel(),now=democlock.now)
    m=source('dad','十五分钟后提醒我吃药@小艺')
    async def forbidden(*args):raise AssertionError('single reminder is not an EMR plan')
    monkeypatch.setattr(prognosis,'handle_request',forbidden)
    await a.process(1,str(m.id))
    with DB() as db:
        assert any(r.data['content']=='吃药' for r in records(db,'reminder',1))
    await a.close()

@pytest.mark.asyncio
async def test_real_message_api_recognizes_trailing_mention(family,monkeypatch):
    import httpx
    from backend.app import app,agent as server_agent
    captured={}
    async def fake_start(agent,user_id,option,meta,**kwargs):
        captured.update(option=option,meta=meta)
        return 'task'
    monkeypatch.setattr(care,'start_booking',fake_start)
    previous=server_agent.model
    server_agent.model=RoutingModel()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
            response=await client.post('/api/groups/1/messages?user=mom',json={'client_id':'inline-real-api','content':'预定明天下午的号@小艺'})
            assert response.status_code==200
            mid=response.json()['id']
            with DB() as db:
                assert get(db,'job',1,str(mid)).data['mention']
            await server_agent.process(1,str(mid))
            assert captured['option']['session']=='afternoon'
            assert captured['meta']['patient']=='mom'
    finally:
        await server_agent.close()
        server_agent.model=previous


def test_persisted_companion_prompt_is_upgraded_without_duplicating_or_losing_custom_text():
    from backend.persona import companion_prompt,system_prompt,REQUEST_GUIDANCE
    previous=companion_prompt().replace(REQUEST_GUIDANCE+'\n','')
    result=system_prompt({'agent_name':'小艺','prompt':previous+'\n只使用简短中文回复。'})
    assert result.count('陪伴型管家')==1
    assert REQUEST_GUIDANCE in result
    assert result.endswith('只使用简短中文回复。')
