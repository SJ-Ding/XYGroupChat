import asyncio
import io
import time
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from backend.app import app, agent
from backend.db import DB, Message, Record, get, put, records, Member
from backend.agent import Agent
from backend.memory import save_memory, delete_memory, search
from backend.skills import execute, SkillContext

class FakeModel:
    def __init__(self, analysis=None):
        self.analysis = analysis or {'intent': {'kind':'request','target':'agent','engagement':'addressed','confidence':.99}, 'new_need': None, 'updates': [], 'memories': [], 'reason': '明确召唤'}
        self.gate = None
        self.calls = []
    async def call(self, messages, tools=None, structured=False):
        self.calls.append((messages, tools))
        if structured:
            return self.analysis
        if self.gate:
            await self.gate.wait()
        return {'role': 'assistant', 'content': '需要我帮忙整理一下吗？'}

async def no_broadcast(*args):
    pass

def seed_demand(key='need', candidate='需要帮忙吗？', deadline=130):
    with DB() as db:
        m = Message(group_id=1, user_id=1, client_id=key, content='小宇，周六能回家吃饭吗？', created=100)
        db.add(m)
        db.flush()
        put(db, 'demand', 1, key, {'text': m.content, 'source': m.id, 'status': 'waiting', 'version': 1, 'candidate': candidate, 'deadline': deadline, 'settings': get(db, 'group', 1, 'settings').data})
        db.commit()
        return m.id

def test_url_identity_chat_upload_and_permissions():
    agent.model = FakeModel()
    with TestClient(app) as client:
        assert client.get('/api/me').status_code == 400
        assert client.get('/api/me?user=unknown').status_code == 400
        client.params = {'user': 'dad'}
        assert client.get('/api/me').json()['username'] == 'dad'
        assert client.get('/api/groups/2/messages').status_code == 403
        payload = {'client_id':'unique','content':'测试消息','attachments':[]}
        first = client.post('/api/groups/1/messages', json=payload).json()
        assert client.post('/api/groups/1/messages', json=payload).json()['id'] == first['id']
        assert len(client.get('/api/groups/1/messages').json()) == 1
        assert len(client.get('/api/groups/1/messages?after=0').json()) == 1
        assert len(client.get('/api/groups/1/messages?around='+str(first['id'])).json()) == 1
        assert client.post('/api/groups/1/uploads', files={'file':('bad.png',b'not an image','image/png')}).status_code == 400
        image=io.BytesIO();Image.new('RGB',(20,20),'green').save(image,format='PNG')
        upload=client.post('/api/groups/1/uploads',files={'file':('x.png',image.getvalue(),'image/png')}).json()
        assert client.get('/api/groups/1/uploads/'+upload['key']).status_code == 200
        assert client.get('/api/groups/2/uploads/'+upload['key']).status_code == 403
        assert client.post('/api/groups/1/messages',json={'client_id':'pic','attachments':[upload['key']]}).status_code == 200

def test_websocket_identity_and_replay():
    agent.model=FakeModel()
    with TestClient(app) as dad, TestClient(app) as mom:
        dad.params = {'user':'dad'}
        mom.params = {'user':'mom'}
        with dad.websocket_connect('/ws/1?user=dad',headers={'origin':'http://testserver'}) as a:
            assert a.receive_json()['type']=='presence'
            with mom.websocket_connect('/ws/1?user=mom',headers={'origin':'http://testserver'}) as b:
                assert b.receive_json()['type']=='presence'
                a.receive_json()
                mom.post('/api/groups/1/messages',json={'client_id':'mom1','content':'来自妈妈'})
                events=[]
                while 'message' not in events:
                    events.append(a.receive_json()['type'])
                rows=dad.get('/api/groups/1/messages?after=0').json()
                assert rows[-1]['name']=='妈妈'

def test_memory_corrections_suppression_and_isolation():
    with DB() as db:
        r=save_memory(db,1,'妈妈喜欢清淡口味',[5],['妈妈'])
        key=r.key
        db.commit()
        assert search(db,1,'妈妈口味')[0]['key']==key
        assert search(db,2,'妈妈口味')==[]
        save_memory(db,1,'妈妈现在喜欢微辣',[5],key=key,manual=True)
        save_memory(db,1,'妈妈喜欢清淡口味',[5],key=key)
        assert get(db,'memory',1,key).data['content']=='妈妈现在喜欢微辣'
        delete_memory(db,get(db,'memory',1,key));db.commit()
        assert search(db,1,'妈妈')==[]
        assert save_memory(db,1,'妈妈喜欢清淡口味',[5]) is None
        assert records(db,'revision',1)

@pytest.mark.asyncio
async def test_candidate_wait_send_once_and_restart():
    seed_demand()
    clock=[129]
    a=Agent(no_broadcast,FakeModel(),lambda:clock[0])
    await a.tick()
    with DB() as db: assert db.query(Message).filter_by(user_id=0).count()==0
    clock[0]=130
    # Recover with a fresh engine instance, using the same durable records.
    b=Agent(no_broadcast,FakeModel(),lambda:clock[0])
    await b.tick();await b.tick()
    with DB() as db:
        assert db.query(Message).filter_by(user_id=0).filter(~Message.client_id.startswith('card:')).count()==1
        assert get(db,'demand',1,'need').data['status']=='sent'
    await a.close();await b.close()

@pytest.mark.asyncio
async def test_responses_cancel_and_unrelated_keep_deadline():
    mid=seed_demand()
    a=Agent(no_broadcast,FakeModel(),lambda:120)
    with DB() as db: m=db.get(Message,mid)
    await a.analyze(1,m)
    with DB() as db: assert get(db,'demand',1,'need').data['deadline']==130
    a.model.analysis={'updates':[{'key':'need','state':'resolved'}], 'reason':'收到回应'}
    await a.analyze(1,m)
    a.now=lambda:200
    await a.tick()
    with DB() as db:
        assert get(db,'demand',1,'need').data['status']=='resolved'
        assert db.query(Message).filter_by(user_id=0).count()==0
    await a.close()

@pytest.mark.asyncio
async def test_slow_generation_and_stale_candidate():
    mid=seed_demand(candidate=None)
    model=FakeModel();model.gate=asyncio.Event()
    a=Agent(no_broadcast,model,lambda:140)
    await a.tick();await asyncio.sleep(.02)
    with DB() as db: assert db.query(Message).filter_by(user_id=0).count()==0
    with DB() as db:
        r=get(db,'demand',1,'need');d=r.data;d.update(version=2,status='resolved');r.set(d);db.commit()
    model.gate.set();await asyncio.sleep(.03);await a.tick()
    with DB() as db:
        assert get(db,'demand',1,'need').data['candidate'] is None
        assert db.query(Message).filter_by(user_id=0).count()==0
    await a.close()

@pytest.mark.asyncio
async def test_changed_need_restarts_observation():
    mid=seed_demand()
    model=FakeModel({'updates':[{'key':'need','state':'changed','text':'改为周日'}]})
    a=Agent(no_broadcast,model,lambda:120)
    with DB() as db:
        m=db.get(Message,mid);m.created=120;db.commit()
    await a.analyze(1,m)
    with DB() as db:
        d=get(db,'demand',1,'need').data
        assert d['deadline']==150 and d['version']==2 and d['candidate'] is None
    await a.close()

@pytest.mark.asyncio
async def test_skills_validation_permission_idempotency():
    ctx=SkillContext(1,1,'run',1,True)
    args={'action':'create','title':'准备晚餐','owner_id':3}
    assert 'error' not in await execute('family_tasks',args,ctx)
    await execute('family_tasks',args,ctx)
    with DB() as db: assert len(records(db,'task',1))==1
    assert 'error' in await execute('family_tasks',{'action':'invalid'},ctx)
    assert 'error' in await execute('remember',{'content':'偏好'},SkillContext(2,1,'run',1,True))
    assert 'error' in await execute('remember',{'content':'偏好'},SkillContext(1,1,'run',1,False))
    await execute('remember',{'content':'爸爸喜欢茶'},ctx)
    await execute('remember',{'content':'爸爸喜欢茶'},ctx)
    with DB() as db: assert len(records(db,'memory',1))==1

@pytest.mark.asyncio
async def test_mention_context_images_and_configuration_snapshot():
    mid=seed_demand()
    a=Agent(no_broadcast,FakeModel())
    with DB() as db:
        settings=get(db,'group',1,'settings').data;settings['prompt']='只用简短中文回复'
        put(db,'job',1,str(mid),{'source':mid,'mention':True,'settings':settings,'status':'pending','analyzed':False});db.commit()
    await a.process(1,str(mid))
    with DB() as db:
        assert get(db,'job',1,str(mid)).data['status']=='done'
        assert db.query(Message).filter_by(user_id=0).filter(~Message.client_id.startswith('card:')).count()==1
    assert any('只用简短中文回复' in str(messages) for messages,_ in a.model.calls)
    await a.close()
