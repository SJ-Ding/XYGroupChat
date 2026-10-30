import json
import pytest
import httpx
from sqlalchemy import text
from fastapi.testclient import TestClient
from backend.model import Model, ModelError, parse_object
from backend.agent import Agent
from backend.app import app, agent
from backend.db import DB, Message, Record, get, put, records, migrate
from backend.memory import save_memory, list_memories, search
from backend.repairs import repair_legacy_harness
from test_system import FakeModel, no_broadcast


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-only-key')
    monkeypatch.setenv('DEEPSEEK_MODEL', 'deepseek-flash')
    monkeypatch.setenv('DEEPSEEK_BASE_URL', 'https://model.invalid')
    monkeypatch.delenv('DEEPSEEK_THINKING', raising=False)


def response(content, *, finish='stop', tokens=10, reasoning=None, calls=None):
    msg = {'role':'assistant','content':content}
    if reasoning is not None:
        msg['reasoning_content'] = reasoning
    if calls:
        msg['tool_calls'] = calls
    return httpx.Response(200, json={'choices':[{'message':msg,'finish_reason':finish}], 'usage':{'total_tokens':tokens}})


@pytest.mark.parametrize('value', ['{"ok":true}', '\ufeff{"ok":true}', '```json\n{"ok":true}\n```'])
def test_only_complete_objects_are_accepted(value):
    assert parse_object(value) == {'ok':True}


@pytest.mark.parametrize('value', ['', '[]', 'null', '{"value":NaN}', 'Here is JSON: {"ok":true}', '{"ok":'])
def test_invalid_or_embedded_decisions_are_rejected(value):
    with pytest.raises(ValueError): parse_object(value)


@pytest.mark.asyncio
async def test_structured_retry_is_bounded_and_aggregates_usage(provider, monkeypatch):
    monkeypatch.setenv('DEEPSEEK_THINKING', 'enabled')
    bodies = []
    def handler(request):
        body=json.loads(request.content);bodies.append(body)
        assert body['thinking']=={'type':'disabled'}
        return response('',tokens=7) if len(bodies)==1 else response('{"intent":{},"memories":[]}',tokens=11)
    model=Model(httpx.MockTransport(handler))
    original=[{'role':'user','content':'只输出JSON，不要创建待办'}]
    result=await model.call(original,structured=True)
    assert len(bodies)==2 and len(original)==1
    assert bodies[1]['max_tokens']>bodies[0]['max_tokens']
    assert result['_usage']['total_tokens']==18 and result['_attempts']==2
    assert result['memories']==[]


@pytest.mark.asyncio
async def test_truncated_analysis_is_discarded_even_if_object_parses(provider):
    calls=[]
    def handler(request):
        calls.append(1)
        return response('{"new_need":{"text":"should not use"}}',finish='length') if len(calls)==1 else response('{"new_need":null}')
    result=await Model(httpx.MockTransport(handler)).call([{'role':'user','content':'JSON'}],structured=True)
    assert result['new_need'] is None and len(calls)==2


@pytest.mark.asyncio
async def test_persistent_invalid_json_is_actionable_not_a_decoder_trace(provider):
    calls=[]
    def handler(request):
        calls.append(1);return response('')
    with pytest.raises(ModelError,match='已尝试2次') as error:
        await Model(httpx.MockTransport(handler)).call([{'role':'user','content':'JSON'}],structured=True)
    assert len(calls)==2 and error.value.kind=='structured'


@pytest.mark.asyncio
async def test_http_failure_is_not_retried_and_provider_body_is_not_exposed(provider):
    calls=[]
    def handler(request):
        calls.append(1)
        return httpx.Response(400,json={'error':{'message':'PRIVATE_SENTINEL request_id: request-12345678'}})
    with pytest.raises(ModelError,match='HTTP 400') as error:
        await Model(httpx.MockTransport(handler)).call([{'role':'user','content':'JSON'}],structured=True)
    assert len(calls)==1 and 'PRIVATE_SENTINEL' not in str(error.value)
    assert error.value.request_id=='request-12345678'


@pytest.mark.asyncio
async def test_thinking_is_opt_in_for_chat_and_not_sent_to_other_models(provider, monkeypatch):
    bodies=[]
    def handler(request):
        bodies.append(json.loads(request.content));return response('ok')
    model=Model(httpx.MockTransport(handler))
    await model.call([{'role':'user','content':'test'}])
    assert bodies[-1]['thinking']['type']=='disabled'
    monkeypatch.setenv('DEEPSEEK_THINKING','enabled')
    await model.call([{'role':'user','content':'test'}])
    assert bodies[-1]['thinking']['type']=='enabled'
    monkeypatch.setenv('DEEPSEEK_MODEL','another-compatible-model')
    await model.call([{'role':'user','content':'test'}])
    assert 'thinking' not in bodies[-1]


def seed(text_value='@小忆 记住测试角色妈妈喜欢蓝星茶'):
    with DB() as db:
        msg=Message(group_id=1,user_id=2,client_id='recovery-source',content=text_value,attachments='[]')
        db.add(msg);db.flush()
        settings=get(db,'group',1,'settings').data
        put(db,'job',1,str(msg.id),{'source':msg.id,'mention':True,'settings':settings,'status':'pending','analyzed':False})
        db.commit();return msg.id,settings


@pytest.mark.asyncio
async def test_write_receipts_are_not_fabricated_assistant_tool_turns():
    class ReceiptModel(FakeModel):
        async def call(self,messages,tools=None,structured=False):
            if structured: return self.analysis
            assert not any(m.get('tool_calls') for m in messages)
            assert any('server_action_results' in str(m.get('content')) for m in messages)
            assert 'remember' not in [t['function']['name'] for t in tools]
            return {'content':'已记录'}
    mid,settings=seed()
    a=Agent(no_broadcast,ReceiptModel())
    await a.process(1,str(mid))
    with DB() as db:
        assert get(db,'job',1,str(mid)).data['status']=='done'
        assert len(records(db,'memory',1))==1
    await a.close()


@pytest.mark.asyncio
async def test_real_model_tool_metadata_is_preserved_only_in_ephemeral_context():
    class ToolModel(FakeModel):
        def __init__(self): super().__init__();self.turn=0
        async def call(self,messages,tools=None,structured=False):
            if structured: return self.analysis
            self.turn+=1
            if self.turn==1:
                return {'role':'assistant','content':'','reasoning_content':'opaque-protocol-state',
                    'tool_calls':[{'id':'actual-call','type':'function','function':{'name':'memory_search','arguments':'{"query":"蓝星茶"}'}}]}
            prior=next(m for m in messages if m.get('tool_calls'))
            assert prior['reasoning_content']=='opaque-protocol-state'
            return {'content':'没有找到'}
    mid,settings=seed('@小忆 查询蓝星茶')
    a=Agent(no_broadcast,ToolModel())
    await a.process(1,str(mid))
    with DB() as db:
        assert get(db,'job',1,str(mid)).data['status']=='done'
        assert all('opaque-protocol-state' not in r.payload for r in db.query(Record).all())
        assert all('opaque-protocol-state' not in m.content for m in db.query(Message).all())
    await a.close()


@pytest.mark.asyncio
async def test_reply_retry_skips_successful_tools_and_reports_partial_state(monkeypatch):
    import backend.agent as module
    class BrokenReply(FakeModel):
        async def call(self,messages,tools=None,structured=False):
            if structured:
                return {'memories':[{'content':'妈妈喜欢蓝星茶','confidence':.99}], 'reason':'明确记住'}
            raise RuntimeError('模拟回复网络失败')
    calls=[];original=module.execute
    async def track(*args):
        calls.append(args[0]);return await original(*args)
    monkeypatch.setattr(module,'execute',track)
    mid,settings=seed()
    a=Agent(no_broadcast,BrokenReply())
    await a.process(1,str(mid))
    with DB() as db:
        d=get(db,'job',1,str(mid)).data
        r=get(db,'run',1,'mention:'+str(mid)).data
        assert d['status']=='reply_failed' and d['action_status']=='succeeded'
        assert r['status']=='succeeded' and r['reply_status']=='failed'
        assert len(list_memories(db,1))==1  # explicit command skipped auto extraction
        put(db,'job',1,str(mid),{**d,'status':'pending'});db.commit()
    a.model=FakeModel()
    await a.process(1,str(mid))
    assert calls==['remember']
    with DB() as db:
        assert get(db,'job',1,str(mid)).data['status']=='done'
        assert get(db,'run',1,'mention:'+str(mid)).data['reply_status']=='sent'
        assert db.query(Message).filter_by(user_id=0).filter(~Message.client_id.startswith('card:')).count()==1
        assert len(list_memories(db,1))==1
    await a.close()


def test_explicit_memory_merge_is_audited_and_not_a_suppression():
    with DB() as db:
        auto=save_memory(db,1,'近义自动事实',[5]);auto_key=auto.key
        canonical=save_memory(db,1,'用户明确事实',[5],manual=True,explicit=True)
        save_memory(db,1,'另一个不同来源事实',[6])
        db.commit()
        assert auto.data['deleted'] and auto.data['merged_into']==canonical.key
        assert len(list_memories(db,1))==2
        assert records(db,'revision',1)[0].data['operation']=='merge_explicit'
        assert records(db,'suppression',1)==[]
        assert save_memory(db,1,'再次近义提取',[5]).key==canonical.key
        assert get(db,'memory',1,auto_key) is not None


def test_versioned_repair_preserves_independent_facts_and_reclassifies_reply_failure():
    mid,settings=seed()
    with DB() as db:
        auto=save_memory(db,1,'旧自动蓝星茶事实',[mid]);auto_key=auto.key
        manual=save_memory(db,1,'旧手动蓝星茶事实',[mid],manual=True);manual_key=manual.key
        save_memory(db,1,'其他来源事实',[mid+100])
        put(db,'run',1,'mention:'+str(mid),{'conversation':True,'status':'failed','steps':[{'id':'0','tool':'remember','arguments':{'content':'旧手动蓝星茶事实'},'status':'succeeded','result':{'key':manual.key}}]})
        job=get(db,'job',1,str(mid));job.set({**job.data,'status':'failed','analyzed':True,'error':'HTTP400'})
        db.execute(text('DELETE FROM schema_migrations WHERE version=3'));db.commit()
    migrate();migrate()
    with DB() as db:
        assert get(db,'memory',1,auto_key).data['merged_into']==manual_key
        assert len(list_memories(db,1))==2
        assert get(db,'job',1,str(mid)).data['status']=='reply_failed'
        assert get(db,'run',1,'mention:'+str(mid)).data['status']=='succeeded'
        assert repair_legacy_harness(db)=={'merged_memories':0,'reply_failures_reclassified':0}


def test_manual_edit_of_a_multi_fact_chat_does_not_merge_other_facts():
    mid,settings=seed('妈妈喜欢茶，爸爸喜欢散步。')
    with DB() as db:
        save_memory(db,1,'爸爸喜欢散步',[mid])
        save_memory(db,1,'妈妈喜欢茶',[mid],manual=True)
        db.commit()
        assert repair_legacy_harness(db)['merged_memories']==0
        assert len(list_memories(db,1))==2


@pytest.mark.asyncio
async def test_reply_retry_reports_current_task_state_without_resetting_it():
    class ReplyModel(FakeModel):
        fail=True
        async def call(self,messages,tools=None,structured=False):
            if structured: return self.analysis
            if self.fail: raise RuntimeError('reply failure')
            receipt=next(json.loads(m['content']) for m in messages if m['role']=='user' and isinstance(m.get('content'),str) and 'server_action_results' in m['content'])
            assert receipt['server_action_results'][0]['result']['done'] is True
            return {'content':'该待办已完成'}
    model=ReplyModel();mid,settings=seed('@小忆 添加待办：纸鹤')
    a=Agent(no_broadcast,model)
    await a.process(1,str(mid))
    with DB() as db:
        task=records(db,'task',1)[0];task.set({**task.data,'done':True})
        job=get(db,'job',1,str(mid));job.set({**job.data,'status':'pending'});db.commit()
    model.fail=False
    await a.process(1,str(mid))
    with DB() as db:
        assert records(db,'task',1)[0].data['done'] is True
        assert get(db,'job',1,str(mid)).data['status']=='done'
    await a.close()
