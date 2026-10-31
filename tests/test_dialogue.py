import json
import uuid
import pytest
from backend.agent import Agent
from backend.contracts import ConversationEvent, Intent
from backend.db import DB, Message, get, put
from backend.dialogue import pending, question, remember
from backend.intent import recognize, parse_intent
from backend.participation import decide


def message(text, user=1):
    with DB() as db:
        row = Message(group_id=1, user_id=user, client_id=uuid.uuid4().hex, content=text, attachments='[]', created=100)
        db.add(row)
        db.commit()
        return row.id


@pytest.mark.parametrize('text,kind,count', [
    ('选第一家医院还是第二家？', 'choice', 2),
    ('需要我查询明天下午的号源吗？', 'confirmation', 0),
    ('请告诉我时间', 'information', 0),
    ('请选择：\n1. 第一家医院\n2. 第二家医院', 'choice', 2),
])
def test_extract_delivered_questions(text, kind, count):
    value = question(text)
    assert value['type'] == kind
    assert len(value['options']) == count


def test_question_lifecycle_is_bound_to_user_and_source():
    source = message('帮我查号')
    with DB() as db:
        remember(db, 1, source, source + 1, '选第一家还是第二家？', 100)
        assert pending(db, 1, 1, 700)['source_id'] == source
        assert pending(db, 1, 2, 101) is None
        assert pending(db, 2, 1, 101) is None
        assert pending(db, 1, 1, 701) is None
        assert pending(db, 1, 1, 101, source) is None
        remember(db, 1, source, source + 2, '需要我查询吗？', 110)
        assert pending(db, 1, 1, 111)['type'] == 'confirmation'
        remember(db, 1, source, source + 3, '查询完成。', 120)
        assert pending(db, 1, 1, 121) is None


def test_choice_resolution_and_multiple_questions_do_not_authorize():
    from backend.dialogue import answer_text
    value = question('请选择：\n1. 医院甲\n2. 医院乙')
    assert answer_text(value,'第一个') == '医院甲'
    assert answer_text(value,'第三个') is None
    assert answer_text(value,'好的') is None
    assert answer_text(value,'随便你选') is None
    assert question('需要我查号吗？还是需要预约？')['type'] != 'confirmation'
    assert len(question('给妈妈还是爸爸挂号呀？说一声我去找号。')['options']) == 2


@pytest.mark.asyncio
async def test_medical_followup_preserves_query_without_upgrading_to_booking(monkeypatch):
    from backend import care, care_seed, democlock
    care_seed.reset()
    source = message('明天下午骨科还有号吗', user=2)
    with DB() as db:
        remember(db,1,source,source+1,'请告诉我上午还是下午？',100)
        db.commit()
        value = pending(db,1,2,101)
    async def model(*args, **kwargs):
        return {'intent':{'engagement':'continuation','confidence':.99}}
    # Free-form answers to original choices still retain the query's scope.
    data = await recognize(model,waiting=[],memories=[],names={},messages=[{'sender':2,'text':'明天下午','created':101}],now=101,pending_question=value)
    assert data['intent']['scene'] == 'family-appointment'
    assert data['intent']['operation'] == 'query'
    democlock.reset()


@pytest.mark.asyncio
@pytest.mark.parametrize('text,owner,age,kind,expected', [
    ('好的', 1, 1, 'confirmation', 'reply'),
    ('第一个', 1, 1, 'choice', 'reply'),
    ('明天下午', 1, 1, 'information', 'reply'),
    ('好的', 1, 1, 'choice', 'reply'),
    ('第一个', 2, 1, 'choice', 'silent'),
    ('好的', 1, 601, 'confirmation', 'silent'),
    ('收到', 1, 1, 'confirmation', 'silent'),
    ('谢谢', 1, 1, 'confirmation', 'silent'),
])
async def test_short_answers_need_owned_live_question(text, owner, age, kind, expected):
    async def model(messages, **kwargs):
        return {'intent': {'kind':'request', 'target':'agent', 'engagement':'implicit_request', 'confidence':.99},
                'confirmed_command':'添加待办：买牛奶'}
    messages = [{'sender':1,'text':text,'created':100+age}]
    data = await recognize(model, waiting=[], memories=[], names={}, messages=messages, now=100+age,
                           pending_question={'user_id':owner,'created':100,'type':kind})
    assert decide(ConversationEvent(1,1,3,text,100+age), parse_intent(data), {}).action == expected
    assert data['confirmed_command'] is None
    if kind == 'choice':
        assert data['intent']['operation'] is None


@pytest.mark.parametrize('engagement', [None, 'bogus', [], 'mention_only', 'social', 'uncertain'])
def test_mentions_do_not_override_non_requests(engagement):
    intent = parse_intent({'intent': {'engagement':engagement,'kind':'request','target':'agent','confidence':.99}})
    assert decide(ConversationEvent(1,1,3,'小艺刚才说得不错',100,True), intent, {}).action == 'silent'


@pytest.mark.asyncio
async def test_full_turn_uses_original_options_and_closes_completed_question():
    class Model:
        async def call(self, messages, structured=False, **kwargs):
            if structured:
                if 'facts' in messages[0]['content']:
                    return {'facts':[]}
                payload = json.loads(messages[-1]['content'])
                assert payload['pending_question']['options'][0]['text'] == '第一家医院'
                return {'intent': {'engagement':'continuation','confidence':.99}, 'memories':[]}
            assert '第一家医院' in str(messages)
            return {'content':'你选的是第一家医院。'}
    async def broadcast(*args):
        pass
    source = message('帮我选医院')
    a = Agent(broadcast, Model(), now=lambda:101)
    await a.send(1, '第一家医院还是第二家医院？', 'question', source_id=source)
    await a.close()

    reply = message('第一个')
    with DB() as db:
        put(db,'job',1,str(reply), {'source':reply,'mention':False,'settings':get(db,'group',1,'settings').data,'status':'pending','analyzed':False})
        db.commit()
    # Fresh agent exercises persisted state rather than in-memory conversation.
    b = Agent(broadcast, Model(), now=lambda:102)
    await b.process(1,str(reply))
    with DB() as db:
        assert get(db,'job',1,str(reply)).data['decision']['action'] == 'reply'
        assert db.query(Message).filter_by(client_id='mention:'+str(reply)).one().content == '你选的是第一家医院。'
        assert pending(db,1,1,102) is None
    await b.close()


@pytest.mark.asyncio
async def test_topic_change_closes_question():
    class Model:
        async def call(self, *args, **kwargs):
            return {'intent': {'kind':'discussion','target':'group','engagement':'social','confidence':.99}}
    async def broadcast(*args): pass
    source = message('整理清单')
    a = Agent(broadcast, Model(), now=lambda:100)
    await a.send(1,'需要我整理吗？','old-question',source_id=source)
    new = message('换个话题，今天晚霞好看')
    with DB() as db:
        row = db.get(Message,new)
    await a.analyze(1,row)
    with DB() as db:
        assert pending(db,1,1,100) is None
    await a.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('text', ['妈妈，帮我挂明天骨科的号', '妈妈帮我挂明天骨科的号', '爸爸，查一下明天有没有号', '我胃有点不舒服'])
async def test_medical_content_does_not_bypass_participation(text):
    from backend import care, care_seed, democlock
    care_seed.reset()
    source = message(text, user=2)
    class NeverCalled:
        async def call(self, *args, **kwargs):
            raise AssertionError('医疗入口不应调用模型或工具')
    async def broadcast(*args): pass
    a = Agent(broadcast, NeverCalled(), now=democlock.now)
    with DB() as db:
        source = db.get(Message, source)
    assert not await care.on_message(a,1,source)
    assert not care.cards_of('hospital_apps')
    assert not care.cards_of('care_plan')
    await a.close()
    democlock.reset()
