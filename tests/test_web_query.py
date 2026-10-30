import json
import httpx
import pytest
from jsonschema import validate, ValidationError
from backend.web_query import web_query, WEB_SCHEMA
from backend.skills import Tool, Skill, ToolContext, SkillContext, tools

@pytest.mark.asyncio
async def test_search_and_fetch(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    def handler(request):
        assert request.headers['Authorization'] == 'Bearer test-key'
        body = json.loads(request.content)
        if request.url.path.endswith('search'):
            assert body == {'query': '天气', 'count': 5, 'need_content': False}
            return httpx.Response(200, json={'results': [{'title': '天气', 'url': 'https://example.com', 'summary': '晴'}]})
        assert body == {'url': 'https://example.com'}
        return httpx.Response(200, json={'title': '页面', 'content': 'x' * 13000})
    transport = httpx.MockTransport(handler)
    result = await web_query(None, {'action': 'search', 'query': '天气'}, transport=transport)
    assert result['untrusted'] and result['results'][0]['url'] == 'https://example.com'
    result = await web_query(None, {'action': 'fetch', 'url': 'https://example.com'}, transport=transport)
    assert result['truncated'] and len(result['content']) == 12000

@pytest.mark.asyncio
async def test_failures(monkeypatch):
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    assert 'error' in await web_query(None, {'action': 'search', 'query': 'test'})
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'secret')
    for status in (401, 402, 429, 500):
        result = await web_query(None, {'action': 'search', 'query': 'test'}, transport=httpx.MockTransport(lambda r: httpx.Response(status, text='secret')))
        assert str(status) in result['error'] and 'secret' not in result['error']
    assert 'error' in await web_query(None, {'action': 'fetch', 'url': 'file:///etc/passwd'})

@pytest.mark.parametrize('args', [{'action': 'search'}, {'action': 'fetch'}, {'action': 'search', 'query': '   '}, {'action': 'search', 'query': 'x', 'count': 51}, {'action': 'fetch', 'url': 'https://example.com', 'query': 'x'}])
def test_invalid_args(args):
    with pytest.raises(ValidationError):
        validate(args, WEB_SCHEMA)

def test_tool_boundary():
    assert Tool is Skill and ToolContext is SkillContext
    assert [t['function']['name'] for t in tools(False, [], {'web_query'})] == ['web_query']
