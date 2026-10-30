"""Immediate scoped observations and local, deterministic memory consolidation.

Periodic review does not send private memories to another service and never
creates reminders, tasks, or public chat messages.
"""
import hashlib
import math
import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from .db import Member, get, put, records
from .memory import save_memory, index, visible

# Sensitive keywords (including medical) are suppressed from automatic capture
# unless the model explicitly classifies the memory as category='medical'.
# This prevents casual mentions of "药" in daily plans from being captured as
# medical memory, while still allowing structured medical extraction when the
# model identifies a genuine medical fact (prescription, diagnosis, follow-up).
SENSITIVE = re.compile(r'药|病|诊断|血压|血糖|身份证|密码|银行卡|验证码|抑郁|焦虑症|怀孕|过敏|体检')
MEDICAL_CONTEXT = re.compile(r'挂号|就诊|复诊|药单|处方|科室|医院|医生')
OPT_OUT = re.compile(r'别记|不要记|不用记|不必记|别保存|不要保存|别记录|不要记录|不需要记')
CATEGORIES = {'preference','fact','plan','state','event','medical'}


def normalized(value):
    return re.sub(r'\s+', '', value).lower()


def audit(db, memory, operation, now):
    put(db,'revision',memory.group_id,str(uuid.uuid4()),{'memory_key':memory.key,'previous':memory.data,'at':now,'operation':operation})


def mark_dirty(db, gid, now):
    state = get(db,'memory_maintenance',gid,'latest')
    d = state.data if state else {'last_run':None,'next_due':now+300,'runs':0,'counts':{}}
    d['next_due'] = min(d.get('next_due',now+300),now+300)
    d['dirty'] = True
    put(db,'memory_maintenance',gid,'latest',d)


def transitions(known, deltas, latest=None, intent=None):
    """Resolve/cancel identifies an existing item, without regenerating its fields."""
    by_key={m['key']:m for m in known}
    items=[]
    for delta in deltas[:3]:
        key=delta.get('key')
        old=by_key.get(key) if isinstance(key,str) else None
        state=delta.get('state')
        operation=delta.get('operation') or ({'cancelled':'cancel','resolved':'resolve'}.get(state) if isinstance(state,str) else None)
        if not old or operation not in ('resolve','cancel'):
            continue
        evidence=delta.get('evidence')
        confidence=delta.get('confidence',0)
        # Providers may emit the legacy {state,text} delta. Only accept that
        # variant when the latest utterance itself explicitly closes the plan.
        # Do not treat the paraphrased `text` field as source evidence.
        if not evidence:
            raw=latest.content if latest else ''
            pattern=r'取消|不去了|不做了|放弃|撤销|作废' if operation=='cancel' else r'已完成|已经完成|已经办完|已办完|做完了|结束了'
            if not intent or intent.confidence<.85 or (operation=='cancel' and intent.kind!='cancel') or not re.search(pattern,raw) or re.search(r'没(?:有)?取消|不取消|别取消|不要取消|尚未|如果|要不要|考虑',raw):
                continue
            evidence,confidence=raw,intent.confidence
        items.append({**{k:old[k] for k in ('content','subjects','subject_ids','category','topic') if k in old},
            'existing_key':key,'operation':operation,'evidence':evidence,'confidence':confidence})
    return items


def capture(db, gid, message, items, settings, now, known_keys=None):
    if not settings.get('memory_auto',True) or OPT_OUT.search(message.content):
        return []
    # Sensitive keywords (including medical) in the raw message require the
    # model to explicitly classify extracted memory as category='medical' to
    # pass. This prevents casual "拿药" in daily plans from being captured,
    # while allowing genuine medical facts (diagnosis, prescription, follow-up)
    # when the model identifies them as medical.
    message_sensitive = bool(SENSITIVE.search(message.content))
    if gid < 0:
        groups={m.group_id for m in db.query(Member).filter_by(user_id=-gid).all()}
        members={m.user_id for m in db.query(Member).filter(Member.group_id.in_(groups)).all()} | {-gid}
    else:
        members={m.user_id for m in db.query(Member).filter_by(group_id=gid).all()}
    changes = []
    for item in items[:3]:
        content = item.get('content')
        evidence = item.get('evidence') or (content if isinstance(content,str) and content in message.content else '')
        try:
            confidence = float(item.get('confidence',0))
        except (TypeError,ValueError):
            continue
        if not isinstance(content,str) or not content.strip() or len(content)>2000 or not math.isfinite(confidence) or confidence<.85:
            continue
        # Non-medical sensitive keywords in content are still suppressed.
        # Medical keywords are allowed when category is medical.
        if not isinstance(evidence,str) or not evidence.strip() or normalized(evidence) not in normalized(message.content):
            continue
        category = item.get('category','fact')
        if not isinstance(category,str) or category not in CATEGORIES:
            continue
        is_medical = category == 'medical'
        # Suppress sensitive content unless the item is explicitly medical.
        # When the raw message contains sensitive keywords (including medical),
        # only medical-category items are allowed; non-medical items are dropped.
        if not is_medical and (SENSITIVE.search(content) or message_sensitive):
            continue
        subject_ids = item.get('subject_ids') or [message.user_id]
        if not isinstance(subject_ids,list) or any(type(x) is not int or x not in members for x in subject_ids):
            continue
        subject_ids = sorted(set(subject_ids))
        topic = str(item.get('topic') or content)[:120].strip()
        slot = hashlib.sha256(f'{gid}:{subject_ids}:{category}:{normalized(topic)}'.encode()).hexdigest()
        existing_key = item.get('existing_key')
        if existing_key is not None and not isinstance(existing_key,str):
            continue
        if existing_key and known_keys is not None and existing_key not in known_keys:
            continue
        old = get(db,'memory',gid,existing_key) if isinstance(existing_key,str) else None
        if not old:
            matches = [r for r in records(db,'memory',gid) if not r.data.get('deleted') and
                       (r.data.get('topic_key')==slot or (r.data['content']==content and r.data.get('subject_ids',subject_ids)==subject_ids))]
            old = next((r for r in reversed(matches) if visible(r.data,gid,-gid if gid<0 else None,now)),
                       matches[-1] if matches else None)
        operation = item.get('operation','upsert')
        if operation not in ('upsert','update','resolve','cancel'):
            continue
        if old and old.data.get('subject_ids') and old.data['subject_ids'] != subject_ids:
            continue
        if old and message.created < old.data.get('last_observed_at',0):
            continue  # an older replay must not undo a newer arrangement
        if old and old.data.get('category') and old.data['category'] != category:
            continue
        if old and not visible(old.data,gid,-gid if gid<0 else None,now):
            if message.id in old.data.get('sources',[]):
                continue
            if operation=='upsert':
                old=None
        if old and old.data.get('manual'):
            if operation in ('update','resolve','cancel') and old.data['content'] != content:
                key=str(uuid.uuid5(uuid.NAMESPACE_URL,f'{gid}:{old.key}:{message.id}'))
                put(db,'memory_conflict',gid,key,{'memory_key':old.key,'proposed':content,'sources':[message.id],'status':'pending','at':now})
            continue
        if operation in ('resolve','cancel'):
            if not old or old.data.get('lifetime') not in ('working','short') or old.data.get('status','active')!='active':
                continue
            audit(db,old,operation,now)
            old.set({**old.data,'status':'resolved' if operation=='resolve' else 'cancelled','updated':now,'archived_at':now,
                'last_observed_at':message.created,'sources':sorted(set(old.data.get('sources',[])+[message.id]))})
            index(db,old);changes.append({'key':old.key,'operation':operation});continue
        if old and old.data.get('status','active') not in ('active','expired'):
            if operation!='update':
                continue
        lifetime = item.get('lifetime','short')
        if lifetime not in ('working','short'):
            lifetime='short'  # automatic long-term retention requires review
        seconds = 86400 if lifetime=='working' or category=='state' else settings.get('memory_short_days',7)*86400
        expires = message.created + seconds
        proposed = item.get('expires_at')
        if proposed is not None:
            if not isinstance(proposed,(int,float)) or not math.isfinite(proposed) or proposed<=message.created or proposed>message.created+366*86400:
                continue
            expires=proposed
        if lifetime=='working' or category=='state':
            expires=min(expires,message.created+86400)
        if expires<=now:
            continue
        same = bool(old and old.data['content']==content and visible(old.data,gid,-gid if gid<0 else None,now))
        if same and old.data.get('lifetime')=='long' and item.get('tentative') is True:
            continue
        expiry_from_time=proposed is not None
        if same and proposed is None and old.data.get('expiry_from_time'):
            expires=old.data['expires_at']
            expiry_from_time=True
        observations = list(old.data.get('observations',[])) if same else []
        if any(o['source']==message.id for o in observations):
            continue
        observations.append({'source':message.id,'at':message.created,'speaker':message.user_id})
        observations=sorted(observations,key=lambda o:o['at'])[-30:]
        tentative=item.get('tentative') is True
        stable=category in ('preference','fact') and item.get('stable') is True and not tentative and confidence>=.9
        eligible=stable and (old.data.get('eligible_long_term',True) if same else True)
        if same and old.data.get('lifetime')=='long':
            lifetime,expires='long',old.data.get('expires_at')
        subjects=item.get('subjects') or []
        if not isinstance(subjects,list) or any(not isinstance(s,str) for s in subjects):
            subjects=[]
        before = old.data if old else None
        sources=sorted(set([o['source'] for o in observations]+(old.data.get('sources',[]) if old else [])))
        # Medical memories use domain='medical' and carry structured profile data.
        memory_domain = 'medical' if is_medical else 'general'
        memory_profile = item.get('profile') if is_medical and isinstance(item.get('profile'), dict) else None
        r=save_memory(db,gid,content,sources,subjects,key=old.key if old else None,
            lifetime=lifetime,expires_at=expires,now=now,replace_automatic=operation=='update',
            domain=memory_domain, profile=memory_profile,
            metadata={'category':category,'topic':topic,'topic_key':slot,'subject_ids':subject_ids,'tentative':tentative,
                'eligible_long_term':eligible,'observations':observations,'first_observed_at':observations[0]['at'],
                'last_observed_at':message.created,'status':'active','expiry_from_time':expiry_from_time})
        if r and r.data != before:
            changes.append({'key':r.key,'operation':'update' if old else 'create'})
    if changes:
        mark_dirty(db,gid,now)
    return changes


def review(db, gid, settings, now):
    interval=settings.get('memory_review_seconds',21600)
    state=get(db,'memory_maintenance',gid,'latest')
    if not state:
        state=put(db,'memory_maintenance',gid,'latest',{'last_run':None,'next_due':now+interval,'runs':0,'counts':{},'dirty':False})
    if now<state.data['next_due']:
        return False
    counts={'expired':0,'promoted':0,'merged':0,'reviewed':0}
    entries=records(db,'memory',gid)
    for r in entries:
        d=r.data
        if d.get('deleted') or d.get('status','active')!='active':
            continue
        if d.get('expires_at') is not None and d['expires_at']<=now:
            audit(db,r,'expire',now)
            r.set({**d,'status':'expired','archived_at':now,'last_reviewed_at':now})
            index(db,r);counts['expired']+=1;continue
        counts['reviewed']+=1
        observations=d.get('observations',[])
        days={datetime.fromtimestamp(o['at'],ZoneInfo('Asia/Shanghai')).date() for o in observations}
        if settings.get('memory_auto',True) and not d.get('manual') and d.get('lifetime')=='short' and d.get('eligible_long_term') and not d.get('tentative') and d.get('category') in ('preference','fact','medical') and len(days)>=3 and len({o['source'] for o in observations})>=3:
            audit(db,r,'promote',now)
            r.set({**d,'lifetime':'long','expires_at':None,'promoted_at':now,'last_reviewed_at':now})
            index(db,r);counts['promoted']+=1
        elif not d.get('manual'):
            r.set({**d,'last_reviewed_at':now})
    # Merge exact equivalent automatic slots locally; never use similarity
    # guesses to merge different people, tentative plans or manual records.
    slots={}
    for r in entries:
        d=r.data
        if d.get('manual') or not visible(d,gid,-gid if gid<0 else None,now) or not d.get('topic_key'):
            continue
        signature=(d['topic_key'],d['content'],d.get('lifetime'),d.get('tentative',False))
        canonical=slots.get(signature)
        if not canonical:
            slots[signature]=r;continue
        base=canonical.data
        audit(db,canonical,'merge',now)
        observations={o['source']:o for o in base.get('observations',[])+d.get('observations',[])}
        canonical.set({**base,'sources':sorted(set(base.get('sources',[])+d.get('sources',[]))),
            'observations':sorted(observations.values(),key=lambda o:o['at'])[-30:],
            'expires_at':max(base.get('expires_at') or 0,d.get('expires_at') or 0) or None})
        r.set({**d,'deleted':True,'merged_into':canonical.key})
        index(db,r);index(db,canonical);counts['merged']+=1
    state.set({'last_run':now,'next_due':now+interval,'runs':state.data.get('runs',0)+1,'counts':counts,'dirty':False})
    return True


def status(db, gid, now):
    from .memory import list_memories
    active=list_memories(db,gid,-gid if gid<0 else None,now)
    state=get(db,'memory_maintenance',gid,'latest')
    return {'active':len(active),'working':sum(m.get('lifetime')=='working' for m in active),
        'short':sum(m.get('lifetime')=='short' for m in active),
        'long':sum(m.get('lifetime','long')=='long' for m in active),
        'general':sum(m.get('domain','general')=='general' for m in active),
        'medical':sum(m.get('domain')=='medical' for m in active),
        'maintenance':state.data if state else None}
