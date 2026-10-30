import asyncio
import json
import pytest
from fastapi.testclient import TestClient
from backend.app import app, agent
from backend.agent import Agent
from backend.db import DB, Message, get, put
from backend.debugging import message_list, message_detail, traced_call
from test_system import FakeModel, no_broadcast, seed_demand

@pytest.mark.asyncio
async def test_actual_context_and_decision_are_durable():
    mid = seed_demand()
    model = FakeModel({'intent': {'kind': 'discussion', 'confidence': .95}, 'reason': '普通聊天', 'memories': [], 'updates': []})
    a = Agent(no_broadcast, model)
    with DB() as db:
        message = db.get(Message, mid)
        settings = get(db, 'group', 1, 'settings').data
    await a.analyze(1, message)
    await a.generate(1, mid, settings, 'test-run')
    detail = message_detail(1, mid)
    assert detail['decision']['action'] == 'silent'
    assert [t['phase'] for t in detail['traces']] == ['analysis', 'reply']
    trace = detail['traces'][0]
    assert trace['messages'] == model.calls[0][0]
    assert trace['status'] == 'done'
    assert trace['response']['reason'] == '普通聊天'
    # Editing current settings cannot rewrite the historical request snapshot.
    with DB() as db:
        settings = dict(settings, prompt='NEW_PROMPT_SENTINEL')
        put(db, 'group', 1, 'settings', settings)
        db.commit()
    assert 'NEW_PROMPT_SENTINEL' not in json.dumps(message_detail(1, mid))
    await a.close()

@pytest.mark.asyncio
async def test_trace_omits_image_bytes_reasoning_and_records_failure():
    class Model:
        async def call(self, *args, **kwargs):
            return {'content': '公开回复', 'reasoning_content': 'PRIVATE_REASONING', '_usage': {'total_tokens': 10}}
    mid = seed_demand()
    a = Agent(no_broadcast, Model())
    request = [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:SECRET_IMAGE'}}]}]
    await traced_call(a, 1, mid, 'reply', request)
    assert request[0]['content'][0]['image_url']['url'] == 'data:SECRET_IMAGE'
    result = json.dumps(message_detail(1, mid))
    assert 'SECRET_IMAGE' not in result and 'PRIVATE_REASONING' not in result
    class Broken:
        async def call(self, *args, **kwargs):
            raise RuntimeError('provider credential sentinel')
    a.model = Broken()
    with pytest.raises(RuntimeError):
        await traced_call(a, 1, mid, 'analysis', [{'role': 'user', 'content': 'hello'}], structured=True)
    trace = message_detail(1, mid)['traces'][-1]
    assert trace['status'] == 'failed' and trace['error'] == 'RuntimeError'
    assert 'credential sentinel' not in json.dumps(trace)
    await a.close()


def test_pagination_history_and_detail_whitelist():
    with DB() as db:
        for i in range(33):
            db.add(Message(group_id=1, user_id=1, client_id=f'm{i}', content=f'消息{i}'))
        db.add(Message(group_id=1, user_id=0, client_id='bot', content='助手消息'))
        db.add(Message(group_id=2, user_id=1, client_id='other', content='OTHER_GROUP'))
        db.commit()
    first = message_list(1)
    second = message_list(1, first['next_before'])
    assert len(first['items']) == 30 and len(second['items']) == 3
    assert second['next_before'] is None
    assert not ({r['id'] for r in first['items']} & {r['id'] for r in second['items']})
    mid = first['items'][0]['id']
    with DB() as db:
        put(db, 'job', 1, 'test', {'source': mid, 'status': 'pending', 'settings': {'prompt': 'SETTINGS_SECRET'}})
        put(db, 'trace', 2, 'other', {'source': mid, 'messages': ['OTHER_GROUP']})
        db.commit()
    detail = message_detail(1, mid)
    assert detail['traces'] == [] and detail['decision'] is None
    assert 'SETTINGS_SECRET' not in json.dumps(detail)
    assert message_detail(2, mid) is None


def test_debug_endpoints_scope():
    mid = seed_demand()
    agent.model = FakeModel()
    with TestClient(app) as client:
        root = '/api/groups/1/agent/messages'
        assert client.get(root).status_code == 400
        assert client.get(root + '?user=dad').status_code == 200
        assert client.get(root + f'/{mid}?user=dad').status_code == 200
        assert client.get(root + '/999999?user=dad').status_code == 404
        assert client.get('/api/groups/2/agent/messages?user=dad').status_code == 403
        assert client.get(f'/api/groups/2/agent/messages/{mid}?user=dad').status_code == 403

def test_agent_observer_identity_permissions_and_chat():
    mid = seed_demand()
    agent.model = FakeModel()
    with TestClient(app) as client:
        assert client.get('/api/me?user=agent').json()['observer'] is True
        assert [g['id'] for g in client.get('/api/groups?user=agent').json()] == [1]
        assert client.get('/api/groups/1/messages?user=agent').status_code == 200
        assert client.get(f'/api/groups/1/agent/annotations?user=agent&ids={mid}').status_code == 200
        assert client.get('/api/groups/2/messages?user=agent').status_code == 403
        assert client.post('/api/groups/1/messages?user=agent',json={'client_id':'spoof','content':'hello'}).status_code == 403
        assert client.put('/api/groups/1/settings?user=agent',json={}).status_code == 403
        assert client.get('/api/groups/1/agent/annotations?user=agent&ids=bad').status_code == 422
        assert client.get('/api/groups/1/agent/annotations?user=agent&ids='+','.join(['1']*101)).status_code == 422
        with client.websocket_connect('/ws/1?user=agent',headers={'origin':'http://testserver'}) as ws:
            assert ws.receive_json()['type'] == 'presence'
            ws.send_text('ping')
            assert ws.receive_json()['type'] == 'pong'


def test_agent_observer_cannot_bypass_auth(monkeypatch):
    from backend.auth import configure_password, login, COOKIE
    agent.model = FakeModel()
    monkeypatch.setenv('AUTH_REQUIRED','true')
    with TestClient(app) as client:
        assert client.get('/api/me?user=agent').status_code == 401
        assert client.get('/api/groups/1/messages?user=agent').status_code == 401
        configure_password('dad','test-password-for-observer')
        token, _ = login('dad','test-password-for-observer','127.0.0.1')
        client.cookies.set(COOKIE,token)
        me = client.get('/api/me?user=agent').json()
        assert me['observer'] and me['username'] == 'agent' and me['authenticated']
        assert client.get('/api/groups/1/messages?user=agent').status_code == 200
        assert client.get('/api/groups/2/messages?user=agent').status_code == 403
        assert client.post('/api/groups/1/messages?user=agent',json={'client_id':'spoof','content':'hello'}).status_code == 403
        assert client.get('/api/me?user=dad').json()['username'] == 'dad'


def test_chat_annotations_classification_and_exact_reply_provenance():
    from backend.debugging import message_annotations
    mid = seed_demand()
    with DB() as db:
        put(db,'job',1,str(mid),{'source':mid,'status':'done'})
        put(db,'decision',1,str(mid),{'action':'reply','reason':'直接求助','topic':'晚餐'})
        put(db,'trace',1,'analysis',{'source':mid,'phase':'analysis','response':{'intent':{'kind':'request','confidence':.98}}})
        put(db,'trace',1,'reply',{'source':mid,'phase':'reply','run_id':f'mention:{mid}','response':{'content':'这条回复'}})
        put(db,'trace',1,'unrelated-run',{'source':mid,'phase':'reply','run_id':'other-run'})
        put(db,'trace',2,'other-group',{'source':mid,'phase':'reply','run_id':f'mention:{mid}'})
        reply = Message(group_id=1,user_id=0,client_id=f'mention:{mid}',content='这条回复')
        reminder = Message(group_id=1,user_id=0,client_id='reminder:1',content='提醒')
        hidden = Message(group_id=2,user_id=1,client_id='private',content='私密')
        db.add_all([reply,reminder,hidden]);db.commit()
    rows = message_annotations(1,[mid,reply.id,reminder.id,hidden.id])
    assert rows[str(mid)]['decision']['action'] == 'reply'
    assert rows[str(mid)]['intent']['confidence'] == .98
    assert rows[str(reply.id)] == {'source':mid,'trace_keys':['reply']}
    assert rows[str(reminder.id)] == {'source':None,'trace_keys':[]}
    assert str(hidden.id) not in rows
