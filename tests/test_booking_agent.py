from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from backend import care, care_seed, democlock, hospital_data as H
from backend.booking_agent import book
from backend.db import DB, Message


@pytest.mark.asyncio
@pytest.mark.parametrize('valid', [True, False])
async def test_agent_selects_exact_afternoon_slot_or_stops(monkeypatch, valid):
    care_seed.reset()
    try:
        slot = next(s for s in H.generate_slots() if s['status'] == 'available' and s['session'] == 'afternoon')
        with DB() as db:
            m = Message(group_id=care.GID, user_id=0, client_id='query-result',
                        content='明天下午15:30有号', attachments='[]')
            db.add(m)
            db.commit()
            source = m.id
        async def decide(agent, phase, system, payload):
            assert payload['history'][-1]['content'] == '明天下午15:30有号'
            assert payload['request'] == '帮我挂三点半那个'
            assert payload['available_slots'] == [slot]
            return {'patient': 'dad', 'slot_id': slot['id'] if valid else 'invented'}, None
        monkeypatch.setattr(care, 'llm_json', decide)
        monkeypatch.setattr(care, 'query_hospital', AsyncMock(return_value=[slot]))
        monkeypatch.setattr(care, 'distances', AsyncMock(return_value={slot['campusId']: (1, 5, 'test')}))
        start = AsyncMock()
        say = AsyncMock()
        monkeypatch.setattr(care, 'start_booking', start)
        monkeypatch.setattr(care, 'say', say)
        await book(care, None, 1, '帮我挂三点半那个', source, 'dad', None,
                   SimpleNamespace(step=AsyncMock()), None)
        if valid:
            option = start.call_args.args[2]
            assert option['slot_id'] == slot['id']
            assert option['time'] == slot['startTime']
            say.assert_not_called()
        else:
            start.assert_not_called()
            say.assert_awaited_once()
    finally:
        democlock.reset()
