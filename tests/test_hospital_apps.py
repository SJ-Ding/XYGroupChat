import pytest
from fastapi.testclient import TestClient
from backend.app import app
from backend import care_seed, democlock, hospital_data as H
from backend.db import DB
from backend.hospital_simulator import hospital_base

@pytest.fixture
def family():
    care_seed.reset()
    yield
    democlock.reset()

def test_independent_app_state_and_mutation_boundaries(family, monkeypatch):
    from backend import care
    async def no_callback(*args): pass
    monkeypatch.setattr(care, 'on_paid', no_callback)
    first, second = H.catalog()['hospitals']
    a = '/api/hospital/apps/' + first['id']
    b = '/api/hospital/apps/' + second['id']
    with TestClient(app) as client:
        one = client.get(a+'/state').json()
        two = client.get(b+'/state').json()
        assert one['slots'] and two['slots']
        assert {s['hospitalId'] for s in one['slots']} == {first['id']}
        assert {s['hospitalId'] for s in two['slots']} == {second['id']}
        assert {h['id'] for h in one['hospitals']} == {first['id']}
        assert one['hospital']['id'] == first['id']
        assert {c['hospitalId'] for c in two['campuses']} == {second['id']}
        slot = next(s for s in one['slots'] if s['status'] == 'available')
        body={'slotId':slot['id'],'patientId':'p-001','taskId':'same-task'}
        assert client.post(b+'/appointments',json=body).status_code == 409
        created = client.post(a+'/appointments',json=body)
        assert created.status_code == 200
        appt = created.json()
        assert client.get(b+'/appointments/'+appt['id']).status_code == 404
        assert client.post(b+'/appointments/'+appt['id']+'/cancel').status_code == 404
        assert client.post(b+'/appointments/'+appt['id']+'/pay',json={'token':appt['payToken']}).status_code == 404
        assert client.get(b+'/appointments/'+appt['id']+'/emr').status_code == 404
        other_slot = next(s for s in two['slots'] if s['status'] == 'available')
        assert client.post(b+'/appointments',json={**body,'slotId':other_slot['id']}).status_code == 404
        assert all(x['id'] != appt['id'] for x in client.get(b+'/state').json()['appointments'])
        assert client.post(a+'/appointments/'+appt['id']+'/pay',json={'token':appt['payToken']}).json()['pay_status'] == 'paid'
        assert client.get('/api/hospital/apps/unknown/state').status_code == 404

def test_browser_app_base_and_legacy_entry(monkeypatch):
    monkeypatch.setenv('HOSPITAL_BASE','http://127.0.0.1:8000/hospital/')
    assert hospital_base() == 'http://127.0.0.1:8000/hospital/'
    assert hospital_base('amap-example') == 'http://127.0.0.1:8000/hospital/apps/amap-example/'


def test_booking_task_identity_includes_selected_application():
    from backend.hospital_simulator import _run_key
    assert _run_key(1,1,'挂骨科','hospital-a') != _run_key(1,1,'挂骨科','hospital-b')

@pytest.mark.asyncio
async def test_booking_requires_a_hospital_choice(family, monkeypatch):
    from backend.hospital_simulator import hospital_simulator, automation
    from backend.skills import SkillContext
    def forbidden(*args):
        raise AssertionError('must not launch before choosing hospital')
    monkeypatch.setattr(automation, 'start', forbidden)
    result = await hospital_simulator(SkillContext(1,3,'choose-first',0), {'action':'book','instruction':'为妈妈预约骨科上午'})
    assert result['status'] == 'awaiting_hospital_selection'
    assert len(result['hospitals']) == 2
