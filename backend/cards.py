"""Durable, declarative chat cards. Only trusted code can attach executable actions."""
import hashlib
import time
import math
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, Field, ConfigDict, model_validator
from fastapi import HTTPException
from sqlalchemy import text
from .db import DB, Message, get, put, records


PHASE_LABELS = {'queued': '等待执行', 'executing': '执行工具', 'thinking': '整理回复', 'searching_memory': '查询相关记忆', 'updating_tasks': '处理家庭待办', 'preparing_result': '准备结果卡片', 'searching': '联网搜索', 'loading_skill': '加载技能', 'refreshing_memory': '核对最新信息', 'completed': '已完成', 'waiting_input': '需要补充信息', 'failed': '执行失败'}

def task_title(d):
    if d.get('kind') == 'skill' or d.get('conversation'):
        return '任务进度'
    return d['title']

def visible_run(d):
    return not d.get('conversation') or d.get('show_progress', False)

def hidden_message(db, m):
    if m.user_id != 0:
        return False
    if m.content == '我开始整理这项任务了，你们可以继续聊，完成后我把结果发过来。':
        return True
    if m.client_id.startswith('card:run:'):
        run = get(db, 'run', m.group_id, m.client_id[len('card:run:'):])
        return bool(run and not visible_run(run.data))
    return False

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class CardField(Strict):
    key: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    type: Literal['text', 'number', 'select'] = 'text'
    required: bool = False
    options: list[str] = Field(default_factory=list, max_length=50)
    @model_validator(mode='after')
    def choices(self):
        if self.type == 'select' and not self.options:
            raise ValueError('选择字段需要选项')
        return self

class CardSpec(Strict):
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default='', max_length=4000)
    items: list[dict[str, str]] = Field(default_factory=list, max_length=30)
    amount: str | None = Field(default=None, max_length=100)
    fields: list[CardField] = Field(default_factory=list, max_length=20)
    links: list[dict[str, str]] = Field(default_factory=list, max_length=5)
    # 可信后端（就医守护编排）生成的富卡片：{type, data, actions}；模型工具 send_card 不开放此字段。
    care: dict | None = None
    @model_validator(mode='after')
    def check(self):
        if len({f.key for f in self.fields}) != len(self.fields):
            raise ValueError('字段标识重复')
        for link in self.links:
            url = urlsplit(link.get('url', ''))
            if url.scheme != 'https' or not url.hostname or url.username or url.password or any(c.isspace() for c in link['url']):
                raise ValueError('外链必须是有效 HTTPS 地址')
            if set(link) != {'label', 'url'} or not link['label']:
                raise ValueError('外链需要名称和地址')
        for item in self.items:
            if set(item) != {'label', 'value'}:
                raise ValueError('信息项需要 label 和 value')
        return self

class CardAction(Strict):
    action: Literal['confirm', 'submit', 'cancel', 'retry', 'open_link']
    version: int = Field(ge=1)
    request_id: str = Field(min_length=1, max_length=100)
    values: dict = Field(default_factory=dict)
    link_index: int | None = None

async def notify(gid, card):
    # Deferred import keeps the skill registry independent of the HTTP application.
    from .app import broadcast
    await broadcast(gid, {'type': 'card_update', 'id': card['id'], 'version': card['version']})


def save_card(db, gid, key, spec, *, kind='info', run_key=None, status='active'):
    spec = CardSpec.model_validate(spec).model_dump()
    old = get(db, 'card', gid, key)
    if old:
        return old.data
    m = Message(group_id=gid, user_id=0, client_id='card:' + key, content=spec['title'], attachments='[]')
    db.add(m)
    db.flush()
    card = dict(id=key, message_id=m.id, kind=kind, run_key=run_key, status=status, version=1, **spec)
    put(db, 'card', gid, key, card)
    return card


def sync_run(db, gid, key):
    r = get(db, 'run', gid, key)
    d = r.data
    if not visible_run(d):
        return None
    card = save_card(db, gid, 'run:' + key, {'title': task_title(d)}, kind='progress', run_key=key)
    value = {**card, 'title': task_title(d), 'status': d['status'], 'phase': d.get('phase', d['status']), 'steps': [dict(id=s['id'], title=s.get('title') or {'family_tasks': '家庭待办', 'group_reminder': '设置提醒', 'remember': '保存记忆', 'memory_search': '查询记忆', 'hospital_simulator': '门诊预约'}.get(s['tool'], '办理事项'), status=s['status']) for s in d.get('steps', [])], 'description': d.get('error') or (PHASE_LABELS.get(d.get('phase'), '处理中') if d.get('kind') == 'skill' else PHASE_LABELS.get(d.get('phase'), '正在处理'))}
    if d['status'] == 'waiting_input' and not d.get('intervention'):
        from .skills import REGISTRY
        fields = []
        for i, step in enumerate(d.get('steps', [])):
            skill = REGISTRY.get(step['tool'])
            if not skill: continue
            required = list(skill.schema.get('required', []))
            if step['tool'] == 'family_tasks':
                required += ['title'] if step['arguments'].get('action') == 'create' else ['key'] if step['arguments'].get('action') == 'complete' else []
            for name in dict.fromkeys(required):
                if step['arguments'].get(name) not in (None, ''): continue
                prop = skill.schema.get('properties', {}).get(name, {})
                if prop.get('type') in ('string', 'number', 'integer') or prop.get('enum'):
                    fields.append({'key': f'{i}:{name}', 'label': f'步骤{i+1} · ' + {'title': '事项名称', 'key': '事项标识', 'content': '内容', 'due': '截止时间', 'owner_id': '负责人'}.get(name, prop.get('title', name)), 'type': 'select' if prop.get('enum') else 'number' if prop.get('type') in ('number', 'integer') else 'text', 'required': True, 'options': prop.get('enum', [])})
        value['fields'] = fields
    elif card['kind'] == 'progress':
        value['fields'] = []
    if value != card:
        value['version'] += 1
        put(db, 'card', gid, card['id'], value)
    return value

async def publish_run(gid, key):
    result_card = None
    with DB() as db:
        db.execute(text('BEGIN IMMEDIATE'))
        card = sync_run(db, gid, key)
        run = get(db, 'run', gid, key).data
        # 就医守护任务由 care 模块发支付卡/凭证卡，不再重复发通用“任务已完成”卡
        if run['status'] == 'succeeded' and not run.get('conversation') and run.get('kind') != 'skill' and not run.get('care'):
            items = []
            for step in run.get('steps', []):
                result = step.get('result') or {}
                content = (result.get('content') or result.get('message') or result.get('title')) if isinstance(result, dict) else str(result)
                content = content or step.get('arguments', {}).get('title') or step.get('arguments', {}).get('content') or '已办理'
                items.append({'label': step.get('title') or {'family_tasks': '家庭待办', 'group_reminder': '提醒', 'remember': '记忆', 'hospital_simulator': '门诊预约'}.get(step['tool'], '任务结果'), 'value': str(content)[:2000]})
            result_card = save_card(db, gid, 'result:' + key, {'title': run['title'], 'description': '任务已完成。', 'items': items[:30]})
        db.commit()
    if result_card:
        await notify(gid, result_card)
    if card:
        await notify(gid, card)


def request_intervention(db, gid, key, request_key, spec):
    """Trusted adapter checkpoint: call again with the same key to read its receipt."""
    r = get(db, 'run', gid, key)
    if not r or r.data['status'] in ('succeeded', 'cancelled'):
        raise ValueError('任务不可介入')
    d = r.data
    receipt = d.get('intervention_results', {}).get(request_key)
    if receipt is not None:
        return receipt
    if d.get('intervention') and d['intervention']['key'] != request_key:
        raise ValueError('任务已有待处理请求')
    card = save_card(db, gid, 'review:' + key + ':' + request_key, spec, kind='intervention', run_key=key, status='waiting_input' if spec.get('fields') else 'waiting_authorization')
    d.update(status='waiting_input' if card['fields'] else 'waiting_authorization', intervention={'key': request_key, 'card_id': card['id']})
    r.set(d)
    sync_run(db, gid, key)
    return None

async def update_progress(gid, key, description):
    """Trusted skill progress hook. No invented percentage or new authorization."""
    with DB() as db:
        db.execute(text('BEGIN IMMEDIATE'))
        card = sync_run(db, gid, key)
        card.update(description=str(description)[:4000], version=card['version'] + 1)
        put(db, 'card', gid, card['id'], card)
        db.commit()
    await notify(gid, card)


def allowed_actions(card, run):
    if not run or run['status'] in ('succeeded', 'cancelled') or card['status'] in ('succeeded', 'cancelled', 'resolved'):
        return []
    if card['kind'] == 'intervention':
        if run.get('intervention', {}).get('card_id') != card['id']:
            return []
        return ['submit' if card['fields'] else 'confirm', 'cancel', 'open_link']
    if run.get('kind') == 'skill':
        return ['cancel'] if run['status'] in ('queued', 'running', 'waiting_input') else []
    if run.get('intervention') or run.get('conversation'):
        return []
    return {'waiting_input': ['submit', 'cancel'] if card['fields'] else ['cancel'], 'waiting_authorization': ['confirm', 'cancel'], 'failed': ['retry', 'cancel'], 'queued': ['cancel'], 'running': ['cancel']}.get(run['status'], [])


def public_card(db, gid, card):
    r = get(db, 'run', gid, card.get('run_key')) if card.get('run_key') else None
    status = r.data['status'] if r and r.data['status'] in ('succeeded', 'cancelled') else card['status']
    return {**card, 'status': status, 'actions': allowed_actions(card, r.data if r else None)}


def apply_action(db, gid, card_id, body, user_id):
    """Caller holds BEGIN IMMEDIATE, serializing authorization and duplicate receipts."""
    c = get(db, 'card', gid, card_id)
    if not c:
        raise HTTPException(404, '卡片不存在')
    card = c.data
    receipt_key = hashlib.sha256(f'{card_id}:{user_id}:{body.request_id}'.encode()).hexdigest()
    previous = get(db, 'card_action', gid, receipt_key)
    fingerprint = body.model_dump()
    if previous:
        if previous.data['request'] != fingerprint:
            raise HTTPException(409, '请求标识已使用')
        return public_card(db, gid, card)
    r = get(db, 'run', gid, card.get('run_key')) if card.get('run_key') else None
    d = r.data if r else None
    if body.version != card['version'] or body.action not in allowed_actions(card, d):
        raise HTTPException(409, '卡片已更新，请查看最新状态')
    if body.action == 'open_link':
        if body.link_index is None or not 0 <= body.link_index < len(card['links']):
            raise HTTPException(422, '外链不存在')
    elif body.action == 'cancel':
        d['status'] = 'cancelled'
    elif d.get('intervention'):
        fields = {f['key']: f for f in card['fields']}
        errors = {}
        if set(body.values) - fields.keys():
            raise HTTPException(422, '包含未知字段')
        for key, field in fields.items():
            v = body.values.get(key)
            if v is None or v == '':
                if field['required']: errors[key] = '请填写此项'
            elif field['type'] == 'number' and (type(v) not in (int, float) or not math.isfinite(v)):
                errors[key] = '请输入有效数字'
            elif field['type'] == 'select' and v not in field['options']:
                errors[key] = '请选择有效选项'
            elif field['type'] == 'text' and (not isinstance(v, str) or len(v) > 4000):
                errors[key] = '文本长度不能超过4000字'
        if errors:
            raise HTTPException(422, {'message': '请检查填写内容', 'fields': errors})
        checkpoint = d.pop('intervention')
        d.setdefault('intervention_results', {})[checkpoint['key']] = {'values': body.values, 'user_id': user_id, 'at': time.time()}
        d['status'] = 'queued'
        card['status'] = 'resolved'
        card['submitted_values'] = body.values
        card['updated_by'] = user_id
    else:
        from .harness_api import validate_steps
        if body.action == 'submit':
            allowed = {f['key'] for f in card['fields']}
            if set(body.values) != allowed:
                raise HTTPException(422, '请填写所有必填字段')
            for field_key, value in body.values.items():
                index, name = field_key.split(':', 1)
                d['steps'][int(index)]['arguments'][name] = value
        if validate_steps(d['steps']):
            raise HTTPException(422, '请先在任务管理中补充缺失参数')
        if body.action == 'submit':
            d.update(status='waiting_authorization', grants=[])
        else:
            d.update(status='queued', grants=[{'tool': s['tool'], 'arguments': s['arguments']} for s in d.get('steps', [])])
    if body.action != 'open_link':
        d['updated'] = time.time()
        r.set(d)
        card['version'] += 1
        if d['status'] == 'cancelled': card['status'] = 'cancelled'
        put(db, 'card', gid, card_id, card)
        sync_run(db, gid, r.key)
    put(db, 'card_action', gid, receipt_key, {'request': fingerprint, 'user_id': user_id, 'at': time.time()})
    return public_card(db, gid, get(db, 'card', gid, card_id).data)


def install_routes(app, current, access):
    from fastapi import Depends
    @app.get('/api/groups/{gid}/agent-tasks')
    def task_list(gid: int, user=Depends(current)):
        access(gid, user)
        with DB() as db:
            db.execute(text('BEGIN IMMEDIATE'))
            result = []
            for r in records(db, 'run', gid):
                card = sync_run(db, gid, r.key)
                if card is None:
                    continue
                result.append({'key': r.key, 'title': card['title'], 'status': r.data['status'], 'card_id': card['id'], 'message_id': (get(db, 'card', gid, r.data['intervention']['card_id']).data['message_id'] if r.data.get('intervention') else card['message_id']), 'steps': card['steps']})
            db.commit()
            return result

    @app.get('/api/groups/{gid}/cards')
    def card_list(gid: int, user=Depends(current)):
        access(gid, user)
        with DB() as db:
            return [public_card(db, gid, r.data) for r in records(db, 'card', gid) if not (r.data.get('run_key') and (run := get(db, 'run', gid, r.data['run_key'])) and not visible_run(run.data))]

    @app.post('/api/groups/{gid}/cards/{card_id}/actions')
    async def action(gid: int, card_id: str, body: CardAction, user=Depends(current)):
        access(gid, user)
        with DB() as db:
            db.execute(text('BEGIN IMMEDIATE'))
            card = apply_action(db, gid, card_id, body, user['id'])
            db.commit()
        await notify(gid, card)
        return card
