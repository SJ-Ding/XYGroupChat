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
    if not record.data.get('deleted'):
        db.execute(text('INSERT INTO memory_fts VALUES (:id,:gid,:tokens)'), {'id': record.id, 'gid': record.group_id, 'tokens': tokens(record.data['content'])})

def save_memory(db, gid, content, sources=None, subjects=None, key=None, manual=False):
    sources = sources or []
    if not manual:
        for suppression in records(db, 'suppression', gid):
            if set(sources) & set(suppression.data['sources']):
                return None
    old = get(db, 'memory', gid, key) if key else None
    if old and (old.data.get('manual') or old.data.get('deleted')) and not manual:
        return old
    if old:
        put(db, 'revision', gid, str(uuid.uuid4()), {'memory_key': old.key, 'previous': old.data, 'at': time.time()})
    r = put(db, 'memory', gid, key or str(uuid.uuid4()), {'content': content, 'sources': sources, 'subjects': subjects or [], 'manual': manual, 'deleted': False, 'updated': time.time()})
    index(db, r)
    return r

def delete_memory(db, r):
    d = r.data
    put(db, 'revision', r.group_id, str(uuid.uuid4()), {'memory_key': r.key, 'previous': d, 'at': time.time()})
    put(db, 'suppression', r.group_id, r.key, {'sources': d.get('sources', [])})
    d['deleted'] = True
    r.set(d)
    index(db, r)

def search(db, gid, query, limit=10):
    terms = list(dict.fromkeys(tokens(query).split()))[:100]
    if not terms:
        return []
    ids = db.execute(text('SELECT record_id FROM memory_fts WHERE memory_fts MATCH :q AND group_id=:gid ORDER BY rank LIMIT :lim'), {'q': ' OR '.join('"'+t+'"' for t in terms), 'gid': gid, 'lim': limit}).scalars().all()
    found = {r.id: r for r in db.query(Record).filter(Record.id.in_(ids), Record.kind == 'memory', Record.group_id == gid).all()}
    return [dict(key=found[i].key, **found[i].data) for i in ids if i in found and not found[i].data.get('deleted')]
