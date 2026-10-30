"""Trusted server-side skills. Documentation never executes code."""
import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Callable
from jsonschema import validate
from .db import DB, Member, get, put, records
from .memory import search, save_memory
from .authorization import permitted
from .skill_library import load_instructions

@dataclass
class SkillContext:
    group_id: int
    user_id: int
    run_id: str
    source_id: int
    allow_writes: bool = False
    grants: list | None = None  # None is reserved for trusted legacy callers.
    selected: set | None = None
    now: float | None = None

@dataclass
class Skill:
    name: str
    description: str
    schema: dict
    execute: Callable
    writes: bool = False
    instructions: str = ''
    version: str = '1'

REGISTRY = {}

def register(skill):
    if skill.name in REGISTRY:
        raise ValueError('Duplicate skill')
    REGISTRY[skill.name] = skill

def schema(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}

async def memory_search(ctx, args):
    with DB() as db:
        return search(db, ctx.group_id, args['query'], viewer_id=ctx.user_id if ctx.group_id < 0 else None, now=ctx.now)

async def skill_load(ctx, args):
    return load_instructions(args['name'])

register(Skill('skill_load', '按目录名称加载可信家庭场景技能正文；不执行业务动作、不增加权限。', schema({'name': {'type': 'string', 'maxLength': 64}}, ['name']), skill_load))

async def remember(ctx, args):
    with DB() as db:
        key = hashlib.sha256((ctx.run_id + args['content']).encode()).hexdigest()
        old = get(db, 'memory', ctx.group_id, key)
        if old:
            return {'key': old.key, **old.data}
        r = save_memory(db, ctx.group_id, args['content'], [ctx.source_id] if ctx.source_id else [], key=key, manual=True, explicit=True)
        db.commit()
        return {'key': r.key, **r.data}

async def tasks(ctx, args):
    with DB() as db:
        if args['action'] == 'list':
            return [dict(key=r.key, **r.data) for r in records(db, 'task', ctx.group_id)]
        key = args.get('key') or hashlib.sha256((ctx.run_id + json.dumps(args, sort_keys=True)).encode()).hexdigest()
        if args['action'] == 'complete':
            r = get(db, 'task', ctx.group_id, key)
            if not r:
                raise ValueError('待办不存在')
            data = r.data
            data['done'] = True
        else:
            if not args.get('title'):
                raise ValueError('需要标题')
            old = get(db, 'task', ctx.group_id, key)
            if old:
                return dict(key=old.key, **old.data)
            owner = args.get('owner_id')
            if owner and not ((ctx.group_id < 0 and owner == ctx.user_id) or db.query(Member).filter_by(group_id=ctx.group_id, user_id=owner).first()):
                raise ValueError('负责人不在群内')
            data = {'title': args['title'], 'owner_id': owner, 'due': args.get('due'), 'done': False, 'source_id': ctx.source_id}
        put(db, 'task', ctx.group_id, key, data)
        db.commit()
        return dict(key=key, **data)

async def remind(ctx, args):
    key = hashlib.sha256((ctx.run_id + json.dumps(args, sort_keys=True)).encode()).hexdigest()
    with DB() as db:
        old = get(db, 'reminder', ctx.group_id, key)
        if old:
            return {'key': key, 'scheduled': True, 'sent': old.data.get('sent', False)}
        if args['at'] <= (ctx.now if ctx.now is not None else time.time()):
            raise ValueError('提醒时间必须晚于现在，使用 Unix 秒时间戳')
        put(db, 'reminder', ctx.group_id, key, {'content': args['content'], 'at': args['at'], 'sent': False,
            'user_id': ctx.user_id, 'channel': 'personal' if ctx.group_id < 0 else 'group', 'status': 'active', 'version': 1})
        db.commit()
    return {'key': key, 'scheduled': True}

register(Skill('memory_search', '检索本家庭的记忆，返回来源消息。', schema({'query': {'type': 'string'}}, ['query']), memory_search))
register(Skill('remember', '仅当用户明确要求记住信息时，保存家庭记忆。', schema({'content': {'type': 'string', 'maxLength': 2000}}, ['content']), remember, True))
register(Skill('family_tasks', '列出待办；仅在用户明确要求时创建或完成待办。due 使用 Unix 秒时间戳。', schema({'action': {'enum': ['list', 'create', 'complete']}, 'key': {'type': 'string'}, 'title': {'type': 'string', 'maxLength': 500}, 'owner_id': {'type': ['integer', 'null']}, 'due': {'type': ['number', 'null']}}, ['action']), tasks, True))
register(Skill('group_reminder', '仅在用户明确要求时，创建一次性群内提醒。at 为 Unix 秒时间戳。', schema({'content': {'type': 'string', 'maxLength': 2000}, 'at': {'type': 'number'}}, ['content', 'at']), remind, True))

REGISTRY['memory_search'].instructions = '先检索当前空间，自然使用命中的相关事实和近况，留意短期有效期和未确定的打算。找不到就坦诚说，不编造。不要抄录工具结果或逐条汇报确认状态；只有被问到出处时才解释来源。'
REGISTRY['remember'].instructions = '保存明确要求记住的完整事实，保留否定条件。不可修改授权参数或改变可见空间。'
REGISTRY['family_tasks'].instructions = '先区分查看、创建和完成。完成使用已有待办编号；每项写入必须精确匹配授权。结果中有 error 时不得宣称完成。'
REGISTRY['group_reminder'].instructions = '核对明确约定的内容和未来时间。周期、用药和接收对象通过提醒表单设置；不自行推断剂量和疗程。'

def tools(allow_writes, grants=None, selected=None):
    result = []
    for s in REGISTRY.values():
        if selected is not None and s.name not in selected:
            continue
        if grants is not None and s.writes and s.name != 'family_tasks' and not any(g['tool'] == s.name for g in grants):
            continue
        if s.writes and not allow_writes and s.name != 'family_tasks':
            continue
        params = json.loads(json.dumps(s.schema))
        if s.name == 'family_tasks' and not allow_writes:
            params['properties']['action'] = {'enum': ['list']}
        if grants is not None and s.name == 'family_tasks' and not any(g['tool'] == s.name for g in grants):
            params['properties']['action'] = {'enum': ['list']}
        result.append({'type': 'function', 'function': {'name': s.name, 'description': s.description, 'parameters': params}})
    return result

async def execute(name, args, ctx):
    if name not in REGISTRY:
        return {'error': '未知技能'}
    s = REGISTRY[name]
    try:
        validate(args, s.schema)
        json.dumps(args, allow_nan=False)
        if ctx.selected is not None and name not in ctx.selected:
            raise ValueError('此任务未加载该能力')
        readonly = not s.writes or (name == 'family_tasks' and args.get('action') == 'list')
        if not readonly and ctx.grants is not None and not permitted(ctx.grants, name, args):
            raise ValueError('此动作或参数没有获得授权，请使用明确命令或任务表单')
        if not readonly and ctx.grants is not None:
            # Reuse the sealed representation (including numeric types) so a
            # model's 100 vs 100.0 cannot create a second idempotency key.
            args = next(g['arguments'] for g in ctx.grants if g['tool'] == name and g['arguments'] == args)
        if s.writes and not ctx.allow_writes and not (name == 'family_tasks' and args.get('action') == 'list'):
            raise ValueError('自主介入不能执行写入技能')
        key = hashlib.sha256((ctx.run_id + name + json.dumps(args, sort_keys=True)).encode()).hexdigest()
        with DB() as db:
            if not ((ctx.group_id < 0 and ctx.group_id == -ctx.user_id) or db.query(Member).filter_by(group_id=ctx.group_id, user_id=ctx.user_id).first()):
                raise ValueError('无群权限')
            old = get(db, 'tool', ctx.group_id, key)
            if old and not readonly:
                return old.data['result']
        result = await asyncio.wait_for(s.execute(ctx, args), timeout=10)
        with DB() as db:
            put(db, 'tool', ctx.group_id, key, {'name': name, 'result': result, 'at': time.time()})
            db.commit()
        return result
    except Exception as e:
        return {'error': str(e)[:300]}
