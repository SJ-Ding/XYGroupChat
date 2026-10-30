from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from backend.agent import Agent
from backend.authorization import command_grants
from backend.contracts import ConversationEvent, Intent
from backend.db import DB, Message, get, put, records
from backend.participation import decide
from backend.reminder_language import reminder_request
from test_system import FakeModel, no_broadcast

ZONE = ZoneInfo('Asia/Shanghai')
T = datetime(2026,10,30,15,7,10,tzinfo=ZONE).timestamp()

def local(at):
    return datetime.fromtimestamp(at,ZONE).strftime('%Y-%m-%d %H:%M')

@pytest.mark.parametrize('text,expected', [
    ('三点一刻的时候提醒我出门','2026-10-30 15:15'),
    ('今天下午三点一刻提醒我出门','2026-10-30 15:15'),
    ('15:15提醒我出门','2026-10-30 15:15'),
    ('三点一刻提醒出门','2026-10-30 15:15'),
    ('下午四点钟的时候提醒我出门','2026-10-30 16:00'),
    ('一分钟后提醒出门','2026-10-30 15:08'),
    ('下午三点十五分的时候提醒我出门','2026-10-30 15:15'),
    ('下午三点半提醒我出门','2026-10-30 15:30'),
    ('明天下午三点三刻提醒我出门','2026-10-31 15:45'),
    ('十五分钟后提醒我出门','2026-10-30 15:22'),
    ('@小艺 二十分钟后提醒我出门','2026-10-30 15:27'),
    ('提醒我下午三点一刻出门','2026-10-30 15:15'),
    ('晚上十二点提醒我出门','2026-10-31 00:00'),
    ('明天上午十二点提醒我出门','2026-10-31 12:00'),
])
def test_reminder_language_resolves_source_time(text,expected):
    request=reminder_request(text,'小艺',T)
    assert request and request.clarification is None
    assert request.content == '出门'
    assert local(request.at)==expected
    assert command_grants(text,'小艺',T)==[{'tool':'group_reminder','arguments':{'content':'出门','at':request.at}}]

@pytest.mark.parametrize('text', [
    '今天下午两点提醒我出门','明天三点一刻提醒我出门',
    '提醒我出门','今天25:80提醒我出门','周六三点提醒我出门','三点一刻提醒我','提醒我下午四点半','提醒我15:15',
])
def test_ambiguous_or_past_time_requires_clarification_without_grants(text):
    request=reminder_request(text,'小艺',T)
    assert request and request.at is None and request.clarification
    assert command_grants(text,'小艺',T)==[]

@pytest.mark.parametrize('text', [
    '妈妈，三点一刻提醒我出门','他说三点一刻提醒我出门',
    '不要三点提醒我出门','三点不要提醒我出门','如果三点提醒我出门',
    '引用：三点一刻提醒我出门','> @小艺 三点一刻提醒我出门',
    '他说“三点一刻提醒我出门”','我明天下午三点出门','三点妈妈说提醒我出门','三点不要提醒我','三点提醒的事情做完了','三点提醒我什么',
])
def test_narratives_negations_quotes_and_family_addressees_do_not_grant(text):
    assert reminder_request(text,'小艺',T) is None
    assert command_grants(text,'小艺',T)==[]

@pytest.mark.asyncio
async def test_explicit_reminder_corrects_model_discussion_without_memory_or_demand():
    model=FakeModel({'intent':{'kind':'discussion','target':'group','confidence':.99},'memories':[{'content':'妈妈想出门'}]})
    a=Agent(no_broadcast,model,lambda:T)
    with DB() as db:
        m=Message(group_id=1,user_id=2,client_id='r',content='三点一刻的时候提醒我出门',created=T)
        db.add(m);db.commit()
    result=await a.analyze(1,m)
    assert result['decision']['action']=='reply'
    assert result['memory_changes']==[]
    from backend.debugging import message_annotations
    assert message_annotations(1,[m.id])[str(m.id)]['intent']['kind']=='request'
    with DB() as db:
        assert records(db,'demand',1)==[]
        assert records(db,'reminder',1)==[]  # Understanding alone does not execute.
    await a.close()

@pytest.mark.asyncio
async def test_end_to_end_reminder_ack_scheduled_once_and_delivered_once():
    clock=[T]
    a=Agent(no_broadcast,FakeModel(),lambda:clock[0])
    with DB() as db:
        m=Message(group_id=1,user_id=2,client_id='r',content='三点一刻的时候提醒我出门',created=T)
        db.add(m);db.flush()
        put(db,'job',1,str(m.id),{'source':m.id,'mention':False,'status':'pending','settings':get(db,'group',1,'settings').data})
        db.commit()
    await a.process(1,str(m.id))
    await a.process(1,str(m.id))
    with DB() as db:
        assert get(db,'job',1,str(m.id)).data['replied'] is True
        reminders=records(db,'reminder',1)
        assert len(reminders)==1
        assert local(reminders[0].data['at'])=='2026-10-30 15:15'
        assert reminders[0].data['content']=='出门'
        assert reminders[0].data['user_id']==2
        assert db.query(Message).filter_by(user_id=0,client_id='mention:'+str(m.id)).count()==1
        assert db.query(Message).filter_by(user_id=0,client_id='delivery:reminder:'+reminders[0].key+':v1:'+str(reminders[0].data['at'])).count()==0
        clock[0]=reminders[0].data['at']
    await a.tick();await a.tick()
    with DB() as db:
        assert get(db,'reminder',1,reminders[0].key).data['sent'] is True
        assert db.query(Message).filter_by(user_id=0,client_id='delivery:reminder:'+reminders[0].key+':v1:'+str(reminders[0].data['at'])).count()==1
    await a.close()

@pytest.mark.asyncio
async def test_missing_time_gets_clarification_instead_of_false_confirmation():
    a=Agent(no_broadcast,FakeModel(),lambda:T)
    with DB() as db:
        m=Message(group_id=1,user_id=2,client_id='no-time',content='提醒我出门',created=T)
        db.add(m);db.flush()
        put(db,'job',1,str(m.id),{'source':m.id,'mention':False,'status':'pending','settings':get(db,'group',1,'settings').data})
        db.commit()
    await a.process(1,str(m.id))
    with DB() as db:
        assert records(db,'reminder',1)==[]
        answer=db.query(Message).filter_by(user_id=0,client_id='mention:'+str(m.id)).one()
        assert '什么时候' in answer.content
    assert len(a.model.calls)==1  # Clarification does not ask the model to invent a schedule.
    await a.close()

@pytest.mark.parametrize('text,intent,active,expected',[
    ('顾村公园下午开放吗',Intent(kind='request',target='agent',confidence=.95,assistant_helpful=True),True,'reply'),
    ('三点一刻的时候提醒我出门',Intent(kind='request',target='agent',confidence=.95,assistant_helpful=True),False,'reply'),
    ('我去图书馆的安排改到后天下午',Intent(kind='request',target='agent',confidence=.99,assistant_helpful=True),True,'silent'),
    ('妈妈，晚饭怎么安排',Intent(kind='request',target='member',confidence=.95,assistant_helpful=True),True,'observe'),
])
def test_participation_respects_target_and_statement_guard(text,intent,active,expected):
    event=ConversationEvent(1,2,9,text,T)
    assert decide(event,intent,{'active':active}).action==expected
