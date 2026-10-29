import asyncio
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from fastapi.testclient import TestClient
from backend.app import app, agent
from backend.auth import configure_password
from backend.db import DB, Message, get, put, records
from backend.agent import Agent
from backend.skills import execute, SkillContext
from backend.memory import save_memory, search, list_memories, delete_memory
from backend.authorization import command_grants
from backend.context import bounded_context, fit_sections
from backend.proactive import next_occurrence, schedule_tick, feedback, quiet
from backend.orchestration import create_run, run_steps
from test_system import FakeModel, no_broadcast


def sign_in(client, who='dad'):
    configure_password(who, 'test-private-passphrase')
    response = client.post('/api/auth/login', json={'username': who, 'password': 'test-private-passphrase'})
    assert response.status_code == 200, response.text
    return response.json()


def message(text, gid=1, user_id=1):
    with DB() as db:
        m = Message(group_id=gid, user_id=user_id, client_id=str(time.time_ns()), content=text, attachments='[]', created=100)
        db.add(m)
        db.commit()
        return m


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,target,confidence,helpful,expected', [
    ('discussion','group',.99,False,'silent'), ('joke','agent',.99,True,'silent'),
    ('emotional','group',.99,False,'silent'), ('request','member',.5,True,'silent'),
    ('request','member',.99,False,'silent'), ('request','member',.95,True,'observe'),
    ('request','agent',.95,True,'observe'),
])
async def test_understanding_does_not_automatically_trigger_participation(kind,target,confidence,helpful,expected):
    model = FakeModel({'intent': {'kind':kind,'target':target,'topic':'晚餐','confidence':confidence,'assistant_helpful':helpful},
                       'new_need': {'text':'晚餐怎么安排','target':'爸爸'}, 'memories':[]})
    a = Agent(no_broadcast,model,lambda:100)
    result = await a.analyze(1,message('今晚饭菜怎么安排'))
    assert result['decision']['action'] == expected
    with DB() as db:
        assert len(records(db,'demand',1)) == (1 if expected=='observe' else 0)
        assert db.query(Message).filter_by(user_id=0).count() == 0
    await a.close()


@pytest.mark.asyncio
async def test_shadow_participation_records_decision_without_candidate():
    with DB() as db:
        r=get(db,'group',1,'settings');r.set({**r.data,'participation_shadow':True});db.commit()
    model=FakeModel({'intent':{'kind':'request','target':'member','confidence':.98,'assistant_helpful':True},'new_need':{'text':'整理清单'}})
    a=Agent(no_broadcast,model,lambda:100)
    await a.analyze(1,message('爸爸，能帮忙整理清单吗'))
    with DB() as db:
        assert records(db,'decision',1)[0].data['action']=='observe'
        assert records(db,'demand',1)==[]
    await a.close()


def test_private_memory_lifecycle_and_conflicts_are_separate_dimensions():
    with DB() as db:
        public=save_memory(db,1,'爸爸喜欢茶',[1],now=100)
        private=save_memory(db,-1,'私人测试事实',[2],manual=True,lifetime='short',now=100,expires_at=200)
        save_memory(db,1,'爸爸现在喜欢咖啡',[3],key=public.key,now=100)
        db.commit()
        assert get(db,'memory',1,public.key).data['content']=='爸爸喜欢茶'
        assert len(records(db,'memory_conflict',1))==1
        assert search(db,-1,'私人',viewer_id=1,now=150)[0]['key']==private.key
        assert search(db,-1,'私人',viewer_id=2,now=150)==[]
        assert search(db,-1,'私人',viewer_id=1,now=200)==[]
        assert search(db,1,'私人',viewer_id=1,now=150)==[]
        save_memory(db,1,'爸爸现在喜欢咖啡',[3],key=public.key,manual=True,now=100)
        assert records(db,'memory_conflict',1)[0].data['status']=='resolved'
        delete_memory(db,private)
        assert save_memory(db,-1,'私人测试事实',[2],now=100) is None


def test_context_preserves_whole_source_and_rejects_oversized_mandatory_content():
    context=[{'role':'system','content':'规则'}, {'role':'user','content':'旧消息'*100}, {'role':'user','content':'爸爸：不要安排晚饭，来源99'}]
    result=bounded_context(context,50)
    assert len(result)==2 and result[-1]==context[-1]
    with pytest.raises(ValueError): bounded_context(context,5)
    assert '非常长' not in fit_sections('规则',10,[('记忆',{'content':'非常长'*1000})],100)


@pytest.mark.asyncio
async def test_scoped_grants_cannot_change_action_arguments_or_owner():
    grant={'tool':'family_tasks','arguments':{'action':'create','title':'准备晚餐'}}
    ctx=SkillContext(1,1,'bounded',1,True,grants=[grant])
    assert 'error' not in await execute('family_tasks',grant['arguments'],ctx)
    assert 'error' in await execute('family_tasks',{'action':'create','title':'转账'},ctx)
    assert 'error' in await execute('family_tasks',{'action':'create','title':'准备晚餐','owner_id':2},ctx)
    assert 'error' in await execute('remember',{'content':'爸爸喜欢茶'},ctx)
    assert command_grants('引用：@小忆 记住爸爸喜欢茶','小忆',100)==[]
    assert command_grants('@小忆 一分钟后提醒我们检查晚餐准备','小忆',100)[0]['arguments']['at']==160


@pytest.mark.asyncio
async def test_workflow_restart_preserves_success_and_cancellation_stops_remaining():
    with DB() as db:
        create_run(db,1,'restart',1,'准备晚饭',[{'tool':'family_tasks','arguments':{'action':'create','title':'买菜'}},
            {'tool':'remember','arguments':{'content':'爸爸喜欢茶'}}],True)
        db.commit()
    await run_steps(1,'restart')
    await run_steps(1,'restart')
    with DB() as db:
        assert len(records(db,'task',1))==1 and len(records(db,'memory',1))==1
        assert get(db,'run',1,'restart').data['status']=='succeeded'
        create_run(db,1,'cancelled',1,'取消的任务',[{'tool':'family_tasks','arguments':{'action':'create','title':'不应出现'}}],True)
        r=get(db,'run',1,'cancelled');r.set({**r.data,'status':'cancelled'});db.commit()
    await run_steps(1,'cancelled')
    with DB() as db: assert len(records(db,'task',1))==1


@pytest.mark.asyncio
async def test_partial_failure_retry_does_not_replay_successful_steps():
    with DB() as db:
        create_run(db,1,'partial',1,'部分失败',[{'tool':'family_tasks','arguments':{'action':'create','title':'已完成步骤'}},
            {'tool':'family_tasks','arguments':{'action':'complete','key':'missing'}}],True)
        db.commit()
    await run_steps(1,'partial')
    with DB() as db:
        r=get(db,'run',1,'partial');d=r.data
        assert d['status']=='failed' and d['steps'][0]['status']=='succeeded'
        put(db,'task',1,'missing',{'title':'稍后可用','done':False})
        r.set({**d,'status':'queued'});db.commit()
    await run_steps(1,'partial')
    with DB() as db:
        assert len(records(db,'task',1))==2
        assert get(db,'run',1,'partial').data['status']=='succeeded'


def test_schedule_once_feedback_snooze_and_no_group_fallback():
    with DB() as db:
        put(db,'reminder',-1,'med',{'content':'按已确定安排服药','at':100,'user_id':1,'channel':'personal','status':'active','sent':False,'version':1,'category':'medication'})
        assert schedule_tick(db,-1,100)==[];db.commit()
        schedule_tick(db,-1,101);db.commit()
        assert db.query(Message).filter_by(group_id=1).count()==0
        delivered=records(db,'delivery',-1)
        assert len(delivered)==1 and delivered[0].data['status']=='sent'
        key=delivered[0].key
        with pytest.raises(ValueError):feedback(db,-1,key,2,'completed',101)
        feedback(db,-1,key,1,'delivered',101)
        feedback(db,-1,key,1,'snoozed',102)
        feedback(db,-1,key,1,'snoozed',103)
        db.commit()
        assert len(records(db,'reminder',-1))==2
        schedule_tick(db,-1,702);db.commit()
        assert len(records(db,'delivery',-1))==2
        latest=next(r for r in records(db,'delivery',-1) if r.key!=key)
        feedback(db,-1,latest.key,1,'completed',703);db.commit()
        assert latest.data['status']=='completed'


def test_recurring_timezone_pause_reschedule_missed_and_dst():
    now=datetime(2026,10,29,8,0,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
    due=next_occurrence(now,'Asia/Shanghai','09:00',[3])
    assert due-now==3600
    with DB() as db:
        put(db,'reminder',1,'weekly',{'content':'日常提醒','at':due,'clock':'09:00','weekdays':[3], 'timezone':'Asia/Shanghai','sent':False,'status':'paused','user_id':1})
        schedule_tick(db,1,due);assert records(db,'delivery',1)==[]
        r=get(db,'reminder',1,'weekly');r.set({**r.data,'status':'active'});db.commit()
        schedule_tick(db,1,due);db.commit()
        schedule_tick(db,1,due);db.commit()
        assert len(records(db,'delivery',1))==1
        assert get(db,'reminder',1,'weekly').data['at']==due+7*86400
        put(db,'reminder',1,'missed',{'content':'过期提醒','at':0,'sent':False,'user_id':1,'grace_seconds':60})
        schedule_tick(db,1,100);db.commit()
        assert len(records(db,'missed',1))==1
    spring=datetime(2026,3,8,0,0,tzinfo=ZoneInfo('America/New_York')).timestamp()
    next_day=next_occurrence(spring,'America/New_York','02:30')
    assert datetime.fromtimestamp(next_day,ZoneInfo('America/New_York')).day==9


def test_subscriptions_consent_quiet_shadow_and_cross_channel_caps():
    now=datetime(2026,10,29,9,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
    base={'user_id':1,'topic':'life','enabled':True,'next_at':now,'timezone':'Asia/Shanghai','clock':'09:00','shadow':False}
    with DB() as db:
        schedule_tick(db,1,now);assert records(db,'delivery',1)==[]
        put(db,'subscription',-1,'shadow',{**base,'channel':'personal','shadow':True})
        schedule_tick(db,-1,now);db.commit()
        assert len(records(db,'shadow',-1))==1 and records(db,'delivery',-1)==[]
        put(db,'preference',-1,'delivery',{'quiet_start':'22:00','quiet_end':'10:00','timezone':'Asia/Shanghai','care_limit':1})
        put(db,'subscription',1,'group',{**base,'channel':'group'})
        schedule_tick(db,1,now);db.commit()
        assert records(db,'delivery',1)==[]
        later=now+2*3600
        schedule_tick(db,1,later);db.commit()
        assert len(records(db,'delivery',1))==1
        put(db,'subscription',-1,'actual',{**base,'channel':'personal'})
        schedule_tick(db,-1,later);db.commit()
        assert records(db,'delivery',-1)==[]
        # Deactivation takes effect even when the schedule is already due.
        r=get(db,'subscription',1,'group');r.set({**r.data,'enabled':False,'next_at':later});db.commit()
        schedule_tick(db,1,later+86400);db.commit()
        assert len(records(db,'delivery',1))==1


def test_explicit_confirmation_notice_is_private_and_idempotent():
    with DB() as db:
        put(db,'reminder',-1,'notify',{'content':'私人安排','at':100,'user_id':1,'channel':'personal','status':'active','sent':False,'version':1,'notify_user_id':2,'notify_after_minutes':5})
        schedule_tick(db,-1,100);db.commit()
        schedule_tick(db,-1,400);db.commit()
        schedule_tick(db,-1,401);db.commit()
        notices=records(db,'delivery',-2)
        assert len(notices)==1 and '不代表事项未完成' in notices[0].data['content']
        assert '私人安排' not in notices[0].data['content']
        assert db.query(Message).filter_by(group_id=1).count()==0


def test_authentication_and_private_api_isolation():
    agent.model=FakeModel()
    with TestClient(app) as client:
        assert client.get('/api/harness/personal/state?user=dad').status_code==401
        assert client.post('/api/auth/login',json={'username':'dad','password':'unknown'}).status_code==401
        sign_in(client)
        assert client.get('/api/me?user=mom').json()['username']=='dad'
        response=client.post('/api/harness/personal/memories',json={'content':'PRIVATE_SENTINEL','lifetime':'short'})
        assert response.status_code==200,response.text
        key=response.json()['key']
        assert 'PRIVATE_SENTINEL' in client.get('/api/harness/personal/state').text
        for url in ['/api/groups/1/memories?user=mom','/api/groups/1/agent/status?user=mom','/api/groups/1/activity?user=mom']:
            assert 'PRIVATE_SENTINEL' not in client.get(url).text
        assert client.get('/api/groups/1/memories/'+key+'/revisions?user=dad').status_code==404
        assert client.post('/api/harness/group/memories',json={'content':'bad','scope':'private'}).status_code==422
        client.post('/api/auth/logout')
        assert client.get('/api/harness/personal/state?user=dad').status_code==401
        sign_in(client,'mom')
        assert 'PRIVATE_SENTINEL' not in client.get('/api/harness/personal/state').text
        assert client.delete('/api/harness/personal/memories/'+key).status_code==404


def test_run_api_supplement_authorize_cancel_and_idempotent_creation():
    agent.model=FakeModel()
    with TestClient(app) as client:
        sign_in(client)
        body={'title':'待补充','client_id':'same','steps':[{'tool':'family_tasks','arguments':{'action':'create'}}]}
        r=client.post('/api/harness/group/runs',json=body)
        assert r.status_code==200,r.text
        run=r.json();assert run['status']=='waiting_input'
        assert client.post('/api/harness/group/runs',json=body).json()['key']==run['key']
        url='/api/harness/group/runs/'+run['key']+'/control'
        assert client.post(url,json={'action':'authorize'}).status_code==400
        assert client.post(url,json={'action':'supplement','steps':[{'tool':'family_tasks','arguments':{'action':'create','title':'买菜'}}]}).json()['status']=='waiting_authorization'
        assert client.post(url,json={'action':'authorize'}).json()['status']=='queued'
        assert client.post(url,json={'action':'cancel'}).json()['status']=='cancelled'


def test_health_consent_invalid_schedule_and_feedback_requirements():
    agent.model=FakeModel()
    with TestClient(app) as client:
        sign_in(client)
        body={'content':'已明确的用药安排','at':time.time()+3600,'category':'medication'}
        assert client.post('/api/harness/group/reminders',json=body).status_code==422
        assert client.post('/api/harness/group/reminders',json={**body,'share_health':True}).status_code==200
        assert client.post('/api/harness/personal/reminders',json={**body,'timezone':'Invalid/Zone'}).status_code==422
        assert client.post('/api/harness/personal/reminders',json={**body,'clock':'09:00'}).status_code==422
        assert client.post('/api/harness/group/subscriptions',json={'topic':'health'}).status_code==422
        assert client.post('/api/harness/personal/subscriptions',json={'topic':'health'}).json()['shadow'] is True
        assert client.put('/api/harness/personal/preferences',json={'quiet_start':'22:00'}).status_code==422


@pytest.mark.asyncio
async def test_private_context_never_enters_group_context_or_public_metrics():
    private=message('私人对话',-1)
    public=message('爸爸喜欢茶',1)
    with DB() as db:
        save_memory(db,-1,'PRIVATE_CONTEXT_SENTINEL',manual=True)
        save_memory(db,1,'爸爸喜欢茶',manual=True)
        group_settings=get(db,'group',1,'settings').data
        private_settings={**group_settings,'active':False}
        put(db,'group',-1,'settings',private_settings)
        db.commit()
    a=Agent(no_broadcast,FakeModel())
    ctx=await a.context(1,public.id,group_settings)
    assert 'PRIVATE_CONTEXT_SENTINEL' not in json.dumps(ctx,ensure_ascii=False)
    with pytest.raises(ValueError): await a.context(1,private.id,group_settings)
    await a.close()


def test_unconfigured_password_has_no_default_login():
    with TestClient(app) as client:
        assert client.post('/api/auth/login',json={'username':'dad','password':'not-a-user'}).status_code==401
        assert client.get('/api/harness/personal/state?user=dad').status_code==401


@pytest.mark.asyncio
async def test_explicit_command_executes_even_when_model_omits_tools_and_retry_is_safe():
    m=message('@小忆 添加待办：准备晚餐')
    a=Agent(no_broadcast,FakeModel(),lambda:100)
    with DB() as db: settings=get(db,'group',1,'settings').data
    await a.generate(1,m.id,settings,'explicit-command')
    await a.generate(1,m.id,settings,'explicit-command')
    with DB() as db:
        rows=records(db,'task',1)
        assert len(rows)==1 and rows[0].data['title']=='准备晚餐'
    await a.close()


@pytest.mark.asyncio
async def test_offline_participation_fixture_set():
    from backend.evaluate import evaluate
    result=await evaluate()
    assert result['cases']==12 and result['passed']==12


def test_memory_events_are_personal_only_and_carry_no_memory_payload():
    now=100
    base={'user_id':1,'topic':'life','enabled':True,'next_at':99999,'timezone':'Asia/Shanghai','clock':'09:00','shadow':False,'trigger':'memory_expiring'}
    with DB() as db:
        save_memory(db,-1,'EVENT_PRIVATE_SENTINEL',manual=True,lifetime='short',expires_at=200,now=100)
        put(db,'subscription',-1,'memory',{**base,'channel':'personal'})
        put(db,'subscription',1,'malformed-group',{**base,'channel':'group'})
        schedule_tick(db,-1,now);schedule_tick(db,-1,now);schedule_tick(db,1,now);db.commit()
        assert len(records(db,'delivery',-1))==1
        assert 'EVENT_PRIVATE_SENTINEL' not in records(db,'delivery',-1)[0].data['content']
        assert records(db,'delivery',1)==[]


def test_group_memory_subscription_is_rejected():
    agent.model=FakeModel()
    with TestClient(app) as client:
        sign_in(client)
        assert client.post('/api/harness/group/subscriptions',json={'topic':'life','trigger':'memory_expiring'}).status_code==422


def test_planner_uses_only_explicit_goal_and_waits_for_authorization():
    class Planner(FakeModel):
        async def call(self,messages,**kwargs):
            assert 'PLANNER_PRIVATE_SENTINEL' not in json.dumps(messages)
            return {'title':'准备晚餐','steps':[{'tool':'family_tasks','arguments':{'action':'create','title':'买菜'}}]}
    agent.model=Planner()
    with TestClient(app) as client:
        sign_in(client)
        client.post('/api/harness/personal/memories',json={'content':'PLANNER_PRIVATE_SENTINEL'})
        r=client.post('/api/harness/personal/runs/plan',json={'goal':'准备晚餐，先买菜','client_id':'plan-once'})
        assert r.status_code==200,r.text
        assert r.json()['status']=='waiting_authorization'
        with DB() as db: assert records(db,'task',-1)==[]


def test_pending_reminder_update_and_cancel_remove_old_occurrence():
    agent.model=FakeModel()
    with TestClient(app) as client:
        sign_in(client)
        original=time.time()+3600
        r=client.post('/api/harness/personal/reminders',json={'content':'改期测试','at':original}).json()
        new=client.put('/api/harness/personal/reminders/'+r['key'],json={'content':'新安排','at':original+3600}).json()
        assert new['version']==2
        with DB() as db:
            schedule_tick(db,-1,original);db.commit()
            assert records(db,'delivery',-1)==[]
        assert client.delete('/api/harness/personal/reminders/'+r['key']).status_code==200
        with DB() as db:
            schedule_tick(db,-1,original+3600);db.commit()
            assert records(db,'delivery',-1)==[]


def test_paused_rule_and_cancelling_root_stop_pending_snooze():
    with DB() as db:
        put(db,'reminder',-1,'root',{'content':'周期安排','at':100,'user_id':1,'channel':'personal','status':'active','sent':False,'version':1,'clock':'09:00','timezone':'Asia/Shanghai'})
        schedule_tick(db,-1,100);db.commit()
        first=records(db,'delivery',-1)[0]
        feedback(db,-1,first.key,1,'snoozed',101,1);db.commit()
        root=get(db,'reminder',-1,'root');root.set({**root.data,'status':'cancelled','version':2});db.commit()
        schedule_tick(db,-1,161);db.commit()
        assert len(records(db,'delivery',-1))==1


def test_api_pause_resume_future_rule():
    agent.model=FakeModel()
    with TestClient(app) as client:
        sign_in(client)
        r=client.post('/api/harness/personal/reminders',json={'content':'可暂停','at':time.time()+3600}).json()
        path='/api/harness/personal/reminders/'+r['key']+'/control'
        assert client.post(path,json={'action':'pause'}).json()['status']=='paused'
        assert client.post(path,json={'action':'resume'}).json()['status']=='active'


def test_new_memory_and_reminder_requests_are_idempotent():
    agent.model=FakeModel()
    with TestClient(app) as client:
        sign_in(client)
        for kind, body in [('memories',{'content':'重复提交','client_id':'memory-once'}),
                           ('reminders',{'content':'重复提醒','client_id':'reminder-once','at':time.time()+3600})]:
            first=client.post('/api/harness/personal/'+kind,json=body)
            second=client.post('/api/harness/personal/'+kind,json=body)
            assert first.status_code==200 and second.json()['key']==first.json()['key']
        with DB() as db:
            assert len(records(db,'memory',-1))==1 and len(records(db,'reminder',-1))==1


@pytest.mark.asyncio
async def test_equivalent_numeric_tool_arguments_use_sealed_grant_key():
    grant={'tool':'group_reminder','arguments':{'content':'提醒','at':1000.0}}
    ctx=SkillContext(1,1,'numeric',1,True,grants=[grant],now=100)
    await execute('group_reminder',grant['arguments'],ctx)
    await execute('group_reminder',{'content':'提醒','at':1000},ctx)
    with DB() as db: assert len(records(db,'reminder',1))==1


@pytest.mark.asyncio
async def test_cancelling_running_task_keeps_inflight_result_and_stops_next_step(monkeypatch):
    from backend.skills import REGISTRY, Skill, schema
    started=asyncio.Event();release=asyncio.Event()
    async def slow(ctx,args):
        started.set();await release.wait();return {'completed':True}
    monkeypatch.setitem(REGISTRY,'test_slow',Skill('test_slow','测试进行中步骤',schema({}),slow))
    with DB() as db:
        create_run(db,1,'cancel-during',1,'运行中取消',[{'tool':'test_slow','arguments':{}},
            {'tool':'remember','arguments':{'content':'后续步骤不应执行'}}],True)
        db.commit()
    task=asyncio.create_task(run_steps(1,'cancel-during'))
    await started.wait()
    with DB() as db:
        r=get(db,'run',1,'cancel-during');r.set({**r.data,'status':'cancelled'});db.commit()
    release.set();await task
    with DB() as db:
        d=get(db,'run',1,'cancel-during').data
        assert d['status']=='cancelled' and d['steps'][0]['status']=='succeeded'
        assert records(db,'memory',1)==[]


def test_over_intervention_feedback_suppresses_topic_but_not_direct_requests():
    from backend.participation import send_policy, decide
    from backend.contracts import ConversationEvent, Intent
    agent.model=FakeModel()
    with TestClient(app) as client:
        sign_in(client)
        with DB() as db:
            source=message('能帮忙整理吗')
            settings=get(db,'group',1,'settings').data
            put(db,'demand',1,'source:'+str(source.id),{'source':source.id,'topic':'整理清单','status':'sent'})
            reply=Message(group_id=1,user_id=0,client_id='demand:source:'+str(source.id),content='需要整理吗',attachments='[]')
            db.add(reply);db.commit();reply_id=reply.id
        assert client.post('/api/harness/group/feedback',json={'kind':'over_intervention','source':reply_id}).status_code==200
        with DB() as db:
            assert send_policy(db,1,{'settings':settings,'topic':'整理清单','deadline':time.time()},time.time(),settings)=='feedback_suppressed'
        event=ConversationEvent(1,1,99,'@小忆 请整理',time.time(),True)
        assert decide(event,Intent(kind='request',target='agent',confidence=.99),settings).action=='reply'


@pytest.mark.asyncio
async def test_readonly_tool_retry_rechecks_current_memory_visibility():
    with DB() as db:
        memory=save_memory(db,-1,'需要遗忘的偏好',[1],manual=True)
        db.commit();key=memory.key
    ctx=SkillContext(-1,1,'same-read-run',1,False,grants=[])
    assert len(await execute('memory_search',{'query':'偏好'},ctx))==1
    with DB() as db:
        delete_memory(db,get(db,'memory',-1,key));db.commit()
    assert await execute('memory_search',{'query':'偏好'},ctx)==[]


def test_deleting_memory_discards_conflicts_and_suppresses_their_sources():
    with DB() as db:
        memory=save_memory(db,1,'原有偏好',[1])
        save_memory(db,1,'冲突偏好',[2],key=memory.key)
        delete_memory(db,memory);db.commit()
        assert records(db,'memory_conflict',1)[0].data['status']=='discarded'
        assert save_memory(db,1,'冲突偏好',[2]) is None
