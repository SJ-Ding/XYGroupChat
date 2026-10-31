"""Durable ordered task steps; successful side effects are never replayed."""
import time
from .db import DB, get, put
from .skills import SkillContext, execute, HumanIntervention
from .cards import sync_run, publish_run

STATES = {'waiting_input', 'waiting_authorization', 'queued', 'running', 'succeeded', 'failed', 'cancelled'}


def create_run(db, gid, key, user_id, title, steps, authorized=False, source_id=0):
    run = {'title': title, 'user_id': user_id, 'source_id': source_id,
        'status': 'queued' if authorized else 'waiting_authorization',
        'steps': [{'id': str(i), 'tool': s['tool'], 'arguments': s['arguments'], 'status': 'pending'} for i, s in enumerate(steps)],
        'grants': [{'tool': s['tool'], 'arguments': s['arguments']} for s in steps] if authorized else [],
        'updated': time.time()}
    r = put(db, 'run', gid, key, run)
    sync_run(db, gid, key)
    return r


async def run_steps(gid, key):
    with DB() as db:
        r = get(db, 'run', gid, key)
        if not r or r.data['status'] not in ('queued', 'running') or r.data.get('conversation'):
            return
        d = r.data
        d['status'] = 'running'
        r.set(d)
        db.commit()
    await publish_run(gid, key)
    for index in range(len(d['steps'])):
        with DB() as db:
            d = get(db, 'run', gid, key).data
            if d['status'] not in ('queued', 'running'):
                return
            step = d['steps'][index]
            if step['status'] == 'succeeded':
                continue
            step['status'] = 'running'
            put(db, 'run', gid, key, d)
            db.commit()
        await publish_run(gid, key)
        ctx = SkillContext(gid, d['user_id'], f'run:{key}:step:{index}', d['source_id'], True, grants=d['grants'], task_key=key)
        try:
            result = await execute(step['tool'], step['arguments'], ctx)
        except HumanIntervention:
            with DB() as db:
                paused = get(db, 'run', gid, key)
                value = paused.data
                value['steps'][index]['status'] = 'pending'
                paused.set(value)
                db.commit()
            await publish_run(gid, key)
            return
        with DB() as db:
            current = get(db, 'run', gid, key).data
            # Browser work runs independently. A successful status poll does not
            # mean the reservation has finished, and error=null is not a failure.
            browser_status = step['tool'] == 'hospital_simulator' and step['arguments'].get('action') == 'status'
            if browser_status and current['status'] in ('succeeded', 'failed', 'cancelled'):
                return
            error = result.get('error') if isinstance(result, dict) else None
            if browser_status and not error and result.get('status') in ('failed', 'cancelled'):
                error = '浏览器预约失败' if result['status'] == 'failed' else '浏览器预约已取消'
            pending = browser_status and not error and result.get('status') not in ('done', 'confirmed')
            if browser_status and not pending and not error and not (result.get('appointment') or {}).get('id'):
                error = '模拟医院未返回预约编号'
            current['steps'][index].update(status='failed' if error else 'running' if pending else 'succeeded', result=result)
            if current['status'] != 'cancelled':
                if error:
                    current['status'] = 'failed'
                    current['error'] = str(error)
                elif index == len(current['steps']) - 1:
                    current['status'] = 'running' if pending else 'succeeded'
            current['updated'] = time.time()
            put(db, 'run', gid, key, current)
            db.commit()
        await publish_run(gid, key)
        if pending or current['status'] in ('failed', 'cancelled'):
            return
