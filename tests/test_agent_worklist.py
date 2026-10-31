"""The sidebar lists agent work and real schedules, never legacy family todos."""
from fastapi.testclient import TestClient
from backend.app import app, agent
from backend.agent import Agent
from backend.db import DB, Message, put
from backend.monitor import worklist
from test_system import FakeModel, no_broadcast


def test_worklist_system_reminders_order_history_and_isolation():
    with DB() as db:
        # The oldest-created appointment reminder must survive newer reminders.
        put(db, 'reminder', 1, 'visit:appointment', {'content': '妈妈就诊前一小时', 'at': 200, 'user_id': 0})
        for i in range(25):
            put(db, 'reminder', 1, str(i), {'content': '后续提醒', 'at': 300 + i, 'sent': False, 'status': 'active'})
        put(db, 'reminder', 1, 'cancelled', {'content': '已取消', 'at': 100, 'status': 'cancelled'})
        put(db, 'reminder', 1, 'sent', {'content': '已调度', 'at': 100, 'sent': True})
        put(db, 'reminder', -1, 'private', {'content': 'PRIVATE_SENTINEL', 'at': 150})
        put(db, 'reminder', 2, 'other-group', {'content': 'OTHER_GROUP_SENTINEL', 'at': 150})
        put(db, 'task', 1, 'legacy', {'title': 'LEGACY_SENTINEL', 'done': False})
        db.commit()
    result = worklist(Agent(no_broadcast, FakeModel()), 1)
    assert result['tasks'] == []
    assert len(result['reminders']) == 28
    assert result['reminders'][0]['key'] == 'visit:appointment'
    assert result['reminders'][0]['status'] == 'active'
    assert {r['key']: r['status'] for r in result['reminders']}['sent'] == 'completed'
    assert all('SENTINEL' not in str(r) for r in result['reminders'])


def test_worklist_agent_tasks_deduplicate_and_prioritize_pending():
    with DB() as db:
        m = Message(group_id=1, user_id=1, client_id='work', content='帮我查询骨科号')
        db.add(m); db.flush()
        mid = m.id
        put(db, 'job', 1, str(mid), {'source': mid, 'status': 'done', 'settings': {'secret': 'SECRET_SENTINEL'}})
        put(db, 'run', 1, 'skill:booking', {'source_id': mid, 'title': m.content, 'status': 'waiting_input',
            'updated': 100, 'kind': 'skill', 'snapshot': 'SECRET_SENTINEL'})
        put(db, 'run', 1, 'hidden', {'conversation': True, 'show_progress': False, 'status': 'running'})
        put(db, 'job', 1, 'live', {'source': 999, 'status': 'pending'})
        put(db, 'job', 1, 'done', {'source': 998, 'status': 'done'})
        put(db, 'demand', 1, 'observe', {'text': '稍后跟进', 'source': mid, 'status': 'waiting', 'deadline': 200})
        put(db, 'run', 2, 'foreign', {'title': 'OTHER_GROUP_SENTINEL', 'status': 'running'})
        db.commit()
    a = Agent(no_broadcast, FakeModel())
    a.executions[('job', 1, 'live')] = {'group_id': 1, 'key': 'live', 'phase': 'analyzing'}
    result = worklist(a, 1)
    tasks = {t['key']: t for t in result['tasks']}
    assert 'job:' + str(mid) not in tasks
    assert 'run:hidden' not in tasks
    assert tasks['run:skill:booking']['title'] == '帮我查询骨科号'
    assert tasks['run:skill:booking']['source'] == mid
    assert tasks['job:live']['status'] == 'running'
    assert result['tasks'][-1]['key'] == 'job:done'
    assert 'SECRET_SENTINEL' not in str(result)
    assert 'OTHER_GROUP_SENTINEL' not in str(result)


def test_worklist_endpoint_requires_membership_and_is_read_only():
    agent.model = FakeModel()
    with TestClient(app) as client:
        assert client.get('/api/groups/1/agent/worklist').status_code == 400
        assert client.get('/api/groups/2/agent/worklist?user=dad').status_code == 403
        response = client.get('/api/groups/1/agent/worklist?user=dad')
        assert response.status_code == 200
        assert response.json() == {'tasks': [], 'reminders': []}


def test_worklist_preserves_paused_and_all_reminder_history():
    with DB() as db:
        put(db, 'reminder', 1, 'dad-medication', {
            'content': '爸爸吃药', 'at': 200, 'status': 'paused',
            'clock': '08:30', 'category': 'medication', 'source_id': 42})
        for i in range(55):
            put(db, 'reminder', 1, 'old:' + str(i), {
                'content': '历史提醒', 'at': 100, 'sent': True})
        db.commit()
    rows = worklist(Agent(no_broadcast, FakeModel()), 1)['reminders']
    assert len(rows) == 56
    medication = next(r for r in rows if r['key'] == 'dad-medication')
    assert medication['status'] == 'paused'
    assert medication['category'] == 'medication'
    assert medication['source'] == 42


def test_care_schedules_are_visible_without_creating_duplicate_reminders(monkeypatch):
    from backend import democlock
    from backend.db import records
    now = democlock.at('2026-10-31', '09:00')
    monkeypatch.setattr(democlock, 'now', lambda: now)
    with DB() as db:
        base = dict(member='dad', type='medication', title='原医嘱', clock='08:00',
                    start='2026-09-01', status='active')
        put(db, 'care_item', 1, 'dad-med', base)
        put(db, 'care_item', 1, 'expired', {**base, 'end': '2026-10-30'})
        put(db, 'care_item', 1, 'future', {**base, 'start': '2026-11-10'})
        put(db, 'care_item', 1, 'followup', dict(member='mom', type='followup', title='骨科复诊',
            briefing_at=now + 3600, status='active', briefing_sent=False))
        put(db, 'care_item', 1, 'sent-briefing', dict(member='mom', type='followup', title='简报',
            briefing_at=now - 3600, status='active', briefing_sent=True))
        put(db, 'care_item', 2, 'foreign', base)
        db.commit()
    rows = {r['key']: r for r in worklist(Agent(no_broadcast, FakeModel()), 1)['reminders']}
    assert len(rows) == 5
    assert rows['care:dad-med']['at'] == democlock.at('2026-11-01', '08:00')
    assert '爸爸' in rows['care:dad-med']['content']
    assert rows['care:expired']['status'] == 'expired'
    assert rows['care:future']['at'] == democlock.at('2026-11-10', '08:00')
    assert rows['care:followup']['at'] == now + 3600
    assert rows['care:sent-briefing']['status'] == 'completed'
    with DB() as db:
        assert records(db, 'reminder', 1) == []
