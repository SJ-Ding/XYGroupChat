import json
import httpx
import pytest
from backend.amap_mcp import amap_mcp
from backend.skills import tools

@pytest.mark.asyncio
@pytest.mark.parametrize('sse', [False, True])
async def test_protocol_and_validation(monkeypatch, sse):
    monkeypatch.setenv('AMAP_MCP_URL', 'https://mcp.amap.com/mcp?key=test-secret')
    calls = []
    def handler(req):
        body = json.loads(req.content); method = body['method']; calls.append(method)
        if method == 'initialize':
            result = {'protocolVersion': '2025-03-26'}
        else:
            assert req.headers['Mcp-Session-Id'] == 'session'
            assert req.headers['MCP-Protocol-Version'] == '2025-03-26'
            if method == 'notifications/initialized':
                return httpx.Response(202)
            if method == 'tools/list':
                result = {'tools': [{'name': 'maps_geo', 'inputSchema': {'type': 'object', 'properties': {'address': {'type': 'string'}}, 'required': ['address']}}, {'name': 'delete_all', 'inputSchema': {}}]}
            else:
                assert body['params'] == {'name': 'maps_geo', 'arguments': {'address': '北京'}}
                result = {'content': [{'type': 'text', 'text': 'x' * 9000}]}
        payload = {'jsonrpc': '2.0', 'id': body['id'], 'result': result}
        if sse:
            return httpx.Response(200, headers={'content-type': 'text/event-stream', 'mcp-session-id': 'session'}, text='data: '+json.dumps(payload)+'\n\n')
        return httpx.Response(200, headers={'mcp-session-id': 'session'}, json=payload)
    transport = httpx.MockTransport(handler)
    result = await amap_mcp(None, {'action': 'list'}, transport=transport)
    assert [t['name'] for t in result['tools']] == ['maps_geo']
    result = await amap_mcp(None, {'action': 'call', 'name': 'maps_geo', 'arguments': {'address': '北京'}}, transport=transport)
    assert result['truncated'] and len(result['content']) == 5500
    calls.clear()
    result = await amap_mcp(None, {'action': 'call', 'name': 'maps_geo', 'arguments': {}}, transport=transport)
    assert 'error' in result and 'tools/call' not in calls

@pytest.mark.asyncio
async def test_no_credentials_in_errors(monkeypatch):
    monkeypatch.setenv('AMAP_MCP_URL', 'https://mcp.amap.com/mcp?key=test-secret')
    def handler(req):
        raise httpx.ConnectError(str(req.url))
    result = await amap_mcp(None, {'action': 'list'}, transport=httpx.MockTransport(handler))
    assert 'error' in result and 'test-secret' not in str(result)
    assert tools(False, [], {'amap_mcp'})[0]['function']['name'] == 'amap_mcp'
