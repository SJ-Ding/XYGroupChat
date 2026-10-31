import asyncio
import copy
import json
import pytest
from backend.agent import Agent
from backend.db import DB, Message, get, put, records
from backend.memory import save_memory, delete_memory
from backend.monitor import snapshot
from backend.skills import SkillContext, Skill, REGISTRY, execute, schema
from test_system import no_broadcast


def seed(text='帮我安排家庭菜单', job=False):
    with DB() as db:
        m = Message(group_id=1, user_id=1, client_id=text, content=text)
        db.add(m)
        db.flush()
        settings = get(db, 'group', 1, 'settings').data
        if job:
            put(db, 'job', 1, str(m.id), dict(source=m.id, mention=True, settings=settings, status='pending', analyzed=False))
        db.commit()
        return m.id, settings


async def enqueue(a, text='帮我安排家庭菜单'):
    mid, settings = seed(text)
    messages = await a.context(1, mid, settings)
    answer = {'role': 'assistant', 'content': '', 'tool_calls': [dict(id='load', type='function', function=dict(name='skill_load', arguments=json.dumps({'name': 'family-meals'})))]}
    ctx = SkillContext(1, 1, str(mid), mid, selected={'skill_load', 'memory_search', 'family_tasks'})
    return await a.background.enqueue(1, str(mid), mid, settings, messages, answer, ctx)


@pytest.mark.asyncio
async def test_slow_skill_does_not_block_chat_and_dispatch_is_unique():
    entered, gate = asyncio.Event(), asyncio.Event()
    events = []
    class Model:
        async def call(self, messages, tools=None, structured=False):
            if structured:
                return {'intent': {'kind':'request','target':'agent','engagement':'addressed','confidence':.99}, 'new_need': None, 'updates': [], 'memories': [], 'reason': '聊天'}
            if messages[-1]['role'] == 'tool':
                entered.set()
                await gate.wait()
                return {'content': '菜单结果'}
            if '安排' in str([m for m in messages if m['role'] == 'user'][-1]):
                return {'tool_calls': [dict(id='load', type='function', function=dict(name='skill_load', arguments='{"name":"family-meals"}'))]}
            return {'content': '聊天回复'}
    async def broadcast(gid, e):
        events.append(e)
    a = Agent(broadcast, Model())
    mid, _ = seed(job=True)
    await a.process(1, str(mid))
    await a.background.schedule()
    await asyncio.wait_for(entered.wait(), 2)
    second, _ = seed('今天天气不错', job=True)
    await asyncio.wait_for(a.process(1, str(second)), 2)
    with DB() as db:
        assert any(m.content == '聊天回复' for m in db.query(Message).all())
        tasks = [r for r in records(db, 'run', 1) if r.data.get('kind') == 'skill']
        assert len(tasks) == 1 and tasks[0].data['status'] == 'running'
    assert not a.locks[1].locked()
    gate.set()
    await asyncio.gather(*list(a.pending))
    assert any(e['type'] == 'task_update' for e in events)
    with DB() as db:
        assert len([m for m in db.query(Message).all() if m.client_id.startswith('result:')]) == 1
    await a.background.schedule()
    await asyncio.gather(*list(a.pending))
    await a.close()


@pytest.mark.asyncio
async def test_bounded_parallel_tasks_and_recovery():
    entered, gate = asyncio.Event(), asyncio.Event()
    class Model:
        count = 0
        async def call(self, *args, **kwargs):
            self.count += 1
            if self.count == 2:
                entered.set()
            await gate.wait()
            return {'content': '完成'}
    model = Model()
    a = Agent(no_broadcast, model)
    keys = [await enqueue(a, f'菜单任务{i}') for i in range(3)]
    await a.background.schedule()
    await asyncio.wait_for(entered.wait(), 2)
    assert len(a.background.active) == 2
    with DB() as db:
        assert get(db, 'run', 1, keys[2]).data['status'] == 'queued'
    # Running read-only tasks are recovered by a fresh supervisor.
    await a.close()
    gate.set()
    b = Agent(no_broadcast, model)
    await b.background.schedule()
    await asyncio.gather(*list(b.pending))
    await b.background.schedule()
    await asyncio.gather(*list(b.pending))
    with DB() as db:
        assert all(get(db, 'run', 1, k).data['status'] == 'succeeded' for k in keys)
        assert len([m for m in db.query(Message).all() if m.client_id.startswith('result:')]) == 3
    await b.close()


@pytest.mark.asyncio
async def test_changed_and_new_safety_memory_regenerates_without_chat_injection():
    entered, gate = asyncio.Event(), asyncio.Event()
    class Model:
        seen = []
        async def call(self, messages, **kwargs):
            self.seen.append(copy.deepcopy(messages))
            if len(self.seen) == 1:
                entered.set()
                await gate.wait()
                return {'content': '花生菜单旧结果'}
            assert '花生过敏' in messages[0]['content']
            assert '后续无关聊天' not in str(messages)
            return {'content': '无花生菜单新结果'}
    model = Model()
    a = Agent(no_broadcast, model)
    key = await enqueue(a)
    await a.background.schedule()
    await asyncio.wait_for(entered.wait(), 2)
    with DB() as db:
        save_memory(db, 1, '孩子花生过敏', manual=True)
        db.commit()
    seed('后续无关聊天')
    gate.set()
    await asyncio.gather(*list(a.pending))
    with DB() as db:
        d = get(db, 'run', 1, key).data
        assert d['result'] == '无花生菜单新结果'
        assert d['memory_refs']
        assert len(records(db, 'memory', 1)) == 1
    assert len(model.seen) == 2
    await a.close()


def test_memory_versions_deletion_and_stale_session_rejected():
    with DB() as db:
        r = save_memory(db, 1, '菜单清淡', manual=True)
        key = r.key
        db.commit()
    with DB() as first, DB() as stale:
        a = get(first, 'memory', 1, key)
        b = get(stale, 'memory', 1, key)
        a.set({**a.data, 'content': '菜单少盐'})
        first.commit()
        with pytest.raises(ValueError, match='其他任务'):
            b.set({**b.data, 'content': '旧值覆盖'})
    with DB() as db:
        r = get(db, 'memory', 1, key)
        assert r.data['version'] == 2
        delete_memory(db, r)
        db.commit()
        assert r.data['version'] == 3


@pytest.mark.asyncio
async def test_failures_and_result_delivery_are_independent():
    class Model:
        async def call(self, *args, **kwargs):
            raise RuntimeError('供应商故障')
    a = Agent(no_broadcast, Model())
    key = await enqueue(a)
    await a.background.schedule()
    await asyncio.gather(*list(a.pending))
    state = snapshot(a, 1)
    assert state['foreground']['status'] == 'idle'
    assert state['background_tasks'][0]['status'] == 'failed'
    assert state['background_tasks'][0]['reply_status'] == 'sent'
    with DB() as db:
        before = db.query(Message).count()
    await a.background.deliver(1, key)
    with DB() as db:
        assert db.query(Message).count() == before
    await a.close()


@pytest.mark.asyncio
async def test_sync_tool_is_offloaded(monkeypatch):
    import threading
    main_thread = threading.get_ident()
    def handler(ctx, args):
        assert threading.get_ident() != main_thread
        return {'ok': True}
    monkeypatch.setitem(REGISTRY, 'sync_test', Skill('sync_test', 'test', schema({}), handler))
    result = await execute('sync_test', {}, SkillContext(1, 1, 'test', 0))
    assert result == {'ok': True}

@pytest.mark.asyncio
async def test_deleted_expired_memory_and_conflicts():
    a = Agent(no_broadcast)
    key = await enqueue(a, '菜单清淡')
    with DB() as db:
        r = save_memory(db, 1, '菜单清淡', manual=True)
        memory_key = r.key
        db.commit()
        d = get(db, 'run', 1, key).data
    refs, _, _ = a.background.memories(1, d)
    assert memory_key in refs
    with DB() as db:
        delete_memory(db, get(db, 'memory', 1, memory_key))
        db.commit()
    next_refs, text, _ = a.background.memories(1, {**d, 'memory_refs': refs})
    assert next_refs[memory_key] is None
    assert '菜单清淡' not in text
    with DB() as db:
        r = save_memory(db, 1, '菜单少油', manual=True, lifetime='short', now=100, expires_at=200)
        db.commit()
        expired_key = r.key
    a.now = lambda: 201
    refs, _, _ = a.background.memories(1, {**d, 'memory_refs': {expired_key: 1}})
    assert refs[expired_key] is None
    with DB() as db:
        r = save_memory(db, 1, '孩子花生过敏', manual=True)
        put(db, 'memory_conflict', 1, 'conflict', {'memory_key': r.key, 'status': 'pending'})
        db.commit()
    await a.background.run(1, key, 'skill')
    with DB() as db:
        assert get(db, 'run', 1, key).data['status'] == 'waiting_input'
    await a.close()


@pytest.mark.asyncio
async def test_worker_can_request_clarification_and_cannot_write():
    class Model:
        count = 0
        async def call(self, messages, **kwargs):
            self.count += 1
            if self.count == 1:
                return {'tool_calls': [dict(id='write', type='function', function=dict(name='family_tasks', arguments='{"action":"create","title":"unauthorized"}'))]}
            assert 'error' in json.loads(messages[-1]['content'])
            return {'tool_calls': [dict(id='input', type='function', function=dict(name='task_needs_input', arguments='{"reason":"请核对过敏信息"}'))]}
    a = Agent(no_broadcast, Model())
    key = await enqueue(a)
    await a.background.run(1, key, 'skill')
    with DB() as db:
        assert get(db, 'run', 1, key).data['status'] == 'waiting_input'
        assert not records(db, 'task', 1)
        assert not records(db, 'memory', 1)
    await a.close()


@pytest.mark.asyncio
async def test_global_limit_and_group_isolation():
    entered, release = asyncio.Event(), asyncio.Event()
    a = Agent(no_broadcast)
    keys = [await enqueue(a, f'菜单{i}') for i in range(3)]
    with DB() as db:
        original = get(db, 'run', 1, keys[0]).data
        for gid in (2, 3):
            for i in range(2):
                put(db, 'run', gid, f'{gid}-{i}', copy.deepcopy(original))
        db.commit()
    calls = []
    async def run(gid, key, kind):
        calls.append((gid, key))
        if len(calls) == 4:
            entered.set()
        await release.wait()
        a.background.active.pop((gid, key), None)
    a.background.run = run
    await a.background.schedule()
    await asyncio.wait_for(entered.wait(), 2)
    assert len(a.background.active) == 4
    assert sum(gid == 1 for gid, key in calls) == 2
    assert sum(gid == 2 for gid, key in calls) == 2
    release.set()
    await asyncio.gather(*list(a.pending))
    await a.close()


@pytest.mark.asyncio
async def test_interrupted_write_requires_review_and_confirmed_receipt_reused():
    from backend.orchestration import create_run
    import hashlib
    a = Agent(no_broadcast)
    args = {'action': 'create', 'title': 'buy'}
    with DB() as db:
        r = create_run(db, 1, 'uncertain', 1, 'buy', [{'tool': 'family_tasks', 'arguments': args}], True)
        d = r.data
        d['status'] = 'running'
        d['steps'][0]['status'] = 'running'
        r.set(d)
        db.commit()
    await a.background.run(1, 'uncertain', None)
    with DB() as db:
        assert get(db, 'run', 1, 'uncertain').data['status'] == 'waiting_input'
        assert not records(db, 'task', 1)
    # A persisted success receipt makes replay safe.
    result = await execute('family_tasks', args, SkillContext(1, 1, 'run:uncertain:step:0', 0, True, grants=[{'tool': 'family_tasks', 'arguments': args}]))
    with DB() as db:
        r = get(db, 'run', 1, 'uncertain')
        r.set({**r.data, 'status': 'queued'})
        db.commit()
    await a.background.run(1, 'uncertain', None)
    with DB() as db:
        assert get(db, 'run', 1, 'uncertain').data['status'] == 'succeeded'
        assert len(records(db, 'task', 1)) == 1
    await a.close()


@pytest.mark.asyncio
async def test_timeout_and_failed_delivery_outbox_retry():
    class Model:
        async def call(self, *args, **kwargs):
            await asyncio.Event().wait()
    a = Agent(no_broadcast, Model())
    a.background.timeout = .02
    key = await enqueue(a)
    original = a.send
    async def failing_send(*args):
        raise RuntimeError('offline')
    a.send = failing_send
    await a.background.run(1, key, 'skill')
    with DB() as db:
        d = get(db, 'run', 1, key).data
        assert d['status'] == 'failed' and d['reply_status'] == 'failed'
        assert d.get('checkpoint')
    a.send = original
    await a.background.schedule()
    await asyncio.gather(*list(a.pending))
    with DB() as db:
        assert get(db, 'run', 1, key).data['reply_status'] == 'sent'
    await a.close()


def test_legacy_memory_version_advances_and_api_rejects_stale_edit():
    from fastapi.testclient import TestClient
    from backend.app import app
    with DB() as db:
        r = save_memory(db, 1, '孩子喜欢面条', manual=True)
        key = r.key
        # Simulate an existing pre-version payload without using Record.set.
        d = r.data
        d.pop('version')
        r.payload = json.dumps(d, ensure_ascii=False)
        db.commit()
        r.set({**r.data, 'content': '孩子喜欢米饭'})
        db.commit()
        assert r.data['version'] == 2
    client = TestClient(app)
    response = client.put(f'/api/groups/1/memories/{key}?user=dad', json={'content': '旧编辑', 'version': 1})
    assert response.status_code == 409
    with DB() as db:
        assert get(db, 'memory', 1, key).data['content'] == '孩子喜欢米饭'
