import json
import threading
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from backend import care_seed, democlock
from backend.db import DB, Message, User, get, records
from backend.skills import SkillContext
from backend.prognosis import draft, activate
from backend.reply_memory import persist
from backend.hospital_simulator import AppointmentManager

@pytest.fixture
def family():
    care_seed.reset()
    with DB() as db:
        uid = db.query(User).filter_by(username='mom').first().id
        source = Message(group_id=1,user_id=uid,client_id='source',content='按药单每天8点提醒，三天',attachments='["image"]')
        db.add(source); db.flush()
        reply = Message(group_id=1,user_id=0,client_id='ocr',content='药单：氨氯地平5mg，每天一次，连续三天。',attachments='[]')
        db.add(reply); db.commit()
        return uid, source, reply

@pytest.mark.asyncio
async def test_plan_confirmation_idempotency_and_empty_selection(family):
    uid, source, reply = family
    # User requests using historical OCR in a subsequent message.
    with DB() as db:
        request = Message(group_id=1,user_id=uid,client_id='request',content='按刚才药单提醒',attachments='[]')
        db.add(request); db.commit()
    ctx = SkillContext(1,uid,'plan',request.id)
    args = {'patient_name':'妈妈','items':[{'type':'medication','title':'氨氯地平5mg','detail':'每日一次',
        'source_id':reply.id,'evidence':'氨氯地平5mg','at':democlock.now()+3600}]}
    result = await draft(ctx,args)
    assert result['status'] == 'awaiting_confirmation'
    with DB() as db:
        before = len(records(db,'reminder',1))
        card = get(db,'card',1,result['card_id']).data
        activate(db,1,card,'confirm_plan',['0'],uid); db.commit()
        assert len(records(db,'reminder',1)) == before+1
        activate(db,1,card,'confirm_plan',['0'],uid); db.commit()
        assert len(records(db,'reminder',1)) == before+1
        created = get(db,'reminder',1,result['card_id']+':0')
        assert created.data['source_id'] == reply.id
        from backend.proactive import schedule_tick
        assert schedule_tick(db,1,democlock.now()+3601)
        activate(db,1,card,'cancel_plan',None,uid); db.commit()
        assert get(db,'reminder',1,result['card_id']+':0').data['status'] == 'cancelled'
    args['items'][0]['at'] += 3600
    result = await draft(ctx,args)
    with DB() as db:
        before = len(records(db,'reminder',1))
        card = get(db,'card',1,result['card_id']).data
        activate(db,1,card,'confirm_plan',[],uid); db.commit()
        assert len(records(db,'reminder',1)) == before

@pytest.mark.asyncio
async def test_plan_rejects_cross_chat_and_missing_evidence(family):
    uid, source, reply = family
    ctx = SkillContext(-uid,uid,'private',source.id)
    result = await draft(ctx, {'patient_name':'妈妈','items':[{'type':'followup','title':'复诊','detail':'',
        'source_id':reply.id,'evidence':'不存在','at':democlock.now()+3600}]})
    assert 'error' in result

def test_reply_memory_preview_dedup_optout_and_provenance(family):
    uid, source, reply = family
    facts = [{'content':'药单记录氨氯地平5mg','evidence':'氨氯地平5mg','domain':'medical','subject_ids':[uid],
              'subjects':['妈妈'],'basis':'image'}]
    with DB() as db:
        before = len(records(db,'memory',1))
        assert persist(db,1,source,reply,facts,democlock.now(),preview=True)
        assert len(records(db,'memory',1)) == before
        result = persist(db,1,source,reply,facts,democlock.now()); db.commit()
        value = get(db,'memory',1,result[0]['key']).data
        assert value['attachment_ids'] == ['image'] and value['reply_id'] == reply.id
        assert value['domain'] == 'medical' and source.id in value['sources']
        assert not persist(db,1,source,reply,facts,democlock.now())
        source.content += '不要记住'
        assert not persist(db,1,source,reply,[{**facts[0],'content':'另一条'}],democlock.now())

def test_clicks_throttled_and_no_fabricated_result(monkeypatch):
    import backend.hospital_simulator as sim
    now = [10.0]; delays=[]; clicks=[]
    monkeypatch.setattr(sim.time,'monotonic',lambda:now[0])
    class Page:
        def wait_for_timeout(self,ms):
            delays.append(ms); now[0] += ms/1000
    class Locator:
        def click(self,**kw): clicks.append(now[0])
    session=SimpleNamespace(stop=threading.Event())
    manager=AppointmentManager()
    manager._click(Page(),Locator(),session)
    manager._click(Page(),Locator(),session)
    assert 1.5 <= clicks[1]-clicks[0] < 1.51
    with pytest.raises(RuntimeError,match='编号'):
        manager._complete(session,SimpleNamespace(inner_text=lambda _: '预约失败'))

@pytest.mark.asyncio
async def test_discovery_failure_never_returns_fake_hospitals(monkeypatch):
    from backend import hospital_discovery as discovery
    async def failure(*args):
        return {'error': '高德暂不可用'}
    monkeypatch.setattr(discovery, 'amap_mcp', failure)
    with pytest.raises(ValueError, match='高德暂不可用'):
        await discovery.discover('南京市鼓楼区中山北路')

def test_old_appointment_identity_is_preserved():
    from backend.hospital_data import public
    old = {'id':'AP-OLD','campusName':'原演示医院总院','status':'cancelled'}
    result = public(old)
    assert result['hospitalId'] == 'legacy-hospital'
    assert result['hospitalName'] == old['campusName']
    assert 'hospitalId' not in old

def test_new_hospitals_have_real_source_and_distinct_ids():
    from backend.hospital_data import catalog
    hospitals = catalog()['hospitals']
    assert len({h['id'] for h in hospitals}) == 2
    assert all(h['source'] == '高德 MCP' and h['poiId'] and h['address'] for h in hospitals)
    assert {c['hospitalId'] for c in catalog()['campuses']} == {h['id'] for h in hospitals}
