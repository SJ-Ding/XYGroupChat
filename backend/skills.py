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

@dataclass
class SkillContext:
    group_id: int
    user_id: int
    run_id: str
    source_id: int
    allow_writes: bool = False

@dataclass
class Skill:
    name: str
    description: str
    schema: dict
    execute: Callable
    writes: bool = False

REGISTRY = {}

def register(skill):
    if skill.name in REGISTRY:
        raise ValueError('Duplicate skill')
    REGISTRY[skill.name] = skill

def schema(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}

async def memory_search(ctx, args):
    with DB() as db:
        return search(db, ctx.group_id, args['query'])

async def remember(ctx, args):
    with DB() as db:
        key = hashlib.sha256((ctx.run_id + args['content']).encode()).hexdigest()
        r = save_memory(db, ctx.group_id, args['content'], [ctx.source_id], key=key, manual=True)
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
            owner = args.get('owner_id')
            if owner and not db.query(Member).filter_by(group_id=ctx.group_id, user_id=owner).first():
                raise ValueError('负责人不在群内')
            data = {'title': args['title'], 'owner_id': owner, 'due': args.get('due'), 'done': False, 'source_id': ctx.source_id}
        put(db, 'task', ctx.group_id, key, data)
        db.commit()
        return dict(key=key, **data)

async def remind(ctx, args):
    if args['at'] <= time.time():
        raise ValueError('提醒时间必须晚于现在，使用 Unix 秒时间戳')
    key = hashlib.sha256((ctx.run_id + json.dumps(args, sort_keys=True)).encode()).hexdigest()
    with DB() as db:
        put(db, 'reminder', ctx.group_id, key, {'content': args['content'], 'at': args['at'], 'sent': False})
        db.commit()
    return {'key': key, 'scheduled': True}

register(Skill('memory_search', '检索本家庭的记忆，返回来源消息。', schema({'query': {'type': 'string'}}, ['query']), memory_search))
register(Skill('remember', '仅当用户明确要求记住信息时，保存家庭记忆。', schema({'content': {'type': 'string', 'maxLength': 2000}}, ['content']), remember, True))
register(Skill('family_tasks', '列出待办；仅在用户明确要求时创建或完成待办。due 使用 Unix 秒时间戳。', schema({'action': {'enum': ['list', 'create', 'complete']}, 'key': {'type': 'string'}, 'title': {'type': 'string', 'maxLength': 500}, 'owner_id': {'type': ['integer', 'null']}, 'due': {'type': ['number', 'null']}}, ['action']), tasks, True))
register(Skill('group_reminder', '仅在用户明确要求时，创建一次性群内提醒。at 为 Unix 秒时间戳。', schema({'content': {'type': 'string', 'maxLength': 2000}, 'at': {'type': 'number'}}, ['content', 'at']), remind, True))

def tools(allow_writes):
    result = []
    for s in REGISTRY.values():
        if s.writes and not allow_writes and s.name != 'family_tasks':
            continue
        params = json.loads(json.dumps(s.schema))
        if s.name == 'family_tasks' and not allow_writes:
            params['properties']['action'] = {'enum': ['list']}
        result.append({'type': 'function', 'function': {'name': s.name, 'description': s.description, 'parameters': params}})
    return result

async def execute(name, args, ctx):
    if name not in REGISTRY:
        return {'error': '未知技能'}
    s = REGISTRY[name]
    try:
        validate(args, s.schema)
        if s.writes and not ctx.allow_writes and not (name == 'family_tasks' and args.get('action') == 'list'):
            raise ValueError('自主介入不能执行写入技能')
        key = hashlib.sha256((ctx.run_id + name + json.dumps(args, sort_keys=True)).encode()).hexdigest()
        with DB() as db:
            if not db.query(Member).filter_by(group_id=ctx.group_id, user_id=ctx.user_id).first():
                raise ValueError('无群权限')
            old = get(db, 'tool', ctx.group_id, key)
            if old:
                return old.data['result']
        result = await asyncio.wait_for(s.execute(ctx, args), timeout=10)
        with DB() as db:
            put(db, 'tool', ctx.group_id, key, {'name': name, 'result': result, 'at': time.time()})
            db.commit()
        return result
    except Exception as e:
        return {'error': str(e)[:300]}
