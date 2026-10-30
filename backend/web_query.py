"""Bounded DeepSeek Search/Fetch adapter; never executes retrieved instructions."""
import os
from urllib.parse import urlsplit
import httpx

WEB_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {
        'action': {'enum': ['search', 'fetch']},
        'query': {'type': 'string', 'minLength': 1, 'maxLength': 128, 'pattern': r'\S'},
        'count': {'type': 'integer', 'minimum': 1, 'maximum': 10},
        'url': {'type': 'string', 'minLength': 1, 'maxLength': 8192},
    },
    'required': ['action'],
    'oneOf': [
        {'properties': {'action': {'const': 'search'}}, 'required': ['query'], 'not': {'required': ['url']}},
        {'properties': {'action': {'const': 'fetch'}}, 'required': ['url'],
         'not': {'anyOf': [{'required': ['query']}, {'required': ['count']}]}},
    ],
}


async def web_query(ctx, args, *, transport=None):
    key = os.getenv('DEEPSEEK_API_KEY', '')
    if not key:
        return {'error': '尚未配置 DEEPSEEK_API_KEY'}
    action = args['action']
    if action == 'search':
        body = {'query': args['query'], 'count': args.get('count', 5), 'need_content': False}
    else:
        url = urlsplit(args['url'])
        if url.scheme not in ('http', 'https') or not url.hostname or url.username is not None or url.password is not None:
            return {'error': '需要不含账号密码的 HTTP(S) 网页地址'}
        body = {'url': args['url']}
    try:
        async with httpx.AsyncClient(timeout=8, transport=transport, follow_redirects=False) as client:
            response = await client.post('https://api.deepseek.com/v1/tools/' + action,
                                         headers={'Authorization': 'Bearer ' + key}, json=body)
            if response.status_code != 200:
                return {'error': f'联网查询失败（HTTP {response.status_code}）'}
            data = response.json()
        if action == 'search':
            results = data['results']
            if not isinstance(results, list):
                raise ValueError('results')
            return {'untrusted': True, 'results': [
                {field: str(item.get(field) or '')[:limit] for field, limit in
                 [('title', 300), ('url', 2048), ('summary', 1000), ('snippet', 300), ('date', 80)]}
                for item in results[:body['count']]]}
        content = data['content']
        if not isinstance(content, str):
            raise ValueError('content')
        return {'untrusted': True, 'url': args['url'], 'title': str(data.get('title', ''))[:300],
                'content': content[:12000], 'truncated': len(content) > 12000}
    except httpx.TimeoutException:
        return {'error': '联网查询超时，请稍后重试'}
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        return {'error': '联网查询失败或响应格式异常'}
