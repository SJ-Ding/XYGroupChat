import json
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from sqlalchemy import text
from backend.agent import Agent
from backend.db import DB, Message, get, put, records, migrate
from backend.memory import save_memory, list_memories, search, delete_memory
from backend.memory_lifecycle import capture, review, status
from backend.persona import DEFAULT_AGENT_NAME, DEFAULT_PROMPT, LEGACY_PROMPT, system_prompt
from backend.intent import direct_mention
from backend.authorization import command_grants
from test_system import FakeModel, no_broadcast

T=datetime(2026,10,30,9,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
SETTINGS={'memory_auto':True,'memory_short_days':7,'memory_review_seconds':21600}


def message(content, at=T, gid=1, user=2):
    with DB() as db:
        m=Message(group_id=gid,user_id=user,client_id=uuid.uuid4().hex,content=content,created=at,attachments='[]')
        db.add(m);db.commit();return m


def observation(content='妈妈明天去杭州', **kwargs):
    return {'content':content,'evidence':'明天去杭州','topic':'妈妈出行','category':'plan','subject_ids':[2],
            'subjects':['妈妈'],'confidence':.98,'lifetime':'short','operation':'upsert',**kwargs}


def due(db,gid,now):
    put(db,'memory_maintenance',gid,'latest',{'last_run':None,'next_due':now,'runs':0,'counts':{},'dirty':True})


@pytest.mark.asyncio
async def test_current_plan_is_remembered_without_request_or_public_ack():
    m=message('我明天去杭州，上午拜访客户。')
    model=FakeModel({'intent':{'kind':'discussion','confidence':.99},'memories':[observation()]})
    a=Agent(no_broadcast,model,lambda:T+1)
    result=await a.analyze(1,m)
    with DB() as db:
        memory=list_memories(db,1,now=T+1)[0]
        assert memory['lifetime']=='short' and memory['expires_at']==T+7*86400
        assert memory['sources']==[m.id] and memory['subject_ids']==[2]
        assert not memory['confirmed'] and not memory['manual']
        assert db.query(Message).filter_by(user_id=0).count()==0
        assert not records(db,'task',1) and not records(db,'reminder',1)
        assert get(db,'memory_maintenance',1,'latest').data['next_due']==T+301
    assert result['decision']['action']=='silent'
    query=message('@小艺 妈妈最近有什么安排？',T+2,user=3)
    with DB() as db:settings=get(db,'group',1,'settings').data
    context=await a.context(1,query.id,settings)
    assert '妈妈明天去杭州' in json.dumps(context,ensure_ascii=False)
    await a.close()


@pytest.mark.asyncio
async def test_another_members_request_cannot_turn_plan_update_into_reply():
    message('@小艺 我周末打算做什么？',T,user=3)
    m=message('我去星河图书馆还书的安排改到后天下午。',T+1)
    # Even a mistaken model classification cannot summon the assistant here.
    a=Agent(no_broadcast,FakeModel({'intent':{'kind':'request','target':'agent','confidence':.99,'assistant_helpful':True}}),lambda:T+2)
    result=await a.analyze(1,m)
    assert result['decision']['action']=='silent'
    payload=json.loads(a.model.calls[0][0][-1]['content'])
    assert payload['latest_message']['id']==m.id
    assert all(x['id']!=m.id for x in payload['messages'])
    with DB() as db:assert records(db,'demand',1)==[]
    await a.close()


def test_clear_correction_updates_auto_memory_and_stale_replay_cannot_undo_it():
    original=message('我明天去杭州。')
    correction=message('行程改到后天去杭州。',T+60)
    with DB() as db:
        capture(db,1,original,[observation()],SETTINGS,T)
        key=list_memories(db,1,now=T)[0]['key']
        capture(db,1,correction,[observation('妈妈后天去杭州',evidence='改到后天去杭州',existing_key=key,operation='update')],SETTINGS,T+60,{key})
        assert get(db,'memory',1,key).data['content']=='妈妈后天去杭州'
        assert records(db,'revision',1)[0].data['previous']['content']=='妈妈明天去杭州'
        capture(db,1,original,[observation(existing_key=key)],SETTINGS,T+61,{key})
        assert get(db,'memory',1,key).data['content']=='妈妈后天去杭州'


@pytest.mark.parametrize('operation,words',[('resolve','行程已经完成了'),('cancel','行程取消了')])
def test_finished_or_cancelled_memory_stops_retrieval_but_keeps_history(operation,words):
    m=message('我明天去杭州。')
    end=message(words,T+60)
    with DB() as db:
        capture(db,1,m,[observation()],SETTINGS,T)
        key=list_memories(db,1,now=T)[0]['key']
        capture(db,1,end,[observation(words,evidence=words,existing_key=key,operation=operation)],SETTINGS,T+60,{key})
        db.commit()
        assert search(db,1,'杭州',now=T+61)==[]
        assert get(db,'memory',1,key).data['status']==('resolved' if operation=='resolve' else 'cancelled')
        assert not get(db,'memory',1,key).data['deleted']
        assert records(db,'revision',1)


def test_new_episode_does_not_resurrect_resolved_entry():
    m=message('我明天去杭州。');done=message('行程完成了',T+60);fresh=message('我明天去杭州。',T+86400)
    repeat=message('我明天去杭州。',T+86460)
    with DB() as db:
        capture(db,1,m,[observation()],SETTINGS,T);key=list_memories(db,1,now=T)[0]['key']
        capture(db,1,done,[observation('行程完成',evidence='行程完成了',operation='resolve',existing_key=key)],SETTINGS,T+60,{key})
        capture(db,1,fresh,[observation()],SETTINGS,T+86400)
        capture(db,1,repeat,[observation()],SETTINGS,T+86460)
        active=list_memories(db,1,now=T+86400)
        assert len(active)==1 and active[0]['key']!=key
        assert get(db,'memory',1,key).data['status']=='resolved'


def test_tentative_plan_and_temporary_state_do_not_become_long_term():
    plan=message('我考虑明天去杭州。')
    tired=message('今天有点累。')
    with DB() as db:
        capture(db,1,plan,[observation('妈妈考虑明天去杭州，尚未决定',tentative=True)],SETTINGS,T)
        capture(db,1,tired,[observation('妈妈今天有点累',evidence='今天有点累',category='state',topic='妈妈今天状态',stable=True,expires_at=T+7*86400)],SETTINGS,T)
        entries=list_memories(db,1,now=T)
        state=next(x for x in entries if x['category']=='state')
        assert state['expires_at']==T+86400
        tentative=next(x for x in entries if x['category']=='plan')
        assert tentative['tentative'] and not tentative['eligible_long_term']
        due(db,1,T+300);review(db,1,SETTINGS,T+300)
        assert all(r.data['lifetime']!='long' for r in records(db,'memory',1))


@pytest.mark.parametrize('raw',['不要记录，我明天去杭州。','明天去杭州拿药。','明天去杭州，银行卡密码1234。'])
def test_opt_out_and_sensitive_context_are_not_captured(raw):
    m=message(raw)
    with DB() as db:
        assert capture(db,1,m,[observation()],SETTINGS,T)==[]
        assert records(db,'memory',1)==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('intent',[{'kind':'joke'},{'kind':'discussion','quoted':True}])
async def test_quoted_or_joking_messages_do_not_create_short_memory(intent):
    m=message('引用：妈妈明天去杭州。')
    a=Agent(no_broadcast,FakeModel({'intent':intent,'memories':[observation()]}),lambda:T)
    await a.analyze(1,m)
    with DB() as db:assert records(db,'memory',1)==[]
    await a.close()


def test_manual_correction_is_protected_and_conflict_is_visible():
    m=message('我明天去杭州。')
    with DB() as db:
        manual=save_memory(db,1,'妈妈周末留在家里',[99],manual=True)
        capture(db,1,m,[observation(existing_key=manual.key,operation='update')],SETTINGS,T,{manual.key})
        assert manual.data['content']=='妈妈周末留在家里'
        assert records(db,'memory_conflict',1)[0].data['proposed']=='妈妈明天去杭州'


def test_deleted_sources_and_unknown_people_cannot_recreate_memory():
    m=message('我明天去杭州。')
    other=message('我明天去杭州。',T+2)
    with DB() as db:
        capture(db,1,m,[observation()],SETTINGS,T)
        entry=records(db,'memory',1)[0];delete_memory(db,entry)
        capture(db,1,m,[observation()],SETTINGS,T+1)
        assert capture(db,1,other,[observation(subject_ids=[99])],SETTINGS,T+2)==[]
        assert list_memories(db,1,now=T+2)==[]


def test_repeat_observations_on_three_days_promote_but_same_day_repeats_do_not():
    item=observation('妈妈喜欢喝淡茶',evidence='喜欢喝淡茶',category='preference',topic='妈妈饮茶偏好',stable=True)
    messages={offset:message('我喜欢喝淡茶。',T+offset) for offset in (0,60,120,86400,172800)}
    with DB() as db:
        for offset in (0,60,120):
            m=messages[offset]
            capture(db,1,m,[item],SETTINGS,T+offset)
        due(db,1,T+300);review(db,1,SETTINGS,T+300)
        assert list_memories(db,1,now=T+300)[0]['lifetime']=='short'
        for offset in (86400,172800):
            m=messages[offset]
            capture(db,1,m,[item],SETTINGS,T+offset)
        due(db,1,T+172801);review(db,1,SETTINGS,T+172801)
        entry=list_memories(db,1,now=T+172801)[0]
        assert entry['lifetime']=='long' and entry['expires_at'] is None
        assert not entry['confirmed']
        assert get(db,'memory_maintenance',1,'latest').data['counts']['promoted']==1
        assert any(r.data.get('operation')=='promote' for r in records(db,'revision',1))


def test_reanalysis_does_not_manufacture_independent_observations():
    m=message('我喜欢喝淡茶。')
    item=observation('妈妈喜欢喝淡茶',evidence='喜欢喝淡茶',category='preference',topic='饮茶',stable=True)
    with DB() as db:
        for _ in range(4):capture(db,1,m,[item],SETTINGS,T)
        assert len(records(db,'memory',1)[0].data['observations'])==1


def test_periodic_expiry_and_schedule_survive_restart_and_do_not_send_chat():
    with DB() as db:
        r=save_memory(db,1,'阶段性安排',[1],lifetime='short',expires_at=T+10,now=T)
        assert review(db,1,SETTINGS,T) is False
        assert get(db,'memory_maintenance',1,'latest').data['next_due']==T+21600
        assert review(db,1,SETTINGS,T+21600) is True
        assert r.data['status']=='expired'
        assert search(db,1,'阶段性',now=T+21600)==[]
        db.commit()
    with DB() as db:
        assert review(db,1,SETTINGS,T+21601) is False
        assert db.query(Message).filter_by(user_id=0).count()==0


@pytest.mark.asyncio
async def test_agent_scheduler_reviews_without_model_or_public_message():
    with DB() as db:
        save_memory(db,1,'今天临时安排',[1],lifetime='working',expires_at=T+10,now=T)
        due(db,1,T+11);db.commit()
    events=[]
    async def broadcast(gid,event):events.append((gid,event))
    a=Agent(broadcast,FakeModel(),lambda:T+11)
    await a.tick()
    with DB() as db:
        assert records(db,'memory',1)[0].data['status']=='expired'
        assert get(db,'memory_maintenance',1,'latest').data['runs']==1
        assert db.query(Message).filter_by(user_id=0).count()==0
        assert not records(db,'metric',1)
    assert (1,{'type':'refresh'}) in events
    assert a.model.calls==[]
    await a.close()


def test_changing_review_cadence_reschedules_but_preserves_dirty_work():
    from fastapi.testclient import TestClient
    from backend.app import app, agent
    agent.model=FakeModel()
    with TestClient(app) as client:
        settings=client.get('/api/groups/1/settings?user=dad').json()
        with DB() as db:
            put(db,'memory_maintenance',1,'latest',{'next_due':time.time()+21600,'dirty':False,'runs':0})
            db.commit()
        before=time.time()
        assert client.put('/api/groups/1/settings?user=dad',json={**settings,'memory_review_seconds':3600}).status_code==200
        with DB() as db:
            assert before+3599<=get(db,'memory_maintenance',1,'latest').data['next_due']<=time.time()+3600
            sooner=time.time()+120
            put(db,'memory_maintenance',1,'latest',{'next_due':sooner,'dirty':True,'runs':0});db.commit()
        assert client.put('/api/groups/1/settings?user=dad',json={**settings,'memory_review_seconds':7200}).status_code==200
        with DB() as db:assert get(db,'memory_maintenance',1,'latest').data['next_due']==sooner


def test_private_memory_subject_can_be_family_but_visibility_stays_private():
    m=message('爸爸明天去杭州。',gid=-3,user=3)
    with DB() as db:
        capture(db,-3,m,[observation('爸爸明天去杭州',subject_ids=[1],subjects=['爸爸'],topic='爸爸出行')],SETTINGS,T)
        assert len(list_memories(db,-3,viewer_id=3,now=T))==1
        assert list_memories(db,-3,viewer_id=1,now=T)==[]
        assert list_memories(db,1,now=T)==[]
        due(db,-3,T+300);review(db,-3,SETTINGS,T+300)
        assert status(db,1,T+300)['active']==0
        assert status(db,-3,T+300)['short']==1


def test_timed_plan_deadline_is_not_extended_by_a_repeat():
    first=message('我明天去杭州。')
    again=message('我明天去杭州。',T+60)
    with DB() as db:
        capture(db,1,first,[observation(expires_at=T+172800)],SETTINGS,T)
        capture(db,1,again,[observation()],SETTINGS,T+60)
        assert records(db,'memory',1)[0].data['expires_at']==T+172800


def test_expired_but_not_archived_plan_can_be_updated_without_invalid_expiry():
    first=message('我明天去杭州。')
    fresh=message('我明天去杭州。',T+180000)
    with DB() as db:
        capture(db,1,first,[observation(expires_at=T+172800)],SETTINGS,T)
        capture(db,1,fresh,[observation(operation='update')],SETTINGS,T+180000)
        entry=list_memories(db,1,now=T+180000)[0]
        assert entry['expires_at']>T+180000
        capture(db,1,first,[observation(operation='update')],SETTINGS,T+180001)
        assert list_memories(db,1,now=T+180001)[0]['expires_at']==entry['expires_at']


@pytest.mark.asyncio
@pytest.mark.parametrize('legacy',[False,True])
async def test_cancel_delta_does_not_require_model_to_regenerate_memory_fields(legacy):
    m=message('我明天去杭州。');end=message('我取消去杭州的安排了。',T+60)
    with DB() as db:
        capture(db,1,m,[observation()],SETTINGS,T);key=records(db,'memory',1)[0].key;db.commit()
    delta={'key':key,'state':'cancelled','text':'妈妈取消去杭州'} if legacy else {
        'key':key,'operation':'cancel','evidence':'我取消去杭州的安排了','confidence':.98}
    model=FakeModel({'intent':{'kind':'cancel','confidence':.99},'memory_updates':[delta]})
    a=Agent(no_broadcast,model,lambda:T+60)
    result=await a.analyze(1,end)
    with DB() as db:
        assert list_memories(db,1,now=T+60)==[]
        assert get(db,'memory',1,key).data['status']=='cancelled'
    assert result['memory_changes']==[{'key':key,'operation':'cancel'}]
    await a.close()


def test_legacy_delta_needs_explicit_latest_evidence_and_known_key():
    from backend.memory_lifecycle import transitions
    from backend.contracts import Intent
    known=[{'key':'plan','content':'妈妈明天去杭州'}]
    delta=[{'key':'plan','state':'cancelled','text':'妈妈取消行程'}]
    for text in ('天气不错。','我没有取消行程。','要不要取消行程？','我考虑取消行程。'):
        assert transitions(known,delta,message(text),Intent(kind='cancel',confidence=.99))==[]
    assert transitions(known,[{'key':'other','state':'cancelled'}],message('取消行程了'),Intent(kind='cancel',confidence=.99))==[]


def test_auto_capture_setting_and_evidence_validation():
    m=message('今天晴天。')
    m2=message('我明天去杭州。')
    with DB() as db:
        assert capture(db,1,m,[observation()],SETTINGS,T)==[]
        assert capture(db,1,m2,[observation()],{**SETTINGS,'memory_auto':False},T)==[]
        assert capture(db,1,m2,[observation(expires_at=float('nan'))],SETTINGS,T)==[]
        assert capture(db,1,m2,[observation(category=[])],SETTINGS,T)==[]
        assert capture(db,1,m2,[observation(existing_key=[])],SETTINGS,T,set())==[]


def test_brand_migration_is_repeatable_and_keeps_custom_prompt():
    with DB() as db:
        r=get(db,'group',1,'settings');r.set({**r.data,'agent_name':'小忆','prompt':LEGACY_PROMPT})
        put(db,'group',-1,'settings',{'agent_name':'小忆','prompt':'请记得称呼我老陈','version':1})
        db.execute(text('DELETE FROM schema_migrations WHERE version=4'));db.commit()
    migrate();migrate()
    with DB() as db:
        assert get(db,'group',1,'settings').data['agent_name']=='小艺'
        assert '陪伴型管家' in get(db,'group',1,'settings').data['prompt']
        private=get(db,'group',-1,'settings').data
        assert private['prompt']=='请记得称呼我老陈'
        assert '老陈' in system_prompt(private) and '小艺' in system_prompt(private)
    assert direct_mention('@小艺 你好','小艺') and direct_mention('@小忆 你好','小艺')
    assert direct_mention('小艺，今天有点累。','小艺')
    assert not direct_mention('妈妈说小艺今天有点累。','小艺')
    assert command_grants('@小艺 记住喜欢茶','小艺',T)==command_grants('@小忆 记住喜欢茶','小艺',T)
    assert command_grants('小艺，记住喜欢茶','小艺',T)==command_grants('@小艺 记住喜欢茶','小艺',T)
    assert not direct_mention('妈妈说：“@小艺 记住喜欢茶”','小艺')
    assert system_prompt({'prompt':DEFAULT_PROMPT+'\n这是本人的私人空间。'}).count('陪伴型管家')==1
