import json
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

class Model:
    async def call(self, messages, tools=None, structured=False):
        key = os.getenv('DEEPSEEK_API_KEY', '')
        if not key:
            raise RuntimeError('尚未配置 DEEPSEEK_API_KEY，请填写服务端 .env 后重启')
        body = {'model': os.getenv('DEEPSEEK_MODEL', 'deepseek-flash'), 'messages': messages, 'max_tokens': 2200, 'stream': False}
        if tools:
            body['tools'] = tools
        if structured:
            body['response_format'] = {'type': 'json_object'}
        async with httpx.AsyncClient(timeout=70) as client:
            try:
                r = await client.post(os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com').rstrip('/') + '/chat/completions', headers={'Authorization': 'Bearer ' + key}, json=body)
            except httpx.RequestError:
                raise RuntimeError('无法连接模型服务，请检查网络或接口地址后重试') from None
            if r.status_code != 200:
                raise RuntimeError('模型服务请求失败（HTTP %s）' % r.status_code)
            data = r.json()['choices'][0]['message']
        if structured:
            return json.loads(data['content'])
        return data
