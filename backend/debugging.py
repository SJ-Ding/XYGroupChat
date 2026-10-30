"""Durable, group-scoped debug evidence; never store provider reasoning or image bytes."""
import asyncio
import copy
import json
import os
import time
import uuid
from sqlalchemy import desc, func
from .db import DB, Message, User, Record, get, put


def public_messages(messages):
    result = []
    for message in messages:
        row = {k: copy.deepcopy(v) for k, v in message.items()
               if k in ('role', 'content', 'tool_calls', 'tool_call_id', 'name')}
        if isinstance(row.get('content'), list):
            row['content'] = [({'type': 'image_url', 'image_url': '[图片已省略]'}
                               if b.get('type') == 'image_url' else b) for b in row['content']]
        result.append(row)
    return result


async def traced_call(agent, gid, source, phase, messages, run_id=None, **kwargs):
    key = str(uuid.uuid4())
    started = time.monotonic()
    evidence = {'source': source, 'phase': phase, 'run_id': run_id,
                'at': agent.now(), 'status': 'running', 'messages': public_messages(messages),
                'tools': copy.deepcopy(kwargs.get('tools') or []),
                'structured': bool(kwargs.get('structured')),
                'model': os.getenv('DEEPSEEK_MODEL', 'deepseek-flash')}
    with DB() as db:
        put(db, 'trace', gid, key, evidence)
        db.commit()
    try:
        response = await agent.call(gid, messages, **kwargs)
        # Structured analysis is itself the public result; generation has a narrow whitelist.
        evidence['response'] = ({k: copy.deepcopy(v) for k, v in response.items()
                                 if k in ('intent', 'new_need', 'updates', 'memory_updates', 'memories', 'reason')}
                                if kwargs.get('structured') else
                                {k: copy.deepcopy(v) for k, v in response.items()
                                 if k in ('content', 'tool_calls', '_usage', '_attempts')})
        evidence['status'] = 'done'
        return response
    except BaseException as exc:
        evidence.update(status='cancelled' if isinstance(exc, asyncio.CancelledError) else 'failed',
                        error=type(exc).__name__)
        raise
    finally:
        evidence['latency_ms'] = round((time.monotonic() - started) * 1000)
        with DB() as db:
            put(db, 'trace', gid, key, evidence)
            db.commit()


def message_list(gid, before=None, limit=30):
    with DB() as db:
        query = db.query(Message).filter(Message.group_id == gid, Message.user_id != 0)
        if before is not None:
            query = query.filter(Message.id < before)
        rows = query.order_by(desc(Message.id)).limit(limit + 1).all()
        names = {u.id: u.name for u in db.query(User).all()}
        ids = {m.id for m in rows[:limit]}
        decisions = {r.key: r.data for r in db.query(Record).filter(
            Record.kind == 'decision', Record.group_id == gid, Record.key.in_([str(i) for i in ids])).all()}
        return {'items': [{'id': m.id, 'name': names.get(m.user_id, '成员'), 'content': m.content,
                           'created': m.created, 'attachments': len(json.loads(m.attachments)),
                           'decision': decisions.get(str(m.id))} for m in rows[:limit]],
                'next_before': rows[limit - 1].id if len(rows) > limit else None}


def message_detail(gid, mid):
    with DB() as db:
        message = db.query(Message).filter_by(group_id=gid, id=mid).first()
        if not message or message.user_id == 0:
            return None
        def related(kind, field='source'):
            rows = db.query(Record).filter(Record.kind == kind, Record.group_id == gid,
                func.json_extract(Record.payload, '$.' + field) == mid).order_by(Record.id).all()
            return [dict(key=r.key, **r.data) for r in rows]
        jobs = related('job')
        decision = get(db, 'decision', gid, str(mid))
        # Do not return raw settings, grants or unrelated private records.
        return {'source': mid, 'decision': decision.data if decision else None,
                'jobs': [{k: d[k] for k in ('key', 'status', 'error', 'analyzed', 'replied', 'memory_changes', 'action_status', 'reply_status') if k in d} for d in jobs],
                'traces': related('trace'),
                'logs': related('log'),
                'demands': [{k: d[k] for k in ('key', 'text', 'status', 'candidate', 'deadline', 'version', 'error') if k in d} for d in related('demand')],
                'runs': [{k: d[k] for k in ('key', 'title', 'status', 'steps', 'result', 'error', 'reply_status') if k in d} for d in related('run', 'source_id')]}


def message_annotations(gid, ids):
    """Lightweight evidence for loaded chat bubbles, with exact reply provenance."""
    with DB() as db:
        messages = db.query(Message).filter(Message.group_id == gid, Message.id.in_(ids)).all()
        jobs = {r.key: r.data for r in db.query(Record).filter_by(kind='job', group_id=gid).all()}
        demands = {r.key: r.data for r in db.query(Record).filter_by(kind='demand', group_id=gid).all()}
        runs = {r.key: r.data for r in db.query(Record).filter_by(kind='run', group_id=gid).all()}
        sources = {m.id for m in messages if m.user_id != 0}
        linked = {}
        for m in messages:
            if m.user_id != 0:
                continue
            source, run_id = None, None
            if m.client_id.startswith('mention:'):
                run_id = m.client_id
                source = jobs.get(m.client_id[len('mention:'):], {}).get('source')
                source = source or runs.get(run_id, {}).get('source_id')
            elif m.client_id.startswith('demand:'):
                source = demands.get(m.client_id[len('demand:'):], {}).get('source')
            elif m.client_id.startswith('result:'):
                run_id = next((key for key in runs if m.client_id.startswith('result:' + key + ':')), None)
                source = runs.get(run_id, {}).get('source_id')
            if source:
                linked[m.id] = (source, run_id)
                sources.add(source)
        decisions = {r.key: r.data for r in db.query(Record).filter(Record.kind == 'decision',
            Record.group_id == gid, Record.key.in_([str(i) for i in sources])).all()}
        # Poll only small metadata columns; full context is fetched on demand.
        traces = db.query(Record.key,
            func.json_extract(Record.payload, '$.source'),
            func.json_extract(Record.payload, '$.run_id'),
            func.json_extract(Record.payload, '$.phase'),
            func.json_extract(Record.payload, '$.response.intent'),
            func.json_extract(Record.payload, '$.response.content')).filter(
                Record.kind == 'trace', Record.group_id == gid,
                func.json_extract(Record.payload, '$.source').in_(sources)).order_by(Record.id).all()
        analyses = {r[1]: json.loads(r[4]) if r[4] else None for r in traces if r[3] == 'analysis'}
        result = {}
        for m in messages:
            if m.user_id:
                job = next((d for d in jobs.values() if d.get('source') == m.id), {})
                result[str(m.id)] = {'decision': decisions.get(str(m.id)), 'intent': analyses.get(m.id), 'status': job.get('status')}
            else:
                source, run_id = linked.get(m.id, (None, None))
                matching = [r[0] for r in traces if r[1] == source and
                    ((run_id and r[2] == run_id) or
                     (not run_id and r[3] == 'candidate' and r[5] == m.content))]
                result[str(m.id)] = {'source': source, 'trace_keys': matching}
        return result
