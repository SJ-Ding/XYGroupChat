"""Task progress is one durable card; short tools reply inline without chatter."""
import asyncio
import pytest
from backend.agent import Agent
from backend.app import serialized
from backend.cards import save_card, sync_run
from backend.db import DB, Message, get, put, records

async def silent(*args): pass

def source():
    with DB() as db:
        m=Message(group_id=1,user_id=1,client_id='request',content='@小艺 帮我规划一下')
        db.add(m);db.flush()
        put(db,'job',1,str(m.id),{'source':m.id,'mention':True,'settings':get(db,'group',1,'settings').data,'status':'pending','analyzed':False})
        db.commit();return m.id

class Planner:
    async def call(self,messages,tools=None,structured=False):
        if structured: return {'intent': {'kind':'request','target':'agent','engagement':'addressed','confidence':.99}, 'new_need':None,'updates':[],'memories':[],'reason':'明确请求'}
        if messages[-1]['role']=='tool': return {'content':'这是规划结果。'}
        return {'tool_calls':[{'id':'load','type':'function','function':{'name':'skill_load','arguments':'{"name":"family-meals"}'}}]}

@pytest.mark.asyncio
async def test_one_card_no_ack_dynamic_phase_and_plain_result():
    phases=[]
    async def events(gid,event):
        if event['type']=='task_update': phases.append(event['task']['phase'])
    a=Agent(events,Planner());mid=source()
    await a.process(1,str(mid))
    with DB() as db:
        cards=records(db,'card',1)
        assert len(cards)==1
        assert cards[0].data['title']=='任务进度'
        assert not any(m.content=='我开始整理这项任务了，你们可以继续聊，完成后我把结果发过来。' for m in db.query(Message).all())
    await a.background.schedule();await asyncio.gather(*list(a.pending))
    assert 'loading_skill' in phases and 'thinking' in phases
    with DB() as db:
        card=records(db,'card',1)[0].data
        assert card['status']=='succeeded'
        result=db.query(Message).filter(Message.client_id.startswith('result:')).one()
        assert result.content=='这是规划结果。'
        row=serialized(db,result)
        assert 'reply_to' not in row
        assert records(db,'message_reply',1)==[]
    await a.background.schedule();await asyncio.gather(*list(a.pending))
    with DB() as db: assert db.query(Message).filter(Message.client_id.startswith('result:')).count()==1
    await a.close()

@pytest.mark.asyncio
async def test_simple_tool_shows_progress_and_sends_separate_result():
    entered,gate=asyncio.Event(),asyncio.Event()
    class Quick(Planner):
        async def call(self,messages,tools=None,structured=False):
            if structured: return await super().call(messages,tools,structured)
            if messages[-1]['role']=='tool':
                entered.set();await gate.wait();return {'content':'查好了，没有相关记录。'}
            return {'tool_calls':[{'id':'search','type':'function','function':{'name':'memory_search','arguments':'{"query":"采购"}'}}]}
    a=Agent(silent,Quick());mid=source();task=asyncio.create_task(a.process(1,str(mid)))
    await asyncio.wait_for(entered.wait(),2)
    with DB() as db:
        cards = records(db,'card',1)
        assert len(cards) == 1 and cards[0].data['kind'] == 'progress'
        assert cards[0].data['status'] == 'running'
        assert cards[0].data['description'] == '整理回复'
    gate.set();await task
    with DB() as db:
        assert records(db,'card',1)[0].data['status'] == 'succeeded'
        assert db.query(Message).filter_by(user_id=0, client_id='mention:' + str(mid)).one().content=='查好了，没有相关记录。'
    await a.close()

def test_legacy_noise_is_hidden_and_result_retains_content():
    with DB() as db:
        put(db,'run',1,'mention:1',{'title':'@小艺 帮我规划一下','status':'succeeded','conversation':True,'steps':[]})
        old=save_card(db,1,'run:mention:1',{'title':'@小艺 帮我规划一下'},kind='progress',run_key='mention:1')
        ack=Message(group_id=1,user_id=0,client_id='mention:1',content='我开始整理这项任务了，你们可以继续聊，完成后我把结果发过来。');db.add(ack)
        put(db,'run',1,'skill:mention:1',{'title':'@小艺 帮我规划一下','status':'succeeded','kind':'skill','steps':[]})
        card=sync_run(db,1,'skill:mention:1')
        result=Message(group_id=1,user_id=0,client_id='result:skill:mention:1:succeeded:0',content='【@小艺 帮我规划一下】\n实际规划结果');db.add(result);db.flush()
        assert serialized(db,db.get(Message,old['message_id']))['hidden']
        assert serialized(db,ack)['hidden']
        row=serialized(db,result)
        assert row['content']=='实际规划结果' and 'reply_to' not in row

@pytest.mark.asyncio
async def test_fixed_steps_push_one_separate_result_card():
    from backend.orchestration import create_run, run_steps
    from backend.cards import publish_run
    with DB() as db:
        create_run(db, 1, 'separate-result', 1, '创建采购待办', [
            {'tool': 'family_tasks', 'arguments': {'action': 'create', 'title': '买番茄'}}], True)
        db.commit()
    await run_steps(1, 'separate-result')
    await publish_run(1, 'separate-result')
    with DB() as db:
        progress = get(db, 'card', 1, 'run:separate-result').data
        result = get(db, 'card', 1, 'result:separate-result').data
        assert progress['status'] == 'succeeded'
        assert result['kind'] == 'info'
        assert progress['message_id'] != result['message_id']
        assert result['items'][0]['value'] == '买番茄'
        assert db.query(Message).filter_by(client_id='card:result:separate-result').count() == 1
