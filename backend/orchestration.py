"""Durable ordered task steps; successful side effects are never replayed."""
import time
from .db import DB, get, put
from .skills import SkillContext, execute

STATES = {'waiting_input', 'waiting_authorization', 'queued', 'running', 'succeeded', 'failed', 'cancelled'}


def create_run(db, gid, key, user_id, title, steps, authorized=False, source_id=0):
    run = {'title': title, 'user_id': user_id, 'source_id': source_id,
        'status': 'queued' if authorized else 'waiting_authorization',
        'steps': [{'id': str(i), 'tool': s['tool'], 'arguments': s['arguments'], 'status': 'pending'} for i, s in enumerate(steps)],
        'grants': [{'tool': s['tool'], 'arguments': s['arguments']} for s in steps] if authorized else [],
        'updated': time.time()}
    return put(db, 'run', gid, key, run)


async def run_steps(gid, key):
    with DB() as db:
        r = get(db, 'run', gid, key)
        if not r or r.data['status'] not in ('queued', 'running') or r.data.get('conversation'):
            return
        d = r.data
        d['status'] = 'running'
        r.set(d)
        db.commit()
    for index in range(len(d['steps'])):
        with DB() as db:
            d = get(db, 'run', gid, key).data
            if d['status'] == 'cancelled':
                return
            step = d['steps'][index]
            if step['status'] == 'succeeded':
                continue
            step['status'] = 'running'
            put(db, 'run', gid, key, d)
            db.commit()
        ctx = SkillContext(gid, d['user_id'], f'run:{key}:step:{index}', d['source_id'], True, grants=d['grants'])
        result = await execute(step['tool'], step['arguments'], ctx)
        with DB() as db:
            current = get(db, 'run', gid, key).data
            current['steps'][index].update(status='failed' if isinstance(result, dict) and 'error' in result else 'succeeded', result=result)
            if current['status'] != 'cancelled':
                if isinstance(result, dict) and 'error' in result:
                    current['status'] = 'failed'
                elif index == len(current['steps']) - 1:
                    current['status'] = 'succeeded'
            current['updated'] = time.time()
            put(db, 'run', gid, key, current)
            db.commit()
            if current['status'] in ('failed', 'cancelled'):
                return
