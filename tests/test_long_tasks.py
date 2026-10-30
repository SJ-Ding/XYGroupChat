"""Two real-duration background skill tasks, without external model calls.

Run: .venv/Scripts/python -m pytest tests/test_long_tasks.py -q -s
The real agent, scheduler, tool executor, SQLite and outbox are exercised.
Only the model and the slow read provider are replaced with deterministic doubles.
"""
import asyncio
import json
import time
from dataclasses import replace

import pytest

from backend.agent import Agent
from backend.db import DB, Message, get, put, records
from backend.monitor import snapshot
from backend.skills import REGISTRY


@pytest.mark.asyncio
async def test_two_long_skills_keep_chat_responsive(monkeypatch, tmp_path):
    step_seconds = 6
    scenarios = {
        'LONG_MEALS': {'title': '长任务A：整理一周家庭菜单', 'skill': 'family-meals', 'steps': 4},
        'LONG_OUTING': {'title': '长任务B：整理周末亲子出游方案', 'skill': 'family-outing', 'steps': 5},
    }
    started = {key: asyncio.Event() for key in scenarios}
    completed = {key: asyncio.Event() for key in scenarios}
    timings = {}
    events = []

    def tool(name, args, call_id):
        return {'role': 'assistant', 'content': '', 'tool_calls': [{
            'id': call_id, 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(args, ensure_ascii=False)},
        }]}

    class Model:
        async def call(self, messages, tools=None, structured=False):
            if structured:
                return {'new_need': None, 'updates': [], 'memories': [], 'reason': '测试明确请求'}
            # The latest human source identifies this invocation; older tasks may be history.
            human = [m for m in messages if m['role'] == 'user'][-1]
            source = json.dumps(human, ensure_ascii=False)
            key = next((k for k in scenarios if k in source), None)
            if key is None:
                return {'role': 'assistant', 'content': '可以，两个任务执行期间我们继续聊。'}
            case = scenarios[key]
            if messages[-1]['role'] != 'tool':
                return tool('skill_load', {'name': case['skill']}, 'load-' + key)
            slow_results = [json.loads(m['content']) for m in messages
                            if m['role'] == 'tool' and 'long_task_step' in m['content']]
            if len(slow_results) < case['steps']:
                return tool('memory_search', {'query': f'{key}:{len(slow_results) + 1}'},
                            f'{key}-{len(slow_results) + 1}')
            timings[key]['finished'] = time.monotonic()
            completed[key].set()
            return {'role': 'assistant', 'content': case['title'] + '，已完成全部整理。'}

    async def slow_read(ctx, args):
        key, step = args['query'].split(':')
        if not started[key].is_set():
            timings[key] = {'started': time.monotonic()}
            started[key].set()
        await asyncio.sleep(step_seconds)
        return {'long_task_step': int(step), 'task': key, 'read_only': True}

    async def broadcast(gid, event):
        events.append(event)

    # Replace, rather than mutate, the registry object so pytest restores it completely.
    monkeypatch.setitem(REGISTRY, 'memory_search', replace(REGISTRY['memory_search'], execute=slow_read))
    agent = Agent(broadcast, Model())
    agent.background.group_limit = 2
    agent.background.global_limit = 4
    agent.background.timeout = 90

    def message(content):
        with DB() as db:
            row = Message(group_id=1, user_id=1, client_id=content, content=content)
            db.add(row)
            db.flush()
            put(db, 'job', 1, str(row.id), {
                'source': row.id, 'mention': True, 'status': 'pending', 'analyzed': False,
                'settings': get(db, 'group', 1, 'settings').data,
            })
            db.commit()
            return row.id

    async def chat_while_running(text):
        before = time.monotonic()
        mid = message(text)
        await asyncio.wait_for(agent.process(1, str(mid)), timeout=3)
        with DB() as db:
            reply = db.query(Message).filter_by(client_id='mention:' + str(mid), user_id=0).first()
            assert reply and reply.content == '可以，两个任务执行期间我们继续聊。'
        return round((time.monotonic() - before) * 1000, 2)

    try:
        sources = {}
        for key, case in scenarios.items():
            sources[key] = message(key + ' ' + case['title'])
            await agent.process(1, str(sources[key]))
        await agent.background.schedule()
        await asyncio.wait_for(asyncio.gather(*(e.wait() for e in started.values())), timeout=3)
        state = snapshot(agent, 1)
        assert sum(t['status'] == 'running' for t in state['background_tasks']) == 2
        assert len(agent.background.active) == 2

        first_chat_ms = await chat_while_running('两个任务都在做时，能继续聊天吗？')
        assert not any(e.is_set() for e in completed.values())
        print(f'两个任务已并行运行；第一次聊天耗时 {first_chat_ms} ms', flush=True)

        await asyncio.wait_for(completed['LONG_MEALS'].wait(), timeout=40)
        assert not completed['LONG_OUTING'].is_set()
        second_chat_ms = await chat_while_running('菜单完成了，出游任务继续时也能聊天吗？')
        await asyncio.wait_for(asyncio.gather(*list(agent.pending)), timeout=20)

        with DB() as db:
            tasks = [r.data for r in records(db, 'run', 1) if r.data.get('kind') == 'skill']
            assert len(tasks) == 2
            assert all(d['status'] == 'succeeded' and d['reply_status'] == 'sent' for d in tasks)
            results = db.query(Message).filter(Message.client_id.like('result:%')).all()
            assert len(results) == 2
            assert all(any(case['title'] in r.content for r in results) for case in scenarios.values())
            assert not records(db, 'memory', 1)
        # Replay scheduling cannot resend either result.
        await agent.background.schedule()
        await asyncio.gather(*list(agent.pending))
        with DB() as db:
            assert db.query(Message).filter(Message.client_id.like('result:%')).count() == 2
        assert any(e['type'] == 'task_update' for e in events)
        assert max(t['started'] for t in timings.values()) < min(t['finished'] for t in timings.values())
        report = {
            'task_seconds': {k: round(v['finished'] - v['started'], 2) for k, v in timings.items()},
            'chat_ms': [first_chat_ms, second_chat_ms],
            'parallel': True, 'result_messages': 2, 'duplicate_results': 0,
        }
        (tmp_path / 'long-task-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False), flush=True)
    finally:
        await agent.close()
