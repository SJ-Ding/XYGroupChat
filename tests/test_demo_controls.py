import pytest
from fastapi.testclient import TestClient
from backend import care, care_seed, democlock
from backend.db import DATA, DB, Message, get, put, records
from backend.demo_control import ControlBody, configure, controls, fault, run_branch
from backend.agent import Agent
from backend.hospital_simulator import AppointmentManager, _Session, automation, _progress
from backend.model import ModelError

async def quiet(*args): pass

@pytest.fixture(autouse=True)
def family():
    care_seed.reset()
    yield
    democlock.reset()


def test_control_mode_scope_and_reset():
    assert not controls()['enabled']
    configure(ControlBody(enabled=True, model=True, amap=True))
    assert fault('model', 1) and not fault('model', 2)
    assert AppointmentManager._pause() == 3000
    assert AppointmentManager._pause(2) >= 1500
    configure(ControlBody(slow=False))
    assert AppointmentManager._pause() == 1500
    configure(ControlBody(enabled=False))
    assert not fault('model') and not fault('amap')
    configure(ControlBody(enabled=True, model=True))
    care_seed.reset()
    assert not controls()['enabled'] and not fault('model')


@pytest.mark.asyncio
async def test_model_fault_is_scoped_and_measured():
    class Model:
        async def call(self, *args, **kw): return {'content': 'ok'}
    agent = Agent(quiet, Model())
    configure(ControlBody(enabled=True, model=True))
    with pytest.raises(ModelError): await agent.call(1, [])
    assert (await agent.call(2, []))['content'] == 'ok'
    with DB() as db:
        assert records(db, 'metric', 1)[-1].data['failed']
    configure(ControlBody(enabled=False))
    assert (await agent.call(1, []))['content'] == 'ok'


@pytest.mark.asyncio
async def test_map_fault_ignores_live_cache_and_vision_cache(monkeypatch):
    from backend import care_aftercare
    configure(ControlBody(enabled=True, amap=True, model=True))
    monkeypatch.setitem(care._DIST_CACHE, 'c-jsph', (1, 1, '高德地图'))
    class Trace:
        async def step(self, *args): pass
    result = await care.distances(['c-jsph'], Trace())
    assert result['c-jsph'][2] == '直线距离估算'
    assert await care.amap('maps_distance', {}) is None
    monkeypatch.setattr(care_aftercare, '_cache_get', lambda d: {'result': {'diagnosis': 'cached'}})
    value, error, digest = await care_aftercare.read_image(None, DATA/'missing.png', 'image/png', Trace())
    assert value is None and '故障注入' in error


@pytest.mark.asyncio
async def test_branches_use_normal_message_queue_and_reject_disabled():
    agent = Agent(quiet)
    with pytest.raises(Exception) as exc: await run_branch(agent, 'query')
    assert exc.value.status_code == 409
    configure(ControlBody(enabled=True))
    await run_branch(agent, 'query')
    with DB() as db:
        message = db.query(Message).order_by(Message.id.desc()).first()
        assert '鼓楼医院' in message.content
        assert get(db, 'job', 1, str(message.id))
    with pytest.raises(Exception) as exc: await run_branch(agent, 'slot_taken')
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_browser_steps_join_execution_chain():
    with DB() as db:
        put(db, 'run', 1, 'demo-progress', {'status': 'running', 'source_id': 12, 'title': '挂号', 'steps': []})
        db.commit()
    await _progress(1, 'demo-progress', '第 2 步 · 选择科室')
    with DB() as db:
        step = next(r.data for r in records(db, 'chain', 1) if r.data.get('kind') == 'browser')
        assert step['source'] == 12 and step['status'] == 'succeeded'
        assert '第 2 步' in step['title']


def test_demo_routes_and_status():
    from backend.app import app
    with TestClient(app) as client:
        client.params = {'user': 'child'}
        headers = {'Origin': 'http://testserver'}
        assert client.post('/api/demo/branches/query', json={}, headers=headers).status_code == 409
        assert client.post('/api/demo/control', json={'enabled': True, 'amap': True}, headers=headers).status_code == 200
        state = client.get('/api/demo/state').json()
        assert state['controls']['amap'] and state['branches'] and state['vision']
        assert state['browser_pause_ms'] == 3000
        assert client.post('/api/demo/branches/unknown', json={}, headers=headers).status_code == 404
        result = client.post('/api/demo/reset', json={}, headers=headers).json()
        assert not result['controls']['enabled']


@pytest.mark.asyncio
async def test_slot_taken_changes_real_simulated_inventory(monkeypatch):
    from backend import hospital_data as H
    tomorrow = democlock.shift_date(democlock.today(), 1)
    slot = next(s for s in H.find_slots('d-guke', tomorrow, 'morning', 'c-jsph') if s['status'] == 'available')
    session = _Session('inject-slot', 1, 1, 'inject-slot', {'slot_id': slot['id']})
    monkeypatch.setattr(automation, 'sessions', {'inject-slot': session})
    configure(ControlBody(enabled=True))
    await run_branch(Agent(quiet), 'slot_taken')
    assert H.slot(slot['id'])['remaining'] == 0
    # Exiting demo mode clears faults, but does not claim to undo inventory changes.
    configure(ControlBody(enabled=False))
    assert not fault('model') and H.slot(slot['id'])['remaining'] == 0
