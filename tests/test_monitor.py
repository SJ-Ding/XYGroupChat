import asyncio
import json
import pytest
from fastapi.testclient import TestClient
from backend.app import app, agent
from backend.agent import Agent
from backend.monitor import snapshot
from backend.db import DB, get, put
from test_system import FakeModel, no_broadcast, seed_demand

def test_monitor_counts_whitelist_and_group_isolation():
    mid=seed_demand(candidate='尚未发送的候选')
    with DB() as db:
        put(db,'job',1,'running-job',{'source':mid,'status':'pending','settings':{'prompt':'PRIVATE_PROMPT_SENTINEL'}})
        put(db,'job',1,'failed-job',{'source':mid,'status':'failed','analyzed':False,'error':'模型超时'})
        put(db,'log',1,'decision',{'source':mid,'at':120,'reason':'等待回应'})
        put(db,'log',2,'private',{'source':mid,'at':120,'reason':'OTHER_GROUP_SENTINEL'})
        db.commit()
    a=Agent(no_broadcast,FakeModel(),lambda:125)
    a.started_at=90;a.last_tick=124
    a.executions[('job',1,'running-job')]={'group_id':1,'key':'running-job','source':mid,'phase':'analyzing','started':121}
    a.executions[('job',2,'other')]={'group_id':2,'key':'other','source':mid,'phase':'replying','started':121}
    result=snapshot(a,1)
    assert result['scheduler']['state']=='running'
    assert result['counts']=={'running':1,'pending':0,'done':0,'failed':1,'observing':1}
    assert result['behavior']['blocked'] is True
    assert result['demands'][0]['candidate']=='尚未发送的候选'
    assert 'PRIVATE_PROMPT_SENTINEL' not in json.dumps(result)
    assert 'OTHER_GROUP_SENTINEL' not in json.dumps(result)
    assert len(result['skills'])>=4
    a.last_tick=100
    assert snapshot(a,1)['scheduler']['state']=='degraded'
    a.stopped=True
    assert snapshot(a,1)['scheduler']['state']=='stopped'

def test_monitor_endpoint_requires_valid_group_member():
    agent.model=FakeModel()
    with TestClient(app) as client:
        assert client.get('/api/groups/1/agent/status').status_code==400
        assert client.get('/api/groups/2/agent/status?user=dad').status_code==403
        result=client.get('/api/groups/1/agent/status?user=dad')
        assert result.status_code==200
        assert result.json()['name']=='小艺'

@pytest.mark.asyncio
async def test_live_candidate_phase_is_removed_after_generation():
    mid=seed_demand(candidate=None)
    model=FakeModel();model.gate=asyncio.Event()
    a=Agent(no_broadcast,model)
    with DB() as db: settings=get(db,'group',1,'settings').data
    task=asyncio.create_task(a.candidate(1,'need',1,mid,settings))
    await asyncio.sleep(.01)
    assert snapshot(a,1)['executions'][0]['phase']=='candidate'
    model.gate.set();await task
    assert snapshot(a,1)['executions']==[]
    assert snapshot(a,1)['demands'][0]['candidate']
    await a.close()
