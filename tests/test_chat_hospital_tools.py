import uuid
from dataclasses import replace
import pytest
from backend import care,care_seed,democlock,hospital_data as H
from backend.agent import Agent
from backend.db import DB,Message,User,get,put,records
from backend.execution_chain import query
from backend.model import Model
from backend.skills import REGISTRY

@pytest.fixture
def family():
    care_seed.reset()
    yield
    democlock.reset()

async def no_broadcast(*args):pass


def request(text):
    with DB() as db:
        uid=db.query(User).filter_by(username='child').one().id
        message=Message(group_id=1,user_id=uid,client_id=uuid.uuid4().hex,content=text,attachments='[]')
        db.add(message);db.flush()
        put(db,'job',1,str(message.id),{'source':message.id,'mention':False,'status':'pending','analyzed':False,
            'settings':get(db,'group',1,'settings').data})
        db.commit()
        return message

@pytest.mark.asyncio
@pytest.mark.parametrize('text,exact',[
    ('帮妈妈查一下明天下午四点的骨科号@小艺',True),
    ('帮妈妈查一下明天下午骨科号@小艺',False),
    ('查询明天下午骨科号源',False),
])
async def test_all_chat_query_branches_use_real_executor_and_persist_results(family,monkeypatch,text,exact):
    tomorrow=democlock.shift_date(democlock.today(),1)
    slot=next(s for s in H.find_slots('d-guke',tomorrow,'afternoon','c-jsph') if s['status']=='available')
    slot={**slot,'id':'tool-only','startTime':'16:00','remaining':7}
    calls=[]
    async def provider(ctx,args):
        calls.append((ctx,args))
        return {'slots':[slot],'simulated':True,'query':args}
    monkeypatch.setitem(REGISTRY,'hospital_simulator',replace(REGISTRY['hospital_simulator'],execute=provider))
    def forbidden(*args,**kw):raise AssertionError('chat must not bypass the query tool')
    monkeypatch.setattr(H,'generate_slots',forbidden)
    monkeypatch.setattr(H,'find_slots',forbidden)
    a=Agent(no_broadcast,Model(),now=democlock.now)
    message=request(text)
    await a.process(1,str(message.id))
    assert len(calls)==1
    ctx,args=calls[0]
    assert args['action']=='query' and args['department']=='骨科'
    assert args['date']==tomorrow and args['preferred_time']=='下午'
    assert args.get('time')==('16:00' if exact else None)
    assert ctx.source_id==message.id and ctx.user_id==message.user_id
    with DB() as db:
        receipts=[r.data for r in records(db,'tool',1) if r.data.get('source_id')==message.id]
        assert {r['name'] for r in receipts}=={'skill_load','hospital_simulator'}
        result=next(r['result'] for r in receipts if r['name']=='hospital_simulator')
        assert result['slots'][0]['remaining']==7
    chain=query(1,[message.id])[str(message.id)]['steps']
    assert chain[0]['kind']=='skill' and 'family-appointment' in chain[0]['title']
    tool=next(s for s in chain if 'hospital_simulator' in s['title'])
    assert tool['status']=='succeeded' and '1 个号源' in tool['summary']
    assert not care.cards_of('hospital_apps') and not care.cards_of('payment')
    await a.close()

@pytest.mark.asyncio
async def test_query_failure_is_logged_and_never_reported_as_no_slots(family,monkeypatch):
    async def broken(ctx,args):return {'error':'模拟查询服务不可用'}
    monkeypatch.setitem(REGISTRY,'hospital_simulator',replace(REGISTRY['hospital_simulator'],execute=broken))
    a=Agent(no_broadcast,Model(),now=democlock.now)
    message=request('帮妈妈查明天下午四点骨科的号有吗')
    await a.process(1,str(message.id))
    with DB() as db:
        reply=db.query(Message).filter_by(user_id=0).order_by(Message.id.desc()).first().content
        assert '查询暂时失败' in reply and '暂无符合条件' not in reply
    steps=query(1,[message.id])[str(message.id)]['steps']
    assert any('hospital_simulator' in s['title'] and s['status']=='failed' for s in steps)
    await a.close()

@pytest.mark.asyncio
async def test_missing_department_loads_skill_without_running_an_invalid_query(family):
    a=Agent(no_broadcast,Model(),now=democlock.now)
    message=request('明天下午四点的号有吗')
    await a.process(1,str(message.id))
    with DB() as db:
        receipts=[r.data for r in records(db,'tool',1) if r.data.get('source_id')==message.id]
        assert len(receipts)==1 and receipts[0]['name']=='skill_load'
        reply=db.query(Message).filter_by(user_id=0).order_by(Message.id.desc()).first().content
        assert '科室' in reply
    await a.close()

@pytest.mark.asyncio
async def test_two_real_chat_messages_have_distinct_fresh_query_receipts(family,monkeypatch):
    import httpx
    from backend.app import app,agent
    tomorrow=democlock.shift_date(democlock.today(),1)
    slot=next(s for s in H.find_slots('d-guke',tomorrow,'afternoon','c-jsph') if s['status']=='available')
    calls=[]
    async def provider(ctx,args):
        calls.append((ctx.source_id,args))
        remaining=7 if len(calls)==1 else 0
        return {'slots':[{**slot,'startTime':'16:00','remaining':remaining,
            'status':'available' if remaining else 'full'}],'query':args,'simulated':True}
    monkeypatch.setitem(REGISTRY,'hospital_simulator',replace(REGISTRY['hospital_simulator'],execute=provider))
    previous=agent.model
    agent.model=Model()
    mids=[]
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
            for user,text in [('child','帮妈妈查一下明天下午四点的骨科号@小艺'),('mom','明天下午四点的号有吗')]:
                response=await client.post('/api/groups/1/messages',params={'user':user},
                    json={'client_id':uuid.uuid4().hex,'content':text})
                assert response.status_code==200
                mid=response.json()['id'];mids.append(mid)
                await agent.process(1,str(mid))
        assert [mid for mid,_ in calls]==mids
        assert all(args['action']=='query' and args['time']=='16:00' for _,args in calls)
        with DB() as db:
            receipts=[r.data for r in records(db,'tool',1) if r.data.get('name')=='hospital_simulator']
            assert len(receipts)==2
            assert [r['result']['slots'][0]['remaining'] for r in receipts]==[7,0]
        for mid in mids:
            steps=query(1,[mid])[str(mid)]['steps']
            assert any(s['kind']=='skill' and 'family-appointment' in s['title'] for s in steps)
            assert any('hospital_simulator' in s['title'] and s['status']=='succeeded' for s in steps)
    finally:
        await agent.close()
        agent.model=previous
