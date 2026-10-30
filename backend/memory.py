import json
import re
import time
import uuid
from sqlalchemy import text
from .db import Record, get, put, records

def tokens(value):
    # Chinese character bigrams work without a separate tokenizer dependency.
    chars = re.findall(r'[\u3400-\u9fff]', value)
    words = re.findall(r'[a-zA-Z0-9]+', value.lower())
    return ' '.join(words + chars + [''.join(chars[i:i+2]) for i in range(len(chars)-1)])

def index(db, record):
    db.execute(text('DELETE FROM memory_fts WHERE record_id=:id'), {'id': record.id})
    if not record.data.get('deleted') and record.data.get('status', 'active') == 'active':
        db.execute(text('INSERT INTO memory_fts VALUES (:id,:gid,:tokens)'), {'id': record.id, 'gid': record.group_id, 'tokens': tokens(record.data['content'])})

def visible(data, gid, viewer_id=None, now=None):
    now = time.time() if now is None else now
    if data.get('deleted') or data.get('status', 'active') != 'active' or (data.get('expires_at') is not None and data['expires_at'] <= now):
        return False
    scope = data.get('scope', 'private' if gid < 0 else 'group')
    if scope == 'private':
        return gid < 0 and viewer_id == -gid and data.get('owner_id', -gid) == viewer_id
    return gid > 0


def list_memories(db, gid, viewer_id=None, now=None):
    return [dict(key=r.key, **r.data) for r in records(db, 'memory', gid) if visible(r.data, gid, viewer_id, now)]


def save_memory(db, gid, content, sources=None, subjects=None, key=None, manual=False,
                *, lifetime='long', expires_at=None, scope=None, owner_id=None,
                confirmed=None, now=None, sensitive=False, explicit=False,
                metadata=None, replace_automatic=False, expected_version=None):
    now = time.time() if now is None else now
    scope = scope or ('private' if gid < 0 else 'group')
    if not isinstance(content, str) or not content.strip() or len(content) > 2000:
        raise ValueError('记忆内容应为1到2000字')
    if lifetime not in ('working', 'short', 'long') or scope not in ('group', 'profile', 'private'):
        raise ValueError('无效的记忆层级或可见范围')
    if (scope == 'private') != (gid < 0):
        raise ValueError('私人记忆必须保存在个人空间')
    if gid < 0:
        owner_id = -gid
    if expires_at is None and lifetime != 'long':
        expires_at = now + (86400 if lifetime == 'working' else 7 * 86400)
    if expires_at is not None and expires_at <= now:
        raise ValueError('记忆有效期必须晚于现在')
    sources = sources or []
    if not manual:
        for suppression in records(db, 'suppression', gid):
            if set(sources) & set(suppression.data['sources']):
                return None
        for candidate in records(db, 'memory', gid):
            d = candidate.data
            if d.get('manual') and d.get('explicit') and not d.get('deleted') and sources and set(sources) <= set(d.get('sources', [])):
                return candidate
    old = get(db, 'memory', gid, key) if key else None
    if expected_version is not None and (not old or old.data.get('version', 1) != expected_version):
        raise ValueError('记忆版本冲突，请刷新后重试')
    if old and (old.data.get('manual') or old.data.get('deleted')) and not manual:
        return old
    if old and not manual and old.data['content'] != content and not replace_automatic:
        conflict_key = str(uuid.uuid5(uuid.NAMESPACE_URL, f'{gid}:{old.key}:{content}'))
        put(db, 'memory_conflict', gid, conflict_key, {'memory_key': old.key, 'proposed': content,
             'sources': sources, 'status': 'pending', 'at': now})
        return old
    if old:
        put(db, 'revision', gid, str(uuid.uuid4()), {'memory_key': old.key, 'previous': old.data, 'at': time.time()})
    extra = {k:v for k,v in (metadata or {}).items() if k in ('category','topic','topic_key','subject_ids','tentative','eligible_long_term','observations','last_observed_at','first_observed_at','last_reviewed_at','promoted_at','archived_at','status','expiry_from_time')}
    r = put(db, 'memory', gid, key or str(uuid.uuid4()), {**(old.data if old else {}), 'content': content, 'sources': sources, 'subjects': subjects or [], 'manual': manual, 'deleted': False, 'updated': now,
        'lifetime': lifetime, 'scope': scope, 'owner_id': owner_id, 'expires_at': expires_at,
        'confirmed': manual if confirmed is None else confirmed, 'sensitive': sensitive,
        'explicit': explicit or bool(old and old.data.get('explicit')), 'status':'active', **extra})
    if manual:
        for conflict in records(db, 'memory_conflict', gid):
            d = conflict.data
            if d['memory_key'] == r.key and d['status'] == 'pending':
                conflict.set({**d, 'status': 'resolved'})
    index(db, r)
    if manual and r.data.get('explicit'):
        merge_explicit_duplicates(db, r)
    return r


def merge_explicit_duplicates(db, canonical):
    """Only supersede automatic entries from the same explicit source.

    Do not merge arbitrary similar facts, other members, or manual records.
    Preserve the original entry and record the merge in the canonical history.
    """
    sources = set(canonical.data.get('sources', []))
    if not sources or canonical.data.get('deleted'):
        return 0
    count = 0
    for other in records(db, 'memory', canonical.group_id):
        d = other.data
        if other.key == canonical.key or d.get('manual') or d.get('deleted'):
            continue
        if d.get('sources') and set(d['sources']) <= sources:
            put(db, 'revision', canonical.group_id, str(uuid.uuid4()), {'memory_key': canonical.key,
                'previous': d, 'at': time.time(), 'operation': 'merge_explicit', 'merged_key': other.key})
            other.set({**d, 'deleted': True, 'merged_into': canonical.key})
            index(db, other)
            count += 1
    return count

def delete_memory(db, r):
    d = r.data
    put(db, 'revision', r.group_id, str(uuid.uuid4()), {'memory_key': r.key, 'previous': d, 'at': time.time()})
    sources = set(d.get('sources', []))
    for conflict in records(db, 'memory_conflict', r.group_id):
        value = conflict.data
        if value['memory_key'] == r.key:
            sources.update(value.get('sources', []))
            conflict.set({**value, 'status': 'discarded'})
    put(db, 'suppression', r.group_id, r.key, {'sources': sorted(sources)})
    d['deleted'] = True
    r.set(d)
    index(db, r)

def search(db, gid, query, limit=10, *, viewer_id=None, now=None):
    terms = list(dict.fromkeys(tokens(query).split()))[:100]
    if not terms:
        return []
    ids = db.execute(text('SELECT record_id FROM memory_fts WHERE memory_fts MATCH :q AND group_id=:gid ORDER BY rank'), {'q': ' OR '.join('"'+t+'"' for t in terms), 'gid': gid}).scalars().all()
    found = {r.id: r for r in db.query(Record).filter(Record.id.in_(ids), Record.kind == 'memory', Record.group_id == gid).all()}
    return [dict(key=found[i].key, **found[i].data) for i in ids if i in found and visible(found[i].data, gid, viewer_id, now)][:limit]
