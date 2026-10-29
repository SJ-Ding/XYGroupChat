"""Bounded Chat Completions adapter. Never log prompts or reasoning text."""
import json
import os
import re
import httpx
from dotenv import load_dotenv

load_dotenv()


class ModelError(RuntimeError):
    def __init__(self, message, *, kind='response', status=None, request_id=None, attempts=1):
        super().__init__(message + (f'；请求ID：{request_id}' if request_id else ''))
        self.kind, self.status, self.request_id, self.attempts = kind, status, request_id, attempts


def parse_object(content):
    if not isinstance(content, str) or not content.strip():
        raise ValueError('empty')
    content = content.strip().lstrip('\ufeff').strip()
    fenced = re.fullmatch(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.S | re.I)
    if fenced:
        content = fenced[1].strip()
    def invalid_constant(value):
        raise ValueError('non-finite JSON value')
    result = json.loads(content, parse_constant=invalid_constant)
    if not isinstance(result, dict):
        raise ValueError('not an object')
    return result


def request_id(response, payload):
    candidate = response.headers.get('x-request-id') or response.headers.get('request-id')
    if not candidate:
        error = payload.get('error', {}) if isinstance(payload, dict) else {}
        message = error.get('message', '') if isinstance(error, dict) else ''
        match = re.search(r'request_id:\s*([\w-]{8,128})', str(message))
        candidate = match[1] if match else None
    return candidate if candidate and re.fullmatch(r'[\w-]{1,128}', candidate) else None


class Model:
    def __init__(self, transport=None):
        self.transport = transport

    async def call(self, messages, tools=None, structured=False):
        key = os.getenv('DEEPSEEK_API_KEY', '')
        if not key:
            raise ModelError('尚未配置 DEEPSEEK_API_KEY，请填写服务端 .env 后重启', kind='configuration')
        model = os.getenv('DEEPSEEK_MODEL', 'deepseek-flash')
        body = {'model': model, 'messages': messages, 'max_tokens': 4096 if structured else 2200, 'stream': False}
        if model.startswith('deepseek-'):
            thinking = 'disabled' if structured else os.getenv('DEEPSEEK_THINKING', 'disabled')
            if thinking not in ('enabled', 'disabled'):
                raise ModelError('DEEPSEEK_THINKING 仅支持 enabled 或 disabled', kind='configuration')
            body['thinking'] = {'type': thinking}
            if thinking == 'enabled':
                body['max_tokens'] = 8192
        if tools:
            body['tools'] = tools
        if structured:
            body['response_format'] = {'type': 'json_object'}
        usage, usage_complete = {}, True
        async with httpx.AsyncClient(timeout=70, transport=self.transport) as client:
            # Only invalid structured outputs get one bounded retry. Never
            # retry HTTP errors or replay tools as part of format repair.
            for attempt in range(1, 3 if structured else 2):
                try:
                    response = await client.post(os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com').rstrip('/') + '/chat/completions',
                        headers={'Authorization': 'Bearer ' + key}, json=body)
                except httpx.RequestError:
                    raise ModelError('无法连接模型服务，请检查网络或接口地址后重试', kind='transport', attempts=attempt) from None
                try:
                    payload = response.json()
                except ValueError:
                    raise ModelError(f'模型接口返回无效响应（HTTP {response.status_code}）', kind='envelope', status=response.status_code, attempts=attempt) from None
                rid = request_id(response, payload)
                if response.status_code != 200:
                    # Errors may echo private prompts. Expose no raw body.
                    raise ModelError(f'模型服务请求失败（HTTP {response.status_code}）', kind='http',
                        status=response.status_code, request_id=rid, attempts=attempt)
                try:
                    choice = payload['choices'][0]
                    data = choice['message']
                    if not isinstance(data, dict):
                        raise ValueError()
                except (KeyError, IndexError, TypeError, ValueError):
                    raise ModelError('模型接口缺少有效的回复消息', kind='envelope', request_id=rid, attempts=attempt) from None
                reported = payload.get('usage') or {}
                if not isinstance(reported, dict) or not isinstance(reported.get('total_tokens'), (int, float)):
                    usage_complete = False
                if isinstance(reported, dict):
                    for field in ('total_tokens', 'prompt_tokens', 'completion_tokens'):
                        if isinstance(reported.get(field), (int, float)):
                            usage[field] = usage.get(field, 0) + reported[field]
                if not structured:
                    if choice.get('finish_reason') == 'length':
                        raise ModelError('模型回复被截断，请重试回复；已执行动作不会重复执行', kind='truncated', request_id=rid, attempts=attempt)
                    data['_usage'] = usage if usage_complete else {}
                    data['_attempts'] = attempt
                    return data
                finish = choice.get('finish_reason')
                if finish == 'content_filter' or data.get('refusal'):
                    raise ModelError('模型未接受本次结构化分析请求', kind='refusal', request_id=rid, attempts=attempt)
                try:
                    if finish == 'length':
                        raise ValueError('truncated')
                    result = parse_object(data.get('content'))
                except (ValueError, TypeError):
                    if attempt == 1:
                        body = {**body, 'max_tokens': 8192,
                            'messages': [*messages, {'role': 'user', 'content': '请仅输出完整 JSON 对象，不留空，不使用代码块；不要省略请求中的否定条件和权限边界。'}]}
                        continue
                    reason = '输出被截断' if finish == 'length' else '返回为空或格式不正确'
                    raise ModelError(f'模型结构化分析{reason}，已尝试2次；未应用分析结果，可稍后重试',
                        kind='structured', request_id=rid, attempts=attempt) from None
                result['_usage'] = usage if usage_complete else {}
                result['_attempts'] = attempt
                return result
