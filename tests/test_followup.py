import pytest
from backend.followup import confirmed_command


def conversation(reply='好的', sender=2, age=1):
    return [dict(sender=2,text='帮我安排一下',created=99),
            dict(sender=0,text='需要我帮你执行“添加待办：买牛奶”吗？',created=100),
            dict(sender=sender,text=reply,created=100+age)]


def test_accept_suggestion():
    assert confirmed_command('添加待办：买牛奶', conversation(), '小艺') == '添加待办：买牛奶'


@pytest.mark.parametrize('reply,sender,age', [('不用了',2,1),('谢谢',2,1),('好的',3,1),('好的',2,1801)])
def test_unrelated_or_expired_confirmation(reply,sender,age):
    assert confirmed_command('添加待办：买牛奶', conversation(reply,sender,age), '小艺') is None


def test_cannot_expand_suggestion():
    assert confirmed_command('添加待办：买牛奶和面包', conversation(), '小艺') is None

@pytest.mark.asyncio
async def test_recognition_receives_assistant_and_validates_confirmation():
    import json
    from backend.intent import recognize
    from backend.participation import decide
    from backend.intent import parse_intent
    from backend.contracts import ConversationEvent

    async def model(messages, **kwargs):
        payload = json.loads(messages[-1]['content'])
        assert payload['messages'][-1]['sender'] == 0
        assert payload['latest_message']['text'] == '好的'
        return {'intent': {'kind':'request','target':'agent','engagement':'continuation','confidence':.95},
                'confirmed_command':'添加待办：买牛奶'}

    data = await recognize(model, waiting=[], memories=[], names={}, messages=conversation(), pending_question={'user_id':2,'created':100,'type':'confirmation'})
    assert data['confirmed_command'] == '添加待办：买牛奶'
    assert decide(ConversationEvent(1,2,3,'好的',101), parse_intent(data), {}).action == 'reply'
