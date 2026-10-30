import json
import re
import time
import uuid
from sqlalchemy import text
from .db import Record, get, put, records

# Supported memory domains. 'general' covers daily life (birthdays, preferences,
# plans). Vertical domains (medical, transport, ...) carry structured profiles.
DOMAINS = ('general', 'medical')

def tokens(value):
    # Chinese character bigrams work without a separate tokenizer dependency.
    chars = re.findall(r'[\u3400-\u9fff]', value)
    words = re.findall(r'[a-zA-Z0-9]+', value.lower())
    return ' '.join(words + chars + [''.join(chars[i:i+2]) for i in range(len(chars)-1)])

def index(db, record):
    """Reindex a memory record into the FTS table with its domain column."""
    db.execute(text('DELETE FROM memory_fts WHERE record_id=:id'), {'id': record.id})
    if not record.data.get('deleted') and record.data.get('status', 'active') == 'active':
        domain = record.data.get('domain', 'general')
        db.execute(text('INSERT INTO memory_fts VALUES (:id,:gid,:domain,:tokens)'),
            {'id': record.id, 'gid': record.group_id, 'domain': domain, 'tokens': tokens(record.data['content'])})

def index_memory_records(db):
    """Reindex all memory records — used by migration v5 to populate the new domain column."""
    all_memories = db.query(Record).filter_by(kind='memory').all()
    for record in all_memories:
        index(db, record)

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
                metadata=None, replace_automatic=False, expected_version=None, domain=None, profile=None):
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
    # Determine domain: explicit > inherit from old > default 'general'.
    # 'general' covers daily life; vertical domains (medical, ...) carry profiles.
    resolved_domain = domain or (old.data.get('domain') if old else None) or 'general'
    if resolved_domain not in DOMAINS:
        resolved_domain = 'general'
    # Profile is structured vertical data (e.g. hospital, doctor, medications).
    # Only stored for non-general domains; general memories stay text-only.
    resolved_profile = None
    if resolved_domain != 'general':
        if isinstance(profile, dict):
            resolved_profile = profile
        elif old and old.data.get('profile'):
            resolved_profile = old.data['profile']
    r = put(db, 'memory', gid, key or str(uuid.uuid4()), {**(old.data if old else {}), 'content': content, 'sources': sources, 'subjects': subjects or [], 'manual': manual, 'deleted': False, 'updated': now,
        'lifetime': lifetime, 'scope': scope, 'owner_id': owner_id, 'expires_at': expires_at,
        'confirmed': manual if confirmed is None else confirmed, 'sensitive': sensitive,
        'explicit': explicit or bool(old and old.data.get('explicit')), 'status':'active',
        'domain': resolved_domain, **({'profile': resolved_profile} if resolved_profile else {}), **extra})
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

def search(db, gid, query, limit=10, *, viewer_id=None, now=None, domain=None):
    """FTS search with optional domain filtering.

    domain=None searches all domains; domain='medical' searches only medical
    memories; domain='general' searches only daily-life memories.
    """
    terms = list(dict.fromkeys(tokens(query).split()))[:100]
    if not terms:
        return []
    match = ' OR '.join('"' + t + '"' for t in terms)
    where = 'memory_fts MATCH :q AND group_id=:gid'
    params = {'q': match, 'gid': gid}
    if domain is not None:
        where += ' AND domain=:domain'
        params['domain'] = domain
    ids = db.execute(text('SELECT record_id FROM memory_fts WHERE ' + where + ' ORDER BY rank'), params).scalars().all()
    found = {r.id: r for r in db.query(Record).filter(Record.id.in_(ids), Record.kind == 'memory', Record.group_id == gid).all()}
    return [dict(key=found[i].key, **found[i].data) for i in ids if i in found and visible(found[i].data, gid, viewer_id, now)][:limit]


def list_profile(db, gid, member_id, domain, now=None):
    """Return all structured profile memories for a member in a vertical domain.

    Unlike FTS search, this scans memories by domain + subject directly,
    so it works for vague queries (e.g. '帮我挂号') that lack keywords.
    Returns a list of {key, content, profile, ...} dicts grouped naturally.
    Matches by integer subject_ids, owner_id, profile.member_id, or member name.
    """
    now = time.time() if now is None else now
    from .db import User
    member = db.get(User, member_id)
    member_name = member.name if member else None
    result = []
    for r in records(db, 'memory', gid):
        d = r.data
        if d.get('domain') != domain or not visible(d, gid, -gid if gid < 0 else None, now):
            continue
        sids = d.get('subject_ids') or []
        subs = d.get('subjects') or []
        prof = d.get('profile') or {}
        matched = (member_id in sids if sids else False) or \
                  d.get('owner_id') == member_id or \
                  (member_name and member_name in subs) or \
                  prof.get('member_id') == member_id
        if not matched:
            continue
        result.append(dict(key=r.key, **d))
    return result
