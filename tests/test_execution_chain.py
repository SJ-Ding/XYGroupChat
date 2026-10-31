import asyncio
import json
import pytest
from fastapi.testclient import TestClient
from backend.app import app
from backend.agent import Agent
from backend.db import DB, get, put
from backend.execution_chain import query, start, finish, model_call
from backend.skills import SkillContext, execute
from test_system import seed_demand, no_broadcast

@pytest.mark.asyncio
async def test_rounds_persist_without_raw_data():
    mid = seed_demand()
    ctx = SkillContext(1, 1, 'parent', mid, False, grants=[], selected={'skill_load','memory_search'})
    await execute('skill_load', {'name':'family-outing'}, ctx)
    await execute('memory_search', {'query':'private query sentinel'}, ctx)
    await execute('memory_search', {'query':'second query'}, ctx)
    data = query(1,[mid])[str(mid)]
    assert len(data['steps']) == 3
    assert len({s['id'] for s in data['steps']}) == 3
    assert all(s['status']=='succeeded' for s in data['steps'])
    assert all(s['attempt']==1 for s in data['steps'])
    assert 'family-outing' in data['steps'][0]['title']
    assert 'private query sentinel' not in json.dumps(data)
    assert query(2,[mid]) == {}
    assert data == query(1,[mid])[str(mid)]

@pytest.mark.asyncio
async def test_failure_cancel_and_delivery():
    mid=seed_demand()
    class Broken:
        async def call(self,*a,**kw): raise RuntimeError('SECRET')
    a=Agent(no_broadcast,Broken())
    with pytest.raises(RuntimeError): await model_call(a,1,mid,'run','reply',[])
    class Cancelled:
        async def call(self,*a,**kw): raise asyncio.CancelledError()
    a.model=Cancelled()
    with pytest.raises(asyncio.CancelledError): await model_call(a,1,mid,'run','reply',[])
    await a.send(1,'reply','run',source_id=mid)
    steps=query(1,[mid])[str(mid)]['steps']
    assert [s['status'] for s in steps]==['failed','cancelled','succeeded']
    assert 'SECRET' not in json.dumps(steps)
    await a.close()

@pytest.mark.asyncio
async def test_parent_and_retry_and_history():
    mid=seed_demand()
    with DB() as db:
        put(db,'run',1,'child',{'source_id':mid,'parent_run':'parent','status':'waiting_input','attempt':1})
        db.commit()
    key=await start(1,mid,'child','tool','执行工具操作')
    await finish(1,key)
    data=query(1,[mid])[str(mid)]
    assert data['steps'][0]['task_id']=='parent'
    assert data['steps'][0]['attempt']==2
    assert data['tasks'][0]['status']=='waiting_input'


def test_observer_only_endpoint():
    mid=seed_demand()
    with TestClient(app) as client:
        assert client.get(f'/api/groups/1/agent/chains?user=agent&ids={mid}').status_code==200
        assert client.get(f'/api/groups/1/agent/chains?user=child&ids={mid}').status_code==403
        assert client.get(f'/api/groups/2/agent/chains?user=agent&ids={mid}').status_code==403
        assert client.get('/api/groups/1/agent/chains?user=agent&ids=oops').status_code==422

@pytest.mark.asyncio
async def test_cached_write_and_delivery_failure():
    mid=seed_demand()
    ctx=SkillContext(1,1,'cached',mid,True)
    args={'action':'create','title':'买菜'}
    first=await execute('family_tasks',args,ctx)
    second=await execute('family_tasks',args,ctx)
    assert first==second
    steps=query(1,[mid])[str(mid)]['steps']
    assert steps[-1]['summary']=='使用已有结果'
    a=Agent(no_broadcast)
    async def broken(*args,**kwargs): raise RuntimeError('SECRET_DELIVERY')
    a._send=broken
    with pytest.raises(RuntimeError): await a.send(1,'hello','cached',source_id=mid)
    steps=query(1,[mid])[str(mid)]['steps']
    assert steps[-2]['status']=='succeeded' and steps[-1]['status']=='failed'
    assert 'SECRET_DELIVERY' not in json.dumps(steps)
    await a.close()


def test_legacy_trace_has_no_raw_context():
    mid=seed_demand()
    with DB() as db:
        put(db,'trace',1,'legacy',{'source':mid,'phase':'reply','status':'done','messages':'PRIVATE','response':{'reasoning_content':'SECRET'}})
        db.commit()
    data=query(1,[mid])[str(mid)]
    assert data['steps'][0]['started'] is None
    assert data['steps'][0]['summary']=='历史调用；详细过程未记录'
    assert 'PRIVATE' not in json.dumps(data) and 'SECRET' not in json.dumps(data)


def test_tool_titles_include_concrete_names():
    from backend.execution_chain import tool_title
    assert tool_title('web_query', {}) == '联网查询（web_query）'
    assert tool_title('hospital_simulator', {'action':'query'}) == '查询就医号源（hospital_simulator）'
    assert tool_title('custom_tool', {}) == '执行工具操作（custom_tool）'
    assert tool_title('skill_load', {'name':'family-outing'}) == '加载场景技能：family-outing（skill_load）'
    assert 'SECRET' not in tool_title('web_query', {'query':'SECRET'})
