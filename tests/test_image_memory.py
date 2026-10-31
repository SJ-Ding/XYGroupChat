import asyncio
import json
import uuid

import pytest

from backend.agent import Agent
from backend.db import DB, DATA, Message, get, put, records
from backend.image_memory import capture, recall
from test_system import FakeModel, no_broadcast


def message(content='', attachments=(), gid=1):
    with DB() as db:
        row = Message(group_id=gid, user_id=1, client_id=uuid.uuid4().hex,
                      content=content, attachments=json.dumps(attachments))
        db.add(row)
        db.commit()
        return row.id


def upload(key='picture', gid=1):
    (DATA / 'uploads' / (key + '.png')).write_bytes(b'test-image')
    with DB() as db:
        put(db, 'upload', gid, key, {'file': key + '.png', 'mime': 'image/png', 'owner': 1})
        db.commit()
    return key


@pytest.mark.asyncio
async def test_details_survive_restart_summary_and_history_window():
    mid = message('图里有什么？', [upload()])
    model = FakeModel({'description': '桌上的药盒', 'details': '左下角蓝色标签',
                       'text': '批号 AB123，每盒20片', 'uncertain': '日期被遮挡'})
    agent = Agent(no_broadcast, model)
    with DB() as db:
        settings = get(db, 'group', 1, 'settings').data
    await agent.context(1, mid, settings)
    # No assistant reply contains the batch number; it comes from the image itself.
    for _ in range(85):
        message('普通聊天')
    followup = message('刚才图片里的批号是什么？')
    with DB() as db:
        put(db, 'summary', 1, 'latest', {'to': followup - 1, 'summary': '此前聊过一张图片'})
        db.commit()
    restarted = Agent(no_broadcast, FakeModel())
    context = await restarted.context(1, followup, settings)
    payload = json.dumps(context, ensure_ascii=False)
    assert 'AB123' in payload and '日期被遮挡' in payload
    assert 'data:image' not in payload
    assert not restarted.model.calls
    await agent.context(1, mid, settings)
    assert len(model.calls) == 1


@pytest.mark.asyncio
async def test_four_images_and_concurrent_capture_are_cached():
    keys = [upload(str(i)) for i in range(4)]
    mid = message(attachments=keys)
    agent = Agent(no_broadcast, FakeModel({'description': '可见的物体'}))
    await asyncio.gather(*(capture(agent, 1, mid, {}) for _ in range(2)))
    with DB() as db:
        assert len(records(db, 'image_memory', 1)) == 4
    assert len(agent.model.calls) == 4


@pytest.mark.asyncio
async def test_scope_future_and_deleted_upload_excluded():
    key = upload()
    before = message('先前的问题')
    mid = message(attachments=[key])
    agent = Agent(no_broadcast, FakeModel({'text': '私密文字'}))
    await capture(agent, 1, mid, {})
    with DB() as db:
        assert recall(db, 2, mid + 1, '') == []
        assert recall(db, 1, before, '') == []
        db.delete(get(db, 'upload', 1, key))
        db.commit()
        assert recall(db, 1, mid + 1, '') == []


@pytest.mark.asyncio
@pytest.mark.parametrize('settings,content', [({'memory_auto': False}, ''), ({}, '不要记住这张图片')])
async def test_memory_preferences_respected(settings, content):
    mid = message(content, [upload()])
    agent = Agent(no_broadcast, FakeModel({'description': '桌子'}))
    await capture(agent, 1, mid, settings)
    assert not agent.model.calls


@pytest.mark.asyncio
async def test_failure_does_not_break_reply_and_can_retry():
    class FailingModel(FakeModel):
        async def call(self, *args, **kwargs):
            raise RuntimeError('vision unavailable')

    mid = message('看图', [upload()])
    agent = Agent(no_broadcast, FailingModel())
    with DB() as db:
        settings = get(db, 'group', 1, 'settings').data
    context = await agent.context(1, mid, settings)
    assert 'image_url' in json.dumps(context)
    agent.model = FakeModel({'description': '重试识别成功'})
    await capture(agent, 1, mid, settings)
    with DB() as db:
        assert len(records(db, 'image_memory', 1)) == 1
