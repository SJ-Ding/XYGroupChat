"""A browser status receipt must not finish the reservation before the browser."""
import pytest
from backend.db import DB, get, put, records
from backend.orchestration import run_steps


@pytest.mark.asyncio
async def test_browser_polls_stay_running_until_appointment_exists(monkeypatch):
    from backend.hospital_simulator import _Session, automation
    key = 'appt-lifecycle'
    session = _Session(key, 1, 1, key, {})
    monkeypatch.setitem(automation.sessions, key, session)
    with DB() as db:
        put(db, 'run', 1, key, {'status': 'running', 'user_id': 1, 'source_id': 0, 'title': '挂骨科号', 'grants': [],
            'steps': [{'id': '0', 'tool': 'hospital_simulator', 'arguments': {'action': 'status', 'task_id': key}, 'status': 'running'}]})
        db.commit()
    for status in ('starting', 'submitting'):
        session.status = status
        await run_steps(1, key)
        with DB() as db:
            d = get(db, 'run', 1, key).data
            assert d['status'] == 'running' and d['steps'][0]['status'] == 'running'
            assert d['steps'][0]['result']['error'] is None
            polls = [r for r in records(db, 'chain', 1) if 'hospital_simulator' in r.data.get('title', '')]
            assert polls and all(r.data['status'] == 'succeeded' for r in polls)
    session.status = 'done'
    session.appointment = {'id': 'AP-LIFECYCLE'}
    await run_steps(1, key)
    with DB() as db:
        assert get(db, 'run', 1, key).data['status'] == 'succeeded'


def test_playwright_driver_startup_exception_is_persisted(monkeypatch):
    from playwright import sync_api
    from backend.hospital_simulator import _Session, AppointmentManager
    class BrokenDriver:
        def __enter__(self): raise RuntimeError('浏览器驱动无法启动')
        def __exit__(self, *args): pass
    monkeypatch.setattr(sync_api, 'sync_playwright', BrokenDriver)
    session = _Session('driver-failed', 1, 1, 'driver-failed', {})
    with DB() as db:
        put(db, 'run', 1, session.run_key, {'status': 'running', 'title': '挂号', 'steps': []})
        db.commit()
    AppointmentManager()._run(session)
    assert session.status == 'failed'
    with DB() as db:
        assert get(db, 'run', 1, session.run_key).data['error'] == '浏览器驱动无法启动'


@pytest.mark.asyncio
async def test_start_message_waits_for_tool_and_failures_are_reported(monkeypatch):
    from backend import care, care_seed, democlock
    from backend.agent import Agent
    from backend.skills import REGISTRY
    from dataclasses import replace
    from test_system import no_broadcast, FakeModel
    care_seed.reset()
    try:
        monkeypatch.setattr(care, '_AGENT', Agent(no_broadcast, FakeModel(), now=democlock.now))
        events = []
        async def provider(ctx, args):
            events.append('tool')
            return {'error': '无法启动浏览器'}
        async def say(text, key, **kw): events.append(text)
        monkeypatch.setitem(REGISTRY, 'hospital_simulator', replace(REGISTRY['hospital_simulator'], execute=provider))
        monkeypatch.setattr(care, 'say', say)
        option = {'campus': '模拟医院', 'campus_id': 'c-main', 'doctor': '张明远', 'doctor_id': 'doc-g1',
            'date': democlock.today(), 'date_label': '今天', 'time': '08:30', 'session': 'morning', 'slot_id': 'test-slot'}
        meta = {'patient': 'mom', 'real_name': '王秀兰', 'department': '骨科', 'patient_id': 'p-001'}
        assert await care.start_booking(care.agent_ref(), care.ids()['child'], option, meta, origin_key='failure') is None
        assert events[0] == 'tool'
        assert any('无法启动浏览器' in e for e in events)
        assert not any('已启动模拟医院' in e for e in events)
    finally:
        democlock.reset()


@pytest.mark.asyncio
async def test_explicit_retry_restarts_failed_browser_without_replaying_existing_booking(monkeypatch):
    from backend import hospital_data as H
    from backend import hospital_simulator as sim
    from backend.skills import SkillContext
    monkeypatch.setattr(sim.automation, 'sessions', {})
    monkeypatch.setattr(sim, '_started_tasks', set())
    monkeypatch.setattr(sim, '_latest_tasks', {})
    args = {'action': 'book', 'instruction': '重试预约骨科上午', 'hospital_id': H.campus('c-main')['hospitalId']}
    key = sim._run_key(1, 1, args['instruction'], args['hospital_id'])
    old = sim._Session(key, 1, 1, key, {})
    old.status = 'failed'
    sim.automation.sessions[key] = old
    sim._started_tasks.add(key)
    with DB() as db:
        put(db, 'run', 1, key, {'status': 'failed', 'title': '旧挂号', 'user_id': 1, 'source_id': 0, 'error': '旧错误'})
        db.commit()
    calls = []
    def start(task_id, gid, uid, run_key, context):
        calls.append(task_id)
        session = sim._Session(task_id, gid, uid, run_key, context)
        sim.automation.sessions[task_id] = session
        return session
    monkeypatch.setattr(sim.automation, 'start', start)
    ctx = SkillContext(1, 1, 'explicit-retry', 0)
    result = await sim.hospital_simulator(ctx, args)
    assert result['status'] == 'starting' and calls == [key]
    with DB() as db:
        assert get(db, 'run', 1, key).data['status'] == 'running'
        assert get(db, 'run', 1, key).data['error'] is None
    # A repeated request while the browser is alive reuses that browser.
    await sim.hospital_simulator(ctx, args)
    assert calls == [key]
    sim.automation.sessions.clear()
    with DB() as db:
        slot_id = next(s['id'] for s in H.generate_slots() if s['campusId'] == 'c-main' and s['status'] == 'available')
        H.create_appointment(db, slot_id, 'p-001', key)
        db.commit()
    reconciled = await sim.hospital_simulator(ctx, args)
    assert reconciled['status'] == 'done' and reconciled['appointment']['id']
    assert calls == [key]
