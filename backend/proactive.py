"""Consent-aware scheduling, transactional outbox and delivery feedback."""
import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from .db import Message, Record, User, get, put, records
from .memory import visible, list_memories

TOPICS = {'life', 'health'}
FEEDBACK = {'delivered', 'acknowledged', 'completed', 'snoozed', 'skipped', 'dismissed', 'stopped'}


def next_occurrence(after, zone, clock, weekdays=None):
    tz = ZoneInfo(zone)
    hour, minute = map(int, clock.split(':'))
    weekdays = weekdays if weekdays is not None else list(range(7))
    local = datetime.fromtimestamp(after, tz)
    for offset in range(9):
        day = local.date() + timedelta(days=offset)
        if day.weekday() not in weekdays:
            continue
        dt = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
        # Nonexistent local times are skipped, repeated times fire once.
        stamp = dt.timestamp()
        roundtrip = datetime.fromtimestamp(stamp, tz)
        if roundtrip.hour == hour and roundtrip.minute == minute and stamp > after:
            return stamp
    raise ValueError('周期规则无下一次触发时间')


def quiet(now, preference):
    if not preference or not preference.get('quiet_start') or not preference.get('quiet_end'):
        return False
    clock = datetime.fromtimestamp(now, ZoneInfo(preference.get('timezone', 'Asia/Shanghai'))).strftime('%H:%M')
    start, end = preference['quiet_start'], preference['quiet_end']
    return (start <= clock < end) if start < end else (clock >= start or clock < end)


def outbox(db, gid, key, content, user_id, channel, now, **metadata):
    if (channel == 'personal') != (gid < 0):
        raise ValueError('个人触达不能转发到群，群消息不能进入其他成员私人空间')
    old = get(db, 'delivery', gid, key)
    if old:
        return old, None
    message_id = None
    if channel == 'group':
        message = Message(group_id=gid, user_id=0, client_id='delivery:' + key, content=content, attachments='[]', created=now)
        db.add(message)
        db.flush()
        message_id = message.id
    r = put(db, 'delivery', gid, key, {'content': content, 'user_id': user_id, 'channel': channel,
        'status': 'sent', 'at': now, 'message_id': message_id, **metadata})
    return r, message_id


def event_candidate(db, gid, rule, now):
    trigger = rule.get('trigger', 'daily')
    seen = rule.get('seen_events', [])
    if trigger == 'task_due':
        for r in records(db, 'task', gid):
            d = r.data
            if not d.get('done') and d.get('due') and now <= d['due'] <= now + 86400:
                key = f'task:{r.key}:{d["due"]}'
                if key not in seen:
                    return key, '有一项待办将在24小时内到期，请到待办列表查看。'
    # Memory events are strictly personal, including their existence metadata.
    if trigger == 'memory_expiring' and gid < 0 and rule['user_id'] == -gid and rule['channel'] == 'personal':
        for m in list_memories(db, gid, -gid, now):
            if rule.get('memory_key') and m['key'] != rule['memory_key']:
                continue
            if m.get('expires_at') and m['expires_at'] <= now + 86400:
                key = f'memory:{m["key"]}:{m["expires_at"]}'
                if key not in seen:
                    return key, '有一条阶段性记忆将在24小时内到期，请到个人记忆列表核对。'
    return None


def medical_followup_reminders(db, gid, now):
    """Scan medical-domain memories for upcoming follow_up_date values.

    When a follow-up is within 72 hours and no reminder has been created yet,
    generate a one-time group reminder. This does NOT infer medication adherence
    or dosing — it only surfaces the appointment time stored in the profile.
    Returns a list of newly created message IDs.
    """
    import hashlib as _hashlib
    events = []
    for r in records(db, 'memory', gid):
        d = r.data
        if d.get('domain') != 'medical' or d.get('deleted') or d.get('status', 'active') != 'active':
            continue
        profile = d.get('profile') or {}
        follow_up = profile.get('follow_up_date')
        if not isinstance(follow_up, (int, float)):
            continue
        # Only create reminders for follow-ups within the next 72h window
        if not (now - 3600 <= follow_up <= now + 72 * 3600):
            continue
        member_id = (d.get('subject_ids') or [0])[0] if d.get('subject_ids') else 0
        reminder_key = f'medical_followup:{r.key}'
        existing = get(db, 'reminder', gid, reminder_key)
        if existing and existing.data.get('sent'):
            continue
        if existing and existing.data.get('status') == 'active':
            continue
        # Build a natural reminder content from the profile
        parts = []
        if profile.get('hospital'):
            parts.append(profile['hospital'])
        if profile.get('department'):
            parts.append(profile['department'])
        if profile.get('doctor'):
            parts.append(profile['doctor'] + '医生')
        location = '·'.join(parts) if parts else '医院'
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI
        local_time = _dt.fromtimestamp(follow_up, _ZI('Asia/Shanghai')).strftime('%m月%d日 %H:%M')
        content = f'{local_time}有一次复诊（{location}）。记得带上医保卡和之前的药单。此提醒不表示需要服药。'
        # Create or refresh the reminder; it fires at follow_up time
        put(db, 'reminder', gid, reminder_key, {
            'content': content, 'at': follow_up, 'sent': False,
            'user_id': member_id, 'channel': 'group' if gid > 0 else 'personal',
            'status': 'active', 'version': 1,
            'category': 'medical_followup', 'source_memory': r.key
        })
    return events


def schedule_tick(db, gid, now):
    events = []
    for r in records(db, 'reminder', gid):
        d = r.data
        if d.get('status', 'active') != 'active' or d.get('sent') or d['at'] > now:
            continue
        user_id = d.get('user_id', -gid if gid < 0 else 0)
        if d.get('root_reminder_key'):
            root = get(db, 'reminder', gid, d['root_reminder_key'])
            if not root or root.data.get('status', 'active') != 'active' or root.data.get('version', 1) != d.get('root_version'):
                r.set({**d, 'status': 'cancelled'})
                continue
        pref = get(db, 'preference', -user_id, 'delivery') if user_id else None
        if quiet(now, pref.data if pref else None) and d.get('respect_quiet', True):
            continue
        occurrence = d['at']
        key = f'reminder:{r.key}:v{d.get("version", 1)}:{occurrence}'
        # Legacy MVP reminders preserve their original unique-send semantics.
        grace = d.get('grace_seconds', 86400)
        if now - occurrence <= grace:
            _, mid = outbox(db, gid, key, '提醒：' + d['content'], user_id,
                d.get('channel', 'personal' if gid < 0 else 'group'), now,
                reminder_key=r.key, reminder_version=d.get('version', 1), root_reminder_key=d.get('root_reminder_key'), root_version=d.get('root_version'), occurrence=occurrence, category=d.get('category', 'daily'))
            if mid:
                events.append(mid)
        else:
            put(db, 'missed', gid, key, {'reminder_key': r.key, 'occurrence': occurrence, 'at': now})
        if d.get('clock'):
            d['at'] = next_occurrence(now, d.get('timezone', 'Asia/Shanghai'), d['clock'], d.get('weekdays'))
        else:
            d['sent'] = True
        r.set(d)
    # Subscriptions are stored in their delivery namespace. Personal rules never
    # fall back to the family group. Templates do not inspect private memories.
    for r in records(db, 'subscription', gid):
        d = r.data
        if not d.get('enabled'):
            continue
        trigger = d.get('trigger', 'daily')
        candidate = event_candidate(db, gid, d, now)
        if trigger == 'daily' and d['next_at'] > now:
            continue
        if trigger != 'daily' and not candidate:
            continue
        uid = d['user_id']
        pref = get(db, 'preference', -uid, 'delivery')
        if quiet(now, pref.data if pref else None):
            continue
        tz = ZoneInfo(d['timezone'])
        day = datetime.fromtimestamp(now, tz).date().isoformat()
        personal_tz = ZoneInfo((pref.data if pref else {}).get('timezone', 'Asia/Shanghai'))
        day_start = datetime.fromtimestamp(now, personal_tz).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        # Per-person cap spans both personal and group channels.
        personal_count = sum(1 for rec in db.query(Record).filter_by(kind='care_quota').all()
                             if rec.data.get('user_id') == uid and rec.data['at'] >= day_start)
        group_day_start = datetime.fromtimestamp(now, ZoneInfo('Asia/Shanghai')).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        group_count = sum(1 for rec in records(db, 'delivery', gid) if rec.data.get('subscription_key') and rec.data['at'] >= group_day_start)
        personal_limit = (pref.data if pref else {}).get('care_limit', 1)
        settings = get(db, 'group', gid, 'settings')
        group_limit = settings.data.get('care_group_limit', 1) if settings else 1
        if personal_count >= personal_limit or (gid > 0 and group_count >= group_limit):
            d['next_at'] = next_occurrence(now, d['timezone'], d['clock'], d.get('weekdays'))
            r.set(d)
            continue
        key = f'care:{r.key}:{candidate[0] if candidate else day}'
        content = d.get('content') or ('今天有什么需要一起安排的事吗？' if d['topic'] == 'life' else '今天感觉怎么样？如果需要，可以记录自己的感受。')
        if candidate:
            content = candidate[1]
        elif d.get('memory_key'):
            if gid >= 0 or d['channel'] != 'personal' or uid != -gid:
                continue
            m = get(db, 'memory', gid, d['memory_key'])
            if not m or not visible(m.data, gid, uid, now):
                d['next_at'] = next_occurrence(now, d['timezone'], d['clock'], d.get('weekdays'))
                r.set(d)
                continue
            content = '你关注的事项今天需要安排吗？可以到个人记忆列表查看并更新。'
        if not get(db, 'delivery', gid, key):
            shadow = d.get('shadow', True)
            if shadow:
                put(db, 'shadow', gid, key, {'action': 'suggest', 'topic': d['topic'], 'user_id': uid, 'at': now})
            else:
                _, mid = outbox(db, gid, key, content, uid, d['channel'], now, subscription_key=r.key, topic=d['topic'])
                put(db, 'care_quota', 0, key + f':{gid}', {'user_id': uid, 'at': now})
                if mid:
                    events.append(mid)
        d['next_at'] = next_occurrence(now, d['timezone'], d['clock'], d.get('weekdays'))
        if candidate:
            d['seen_events'] = [*d.get('seen_events', []), candidate[0]][-100:]
        r.set(d)
    # Proactive medical follow-up reminders: scan medical-domain memories for
    # upcoming follow_up_date values. Create a one-time reminder 24h before the
    # appointment if none exists yet. Does not infer medication adherence.
    events.extend(medical_followup_reminders(db, gid, now))
    # Escalation is an explicit agreement about a missing confirmation, never
    # an inference that medication was not taken. Notify only the chosen inbox.
    for delivery in records(db, 'delivery', gid):
        d = delivery.data
        if d['status'] not in ('sent', 'delivered') or not d.get('reminder_key'):
            continue
        reminder = get(db, 'reminder', gid, d['reminder_key'])
        rule = reminder.data if reminder else {}
        recipient = rule.get('notify_user_id')
        if not recipient or rule.get('status') != 'active' or rule.get('version', 1) != d.get('reminder_version'):
            continue
        if now < d['at'] + rule['notify_after_minutes'] * 60:
            continue
        pref = get(db, 'preference', -recipient, 'delivery')
        if quiet(now, pref.data if pref else None):
            continue
        sender = db.get(User, d['user_id'])
        outbox(db, -recipient, f'confirmation:{gid}:{delivery.key}',
            f'{sender.name if sender else "家人"}约定的提醒尚未收到确认。此消息不代表事项未完成。', recipient, 'personal', now,
            confirmation_notice=True)
    return events


def feedback(db, gid, key, uid, action, now, snooze_minutes=10):
    r = get(db, 'delivery', gid, key)
    if not r or r.data['user_id'] not in (0, uid):
        raise ValueError('此触达不存在或不属于你')
    if action not in FEEDBACK:
        raise ValueError('无效反馈')
    d = r.data
    terminal = {'completed', 'skipped', 'dismissed', 'stopped', 'snoozed'}
    if d['status'] in terminal:
        if d['status'] == action:
            return d
        raise ValueError('此触达已经处理')
    if action == 'delivered' and d['status'] != 'sent':
        return d
    if action == 'snoozed':
        if not 1 <= snooze_minutes <= 1440:
            raise ValueError('稍后提醒应在1到1440分钟内')
        skey = hashlib.sha256(f'{key}:{uid}:snooze'.encode()).hexdigest()
        put(db, 'reminder', gid, skey, {'content': d['content'].removeprefix('提醒：'), 'at': now + snooze_minutes * 60,
            'user_id': uid, 'channel': d['channel'], 'status': 'active', 'version': 1, 'sent': False,
            'category': d.get('category', 'daily'), 'parent_delivery': key,
            'root_reminder_key': d.get('root_reminder_key') or d.get('reminder_key'),
            'root_version': d.get('root_version') or d.get('reminder_version')})
    if action == 'stopped':
        for kind, ref in [('reminder', d.get('reminder_key')), ('reminder', d.get('root_reminder_key')), ('subscription', d.get('subscription_key'))]:
            record = get(db, kind, gid, ref) if ref else None
            if record:
                value = record.data
                value.update(status='cancelled', enabled=False)
                record.set(value)
    d.update(status=action, feedback_by=uid, feedback_at=now)
    r.set(d)
    put(db, 'feedback', gid, f'{key}:{uid}:{action}', {'kind': action, 'delivery_key': key, 'user_id': uid, 'at': now})
    return d
