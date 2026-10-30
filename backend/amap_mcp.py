"""Restricted Amap MCP bridge using Streamable HTTP (2025-03-26)."""
import json
import os
from urllib.parse import urlsplit
import httpx
from jsonschema import validate

# Only reviewed query capabilities may execute; discovery cannot grant writes.
ALLOWED = {'maps_geo', 'maps_regeocode', 'maps_ip_location', 'maps_weather',
           'maps_bicycling', 'maps_direction_walking', 'maps_direction_driving',
           'maps_direction_transit_integrated', 'maps_distance',
           'maps_text_search', 'maps_around_search', 'maps_search_detail'}
SCHEMA = {'type': 'object', 'additionalProperties': False,
          'properties': {'action': {'enum': ['list', 'call']},
                         'name': {'type': 'string', 'enum': sorted(ALLOWED)},
                         'arguments': {'type': 'object'}},
          'required': ['action'], 'oneOf': [
              {'properties': {'action': {'const': 'list'}},
               'not': {'anyOf': [{'required': ['name']}, {'required': ['arguments']}]}},
              {'properties': {'action': {'const': 'call'}}, 'required': ['name', 'arguments']}]}


class MCPError(Exception):
    pass


async def amap_mcp(ctx, args, *, transport=None):
    url = os.getenv('AMAP_MCP_URL', '')
    if not url:
        return {'error': '尚未配置 AMAP_MCP_URL'}
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc != 'mcp.amap.com' or parsed.path != '/mcp':
        return {'error': 'AMAP_MCP_URL 必须为高德官方 HTTPS MCP 地址'}
    headers = {'Accept': 'application/json, text/event-stream'}
    serial = 0
    try:
        async with httpx.AsyncClient(timeout=6, transport=transport, follow_redirects=False) as client:
            async def rpc(method, params=None, notification=False):
                nonlocal serial
                serial += 1
                body = {'jsonrpc': '2.0', 'method': method}
                if params is not None:
                    body['params'] = params
                if not notification:
                    body['id'] = serial
                async with client.stream('POST', url, headers=headers, json=body) as response:
                    if response.status_code not in (200, 202, 204):
                        raise MCPError(f'高德 MCP 请求失败（HTTP {response.status_code}）')
                    if response.headers.get('mcp-session-id'):
                        headers['Mcp-Session-Id'] = response.headers['mcp-session-id']
                    if notification:
                        return {}
                    data, size = [], 0
                    if 'text/event-stream' in response.headers.get('content-type', ''):
                        async for line in response.aiter_lines():
                            size += len(line)
                            if size > 500000:
                                raise MCPError('高德响应过大，请缩小查询范围')
                            if line.startswith('data:'):
                                data.append(line[5:].lstrip())
                            elif not line and data:
                                item = json.loads('\n'.join(data)); data = []
                                if item.get('id') == serial:
                                    break
                        else:
                            raise MCPError('高德 MCP 未返回匹配结果')
                    else:
                        chunks = bytearray()
                        async for chunk in response.aiter_bytes():
                            chunks.extend(chunk)
                            if len(chunks) > 500000:
                                raise MCPError('高德响应过大，请缩小查询范围')
                        item = json.loads(chunks)
                    if item.get('id') != serial or 'error' in item:
                        raise MCPError('高德 MCP 协议错误')
                    return item['result']

            init = await rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
                                          'clientInfo': {'name': 'xiaoyi', 'version': '1.0'}})
            if init.get('protocolVersion') != '2025-03-26':
                raise MCPError('高德 MCP 协议版本不兼容')
            headers['MCP-Protocol-Version'] = init['protocolVersion']
            await rpc('notifications/initialized', notification=True)
            catalog, cursor = {}, None
            for _ in range(10):
                page = await rpc('tools/list', {'cursor': cursor} if cursor else {})
                catalog.update({t['name']: t for t in page['tools'] if t['name'] in ALLOWED})
                cursor = page.get('nextCursor')
                if not cursor:
                    break
            else:
                raise MCPError('高德工具目录分页超过限制')
            if args['action'] == 'list':
                return {'tools': [{'name': t['name'], 'description': t.get('description', ''),
                                   'inputSchema': t['inputSchema']} for t in catalog.values()]}
            if args.get('name') not in catalog:
                raise MCPError('该高德工具未开放或不存在，请先列出工具')
            validate(args['arguments'], catalog[args['name']]['inputSchema'])
            result = await rpc('tools/call', {'name': args['name'], 'arguments': args['arguments']})
            if result.get('isError'):
                return {'error': '高德工具执行失败，请检查地点和参数'}
            # Bound each result before the common 8000-character context envelope.
            text = '\n'.join(c.get('text', '') for c in result.get('content', []) if c.get('type') == 'text')
            return {'untrusted': True, 'source': '高德地图', 'content': text[:5500], 'truncated': len(text) > 5500}
    except MCPError as exc:
        return {'error': str(exc)}
    except Exception:
        # Transport exceptions can contain the credential-bearing URL.
        return {'error': '高德 MCP 调用失败，请检查配置、参数或网络'}
