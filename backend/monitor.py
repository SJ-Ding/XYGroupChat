"""Read-only snapshots. Never expose raw job settings or credentials."""
import os
from collections import Counter
from .db import DB, Message, get, records
from .skills import REGISTRY
from .governance import metrics

def snapshot(agent, gid):
    now = agent.now()
    executions = [dict(v) for v in list(agent.executions.values()) if v['group_id'] == gid]
    with DB() as db:
        settings = get(db, 'group', gid, 'settings').data
        jobs = records(db, 'job', gid)
        demands = records(db, 'demand', gid)
        running_keys = {x['key'] for x in executions if x['phase'] != 'candidate'}
        counts = Counter(r.data.get('status') for r in jobs)
        sources = {r.data.get('source') for r in jobs + demands}
        messages = {m.id: m.content[:180] for m in db.query(Message).filter(Message.group_id == gid, Message.id.in_(sources)).all()}
        def job_row(r):
            d = r.data
            return {'key': r.key, 'source': d.get('source'), 'preview': messages.get(d.get('source'), ''), 'status': 'running' if r.key in running_keys and d.get('status') == 'pending' else d.get('status'), 'mention': bool(d.get('mention')), 'updated': r.updated, 'error': d.get('error'),
                'action_status': d.get('action_status'), 'reply_status': d.get('reply_status')}
        def demand_row(r):
            d = r.data
            return {'key': r.key, 'source': d.get('source'), 'text': d.get('text', ''), 'target': d.get('target'), 'status': d.get('status'), 'deadline': d.get('deadline'), 'candidate': d.get('candidate'), 'version': d.get('version'), 'error': d.get('error'), 'updated': r.updated}
        # Keep all active work visible before recent completed history.
        job_order = sorted(jobs, key=lambda r: (r.data.get('status') in ['pending', 'failed', 'reply_failed'], r.id), reverse=True)
        demand_order = sorted(demands, key=lambda r: (r.data.get('status') in ['waiting', 'failed'], r.id), reverse=True)
        heartbeat_stale = agent.last_tick is not None and now - agent.last_tick > 10
        scheduler = 'stopped' if agent.stopped else 'starting' if agent.last_tick is None else 'degraded' if heartbeat_stale or agent.scheduler_error else 'running'
        failed_demands = sum(r.data.get('status') == 'failed' for r in demands)
        blocked = any(r.data.get('status') == 'failed' and not r.data.get('analyzed') for r in jobs)
        return {
            'server_time': now,
            'name': settings['agent_name'],
            'scheduler': {'state': scheduler, 'started_at': agent.started_at, 'heartbeat': agent.last_tick, 'error': agent.scheduler_error},
            'model': {'name': os.getenv('DEEPSEEK_MODEL', 'deepseek-flash'), 'configured': bool(os.getenv('DEEPSEEK_API_KEY'))},
            'behavior': {'active': settings['active'], 'wait_seconds': settings['wait_seconds'], 'version': settings['version'], 'blocked': blocked},
            'counts': {'running': len(executions), 'pending': sum(r.data.get('status') == 'pending' and r.key not in running_keys for r in jobs), 'done': counts['done'], 'failed': counts['failed'] + counts['reply_failed'] + failed_demands, 'observing': sum(r.data.get('status') == 'waiting' for r in demands)},
            'executions': executions,
            'jobs': [job_row(r) for r in job_order[:30]],
            'demands': [demand_row(r) for r in demand_order[:30]],
            'logs': [r.data for r in records(db, 'log', gid)[-40:]][::-1],
            'skills': [{'name': s.name, 'description': s.description, 'writes': s.writes} for s in REGISTRY.values()],
            'tool_runs': [{'key': r.key, 'name': r.data.get('name'), 'at': r.data.get('at'), 'result': str(r.data.get('result'))[:1200]} for r in records(db, 'tool', gid)[-20:]][::-1],
            'reminders': [dict(key=r.key, **r.data) for r in records(db, 'reminder', gid) if not r.data.get('sent')][-20:],
            'metrics': metrics(db, gid),
            'modules': ['intent', 'participation', 'memory', 'context', 'orchestration', 'skills', 'proactive', 'delivery', 'identity', 'governance'],
        }
