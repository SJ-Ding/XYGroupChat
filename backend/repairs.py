"""Versioned, audited repair of the two legacy live-test inconsistencies."""
from .db import DB, Record, Message, get, put
from .authorization import command_grants
from .memory import merge_explicit_duplicates


def repair_legacy_harness(db):
    merged = 0
    for memory in db.query(Record).filter_by(kind='memory').all():
        d = memory.data
        if not d.get('manual') or d.get('deleted'):
            continue
        sources = d.get('sources', [])
        # The source must prove an explicit remember command; merely sharing a
        # message with a manual edit is insufficient to retire another fact.
        proven = bool(sources)
        for source_id in sources:
            source = db.get(Message, source_id)
            job = get(db, 'job', memory.group_id, str(source_id))
            group = get(db, 'group', memory.group_id, 'settings')
            settings = job.data.get('settings', {}) if job else (group.data if group else {})
            if not source or source.group_id != memory.group_id or not any(
                    g['tool'] == 'remember' for g in command_grants(source.content, settings.get('agent_name', '小忆'), source.created)):
                proven = False
                break
        if proven:
            memory.set({**d, 'explicit': True})
            merged += merge_explicit_duplicates(db, memory)
    replies = 0
    for run in db.query(Record).filter_by(kind='run').all():
        d = run.data
        if not d.get('conversation') or not run.key.startswith('mention:') or d.get('status') != 'failed':
            continue
        steps = d.get('steps', [])
        job = get(db, 'job', run.group_id, run.key[len('mention:'):])
        if job and job.data.get('status') == 'failed' and steps and all(s.get('status') == 'succeeded' for s in steps):
            error = job.data.get('error')
            job.set({**job.data, 'status': 'reply_failed', 'action_status': 'succeeded', 'reply_status': 'failed', 'failure_stage': 'reply'})
            d.pop('error', None)
            run.set({**d, 'status': 'succeeded', 'action_status': 'succeeded', 'reply_status': 'failed', 'reply_error': error})
            replies += 1
    return {'merged_memories': merged, 'reply_failures_reclassified': replies}
