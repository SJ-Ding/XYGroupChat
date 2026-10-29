import asyncio
import json
import pytest
from backend.agent import Agent
from backend.db import DB, Message, get, put, records
from backend.skills import SkillContext, execute, tools
from test_system import FakeModel, no_broadcast, seed_demand

@pytest.mark.asyncio
async def test_pending_and_failed_analysis_block_old_candidate():
    mid=seed_demand()
    a=Agent(no_broadcast,FakeModel(),lambda:200)
    with DB() as db:
        put(db,'job',1,'later',{'source':mid,'mention':False,'status':'failed','analyzed':False,'settings':get(db,'group',1,'settings').data});db.commit()
    await a.tick()
    with DB() as db:
        assert db.query(Message).filter_by(user_id=0).count()==0
        r=get(db,'job',1,'later');d=r.data;d['analyzed']=True;r.set(d);db.commit()
    await a.tick()
    with DB() as db: assert db.query(Message).filter_by(user_id=0).count()==1
    await a.close()

@pytest.mark.asyncio
async def test_multiple_demands_and_reminders_send_without_db_lock():
    seed_demand('a');seed_demand('b')
    with DB() as db:
        put(db,'reminder',1,'remind',{'content':'检查晚餐','at':120,'sent':False});db.commit()
    a=Agent(no_broadcast,FakeModel(),lambda:200)
    await a.tick();await a.tick()
    with DB() as db: assert db.query(Message).filter_by(user_id=0).count()==3
    await a.close()

@pytest.mark.asyncio
async def test_setting_version_invalidates_existing_candidate():
    seed_demand()
    with DB() as db:
        r=get(db,'group',1,'settings');d=r.data;d['version']+=1;r.set(d);db.commit()
    a=Agent(no_broadcast,FakeModel(),lambda:200)
    await a.tick()
    with DB() as db:
        assert get(db,'demand',1,'need').data['status']=='cancelled'
        assert db.query(Message).filter_by(user_id=0).count()==0
    await a.close()

@pytest.mark.asyncio
async def test_readonly_tasks_are_available_without_write_authorization():
    names=[t['function']['name'] for t in tools(False)]
    assert 'family_tasks' in names and 'remember' not in names
    ctx=SkillContext(1,1,'read',1,False)
    assert await execute('family_tasks',{'action':'list'},ctx)==[]
    assert 'error' in await execute('family_tasks',{'action':'create','title':'不应写入'},ctx)

@pytest.mark.asyncio
async def test_context_contains_image_and_nonoverlapping_summary():
    mid=seed_demand()
    with DB() as db:
        from backend.db import DATA
        (DATA/'uploads'/'test.png').write_bytes(b'image')
        put(db,'upload',1,'pic',{'file':'test.png','mime':'image/png','owner':1})
        m=db.get(Message,mid);m.attachments=json.dumps(['pic'])
        put(db,'summary',1,'latest',{'from':0,'to':mid-1,'content':'早期家庭摘要'})
        db.commit();settings=get(db,'group',1,'settings').data
    a=Agent(no_broadcast,FakeModel())
    context=await a.context(1,mid,settings)
    assert '早期家庭摘要' in context[0]['content']
    assert any(block['type']=='image_url' for block in context[-1]['content'])
    await a.close()

@pytest.mark.asyncio
async def test_generation_failure_persists_retry_state():
    mid=seed_demand(candidate=None)
    class Broken(FakeModel):
        async def call(self,*args,**kwargs): raise RuntimeError('测试网络故障')
    a=Agent(no_broadcast,Broken())
    with DB() as db: settings=get(db,'group',1,'settings').data
    await a.candidate(1,'need',1,mid,settings)
    with DB() as db:
        d=get(db,'demand',1,'need').data
        assert d['status']=='failed' and '测试网络故障' in d['error']
    await a.close()

@pytest.mark.asyncio
async def test_skill_loop_is_bounded():
    mid=seed_demand()
    class Endless(FakeModel):
        async def call(self,*args,**kwargs):
            return {'role':'assistant','content':None,'tool_calls':[{'id':'tool','type':'function','function':{'name':'memory_search','arguments':'{"query":"妈妈"}'}}]}
    a=Agent(no_broadcast,Endless())
    with DB() as db: settings=get(db,'group',1,'settings').data
    with pytest.raises(RuntimeError,match='轮数'):
        await a.generate(1,mid,settings,'endless')
    await a.close()

@pytest.mark.asyncio
async def test_reminders_survive_failed_conversation_analysis():
    mid=seed_demand()
    with DB() as db:
        put(db,'job',1,'failed',{'source':mid,'status':'failed','analyzed':False})
        put(db,'reminder',1,'scheduled',{'content':'约好的群内提醒','at':100,'sent':False})
        db.commit()
    a=Agent(no_broadcast,FakeModel(),lambda:200)
    await a.tick()
    with DB() as db:
        rows=db.query(Message).filter_by(user_id=0).all()
        assert len(rows)==1 and rows[0].content=='提醒：约好的群内提醒'
        assert get(db,'demand',1,'need').data['status']=='waiting'
    await a.close()
