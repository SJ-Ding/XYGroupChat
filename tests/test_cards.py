import asyncio
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from backend.app import app
from backend.db import DB, get, put, records, Message, Member
from backend.cards import CardSpec, request_intervention, sync_run
from backend.orchestration import create_run, run_steps
from backend.skills import REGISTRY, Skill, schema, human_input


def seed(key='test', authorized=False, gid=1):
    with DB() as db:
        create_run(db, gid, key, 1, '准备家庭事项', [{'tool':'family_tasks','arguments':{'action':'create','title':'买菜'}}], authorized=authorized)
        db.commit()


def client():
    # No lifespan worker: make each execution boundary deterministic.
    return TestClient(app)


def cards(c, user='dad', gid=1):
    response = c.get(f'/api/groups/{gid}/cards?user={user}')
    assert response.status_code == 200, response.text
    return response.json()


def action(c, card, op='confirm', user='mom', request='one', **kw):
    return c.post('/api/groups/1/cards/' + card['id'] + '/actions?user=' + user, json={'action':op,'version':card['version'],'request_id':request,**kw})


def test_card_schema_and_legacy_messages():
    for spec in [{'title':'bad','links':[{'label':'pay','url':'javascript:alert(1)'}]}, {'title':'bad','fields':[{'key':'x','label':'x','type':'select'}]}, {'title':'bad','html':'<script/>'}]:
        with pytest.raises(ValidationError): CardSpec.model_validate(spec)
    c=client()
    row=c.post('/api/groups/1/messages?user=dad',json={'client_id':'legacy','content':'你好'}).json()
    assert row['cards']==[]


@pytest.mark.asyncio
async def test_group_member_confirm_and_durable_no_replay():
    seed();c=client();card=cards(c)[0]
    assert card['actions']==['confirm','cancel']
    assert action(c,card).status_code==200
    assert action(c,card).status_code==200  # same request receipt
    assert action(c,card,user='child',request='second').status_code==409
    await run_steps(1,'test');await run_steps(1,'test')
    with DB() as db:
        assert len(records(db,'task',1))==1
        assert get(db,'run',1,'test').data['status']=='succeeded'
        assert records(db,'card_action',1)[0].data['user_id']==2
    assert cards(c)[0]['status']=='succeeded'
    rows=c.get('/api/groups/1/messages?user=mom').json()
    assert rows[0]['cards'][0]['id']==card['id']


@pytest.mark.asyncio
async def test_trusted_checkpoint_forms_links_and_restart(monkeypatch):
    calls=[]
    async def checkpoint(ctx,args):
        result=await human_input(ctx,'review',{'title':'请审核事项','amount':'¥20.00','items':[{'label':'事项','value':'家庭服务'}], 'fields':[{'key':'choice','label':'安排','type':'select','options':['上午','下午'],'required':True},{'key':'count','label':'人数','type':'number','required':True}], 'links':[{'label':'跳转支付','url':'https://example.com/pay'}]})
        calls.append(result)
        return {'ok':True}
    monkeypatch.setitem(REGISTRY,'checkpoint',Skill('checkpoint','test',schema({}),checkpoint,True))
    with DB() as db:
        create_run(db,1,'check',1,'测试检查点',[{'tool':'family_tasks','arguments':{'action':'create','title':'买菜'}},{'tool':'checkpoint','arguments':{}}],True);db.commit()
    await run_steps(1,'check')
    c=client();review=next(x for x in cards(c) if x['kind']=='intervention')
    assert action(c,review,'submit',values={'choice':'错误','count':'two'}).status_code==422
    assert action(c,review,'open_link',link_index=0).status_code==200
    with DB() as db: assert get(db,'run',1,'check').data['status']=='waiting_input'
    await run_steps(1,'check')  # restart while awaiting input cannot execute
    assert calls==[]
    assert action(c,review,'submit',request='valid',values={'choice':'上午','count':2}).status_code==200
    await run_steps(1,'check');await run_steps(1,'check')
    with DB() as db:
        assert get(db,'run',1,'check').data['status']=='succeeded'
        assert len(records(db,'task',1))==1
    assert len(calls)==1 and calls[0]['user_id']==2
    assert action(c,review,'submit',request='stale',values={}).status_code==409


def test_concurrent_review_is_atomic():
    seed();card=cards(client())[0]
    def submit(user): return action(client(),card,user=user,request=user).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit,['mom','child']))==[200,409]


def test_cross_group_private_and_cancelled_review():
    seed();seed('private',gid=-1)
    c=client()
    assert c.get('/api/groups/-1/cards?user=dad').status_code==403
    assert c.get('/api/groups/99/cards?user=mom').status_code==403
    with DB() as db:
        request_intervention(db,1,'test','review',{'title':'审核'});db.commit()
    review=next(x for x in cards(c) if x['kind']=='intervention')
    assert action(c,review,'cancel').status_code==200
    assert action(c,review,request='later').status_code==409
    assert next(x for x in cards(c) if x['id']==review['id'])['actions']==[]

@pytest.mark.asyncio
async def test_missing_fields_require_separate_authorization():
    with DB() as db:
        r=create_run(db,1,'missing',1,'补充采购',[{'tool':'family_tasks','arguments':{'action':'create'}}])
        r.set({**r.data,'status':'waiting_input'});sync_run(db,1,r.key);db.commit()
    c=client();card=cards(c)[0]
    assert action(c,card,'submit',values={'0:title':'采购蔬菜'}).status_code==200
    with DB() as db:
        assert get(db,'run',1,'missing').data['grants']==[]
        assert records(db,'task',1)==[]
    fresh=cards(c)[0]
    assert action(c,fresh,request='confirm-after-input').status_code==200
    await run_steps(1,'missing')
    with DB() as db: assert len(records(db,'task',1))==1


@pytest.mark.asyncio
async def test_retry_keeps_successful_steps_and_information_card_tool(monkeypatch):
    from backend.skills import execute, SkillContext
    attempts=[]
    async def flaky(ctx,args):
        attempts.append(1)
        return {'error':'稍后重试'} if len(attempts)==1 else {'ok':True}
    monkeypatch.setitem(REGISTRY,'flaky',Skill('flaky','test',schema({}),flaky))
    with DB() as db:
        create_run(db,1,'retry',1,'重试任务',[{'tool':'family_tasks','arguments':{'action':'create','title':'采购'}},{'tool':'flaky','arguments':{}}],True);db.commit()
    await run_steps(1,'retry');c=client();card=cards(c)[0]
    assert card['status']=='failed'
    assert action(c,card,'retry').status_code==200
    await run_steps(1,'retry')
    with DB() as db: assert len(records(db,'task',1))==1
    result=await execute('send_card',{'title':'信息','items':[{'label':'内容','value':'采购已安排'}]},SkillContext(1,1,'info',0,selected={'send_card'}))
    assert 'card_id' in result
    info=next(x for x in cards(c) if x['kind']=='info')
    assert info['actions']==[]
    assert action(c,info).status_code==409
