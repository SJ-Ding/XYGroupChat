"""Read-only snapshots. Never expose raw job settings or credentials."""
import os
from collections import Counter
from .db import DB, Message, get, records
from .skills import REGISTRY
from .background import public_task
from .governance import metrics
from .memory_lifecycle import status as memory_status


def care_reminders(db, gid):
    """Project care schedules for display; the care scheduler owns execution."""
    from . import democlock
    now = democlock.now()
    today = democlock.today(now)
    names = {'dad': '爸爸', 'mom': '妈妈', 'child': '小林'}
    rows = []
    for r in records(db, 'care_item', gid):
        d = r.data
        kind = d.get('type')
        if kind not in ('medication', 'rehab', 'followup'):
            continue
        status = d.get('status', 'active')
        clock = d.get('clock', '08:30')
        if kind == 'followup':
            at = d.get('briefing_at')
            if status == 'active' and d.get('briefing_sent'):
                status = 'completed'
            repeat = None
        else:
            date = max(today, d.get('start') or today)
            at = democlock.at(date, clock)
            if at <= now:
                date = democlock.shift_date(date, 1)
                at = democlock.at(date, clock)
            if d.get('end') and date > d['end']:
                at = democlock.at(d['end'], clock)
                if status == 'active':
                    status = 'expired'
            repeat = clock
        member = names.get(d.get('member'), d.get('member', ''))
        action = {'medication': '用药提醒', 'rehab': '康复提醒', 'followup': '复诊前简报与预约'}[kind]
        rows.append(dict(key='care:' + r.key, content=f"{member} · {action}：{d.get('title', '')}",
            at=at, status=status, clock=repeat, timezone='Asia/Shanghai', channel='group',
            category=kind, source=d.get('source_id'), updated=r.updated,
            start=d.get('start'), end=d.get('end'), detail=d.get('detail'), origin='care'))
    return rows


def worklist(agent, gid):
    """User-facing agent work, without legacy family todos or execution secrets."""
    from .cards import visible_run
    with DB() as db:
        tasks = []
        runs = [r for r in records(db, 'run', gid) if visible_run(r.data)]
        covered = {r.data.get('source_id') for r in runs}
        sources = {r.data.get('source_id') for r in runs}
        sources.update(r.data.get('source') for r in records(db, 'job', gid))
        messages = dict(db.query(Message.id, Message.content).filter(Message.group_id == gid, Message.id.in_(sources)).all())
        running = {x['key'] for x in agent.executions.values() if x['group_id'] == gid}
        for r in runs:
            d = r.data
            source = d.get('source_id')
            card = get(db, 'card', gid, 'run:' + r.key)
            tasks.append(dict(key='run:' + r.key, title=d.get('title') or messages.get(source) or 'Agent 任务',
                status=d.get('status', 'queued'), source=source or (card.data.get('message_id') if card else None),
                updated=d.get('updated') or r.updated, error=d.get('error')))
        for r in records(db, 'job', gid):
            d = r.data
            if d.get('source') in covered:
                continue
            status = d.get('status', 'pending')
            if status == 'pending' and r.key in running:
                status = 'running'
            tasks.append(dict(key='job:' + r.key, title=messages.get(d.get('source')) or '分析图片消息',
                status=status, source=d.get('source'), updated=r.updated, error=d.get('error')))
        for r in records(db, 'demand', gid):
            d = r.data
            if d.get('status') not in ('waiting', 'failed'):
                continue
            tasks.append(dict(key='demand:' + r.key, title=d.get('text') or '等待跟进',
                status=d.get('status'), source=d.get('source'), updated=r.updated,
                deadline=d.get('deadline'), error=d.get('error')))
        active = {'pending', 'queued', 'running', 'waiting', 'waiting_input', 'waiting_authorization', 'failed', 'reply_failed'}
        tasks.sort(key=lambda d: d['updated'] or 0, reverse=True)
        pending = [d for d in tasks if d['status'] in active]
        history = [d for d in tasks if d['status'] not in active][:50]
        reminders = []
        for r in records(db, 'reminder', gid):
            d = r.data
            reminders.append(dict(key=r.key, content=d.get('content', ''), at=d.get('at'),
                status=d.get('status', 'active') if d.get('status', 'active') != 'active' else 'completed' if d.get('sent') else 'active',
                clock=d.get('clock'), weekdays=d.get('weekdays'), timezone=d.get('timezone', 'Asia/Shanghai'),
                channel=d.get('channel', 'group'), category=d.get('category', 'daily'),
                source=d.get('source_id'), updated=r.updated))
        reminders.extend(care_reminders(db, gid))
        scheduled = sorted((d for d in reminders if d['status'] == 'active'), key=lambda d: d['at'] or 0)
        reminder_history = sorted((d for d in reminders if d['status'] != 'active'), key=lambda d: d['updated'], reverse=True)
        return {'tasks': pending + history, 'reminders': scheduled + reminder_history}

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
            'foreground': {'status': 'generating' if any(e['phase'] in ('replying', 'analyzing') for e in executions) else 'idle'},
            'background_tasks': [public_task(r.key, r.data) for r in sorted((r for r in records(db, 'run', gid) if r.data.get('kind') == 'skill'), key=lambda r: (r.data['status'] in ('queued', 'running', 'waiting_input'), r.id), reverse=True)][:30],
            'executions': executions,
            'jobs': [job_row(r) for r in job_order[:30]],
            'demands': [demand_row(r) for r in demand_order[:30]],
            'logs': [r.data for r in records(db, 'log', gid)[-40:]][::-1],
            'skills': [{'name': s.name, 'description': s.description, 'writes': s.writes} for s in REGISTRY.values()],
            'tool_runs': [{'key': r.key, 'name': r.data.get('name'), 'at': r.data.get('at'), 'result': str(r.data.get('result'))[:1200]} for r in records(db, 'tool', gid)[-20:]][::-1],
            'reminders': [dict(key=r.key, **r.data) for r in records(db, 'reminder', gid) if not r.data.get('sent')][-20:],
            'metrics': metrics(db, gid),
            'memory_status': memory_status(db,gid,now),
            'modules': ['intent', 'participation', 'memory', 'context', 'orchestration', 'skills', 'proactive', 'delivery', 'identity', 'governance'],
        }
