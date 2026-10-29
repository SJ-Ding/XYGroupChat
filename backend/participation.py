"""Deterministic participation policy; silence is a first-class outcome."""
from .contracts import ParticipationDecision


def decide(event, intent, settings):
    if intent.quoted:
        return ParticipationDecision('silent', '引用不触发助手', intent.topic)
    if event.direct:
        return ParticipationDecision('reply', '直接向助手发起请求', intent.topic)
    if intent.kind != 'request' or intent.confidence < .85:
        return ParticipationDecision('silent', '不是确定的求助，保持安静', intent.topic)
    if intent.target == 'agent':
        return ParticipationDecision('reply', '明确向助手求助', intent.topic)
    if settings.get('active') and intent.assistant_helpful:
        return ParticipationDecision('observe', '优先等待家人回应', intent.topic)
    return ParticipationDecision('silent', '没有明确的助手帮助空间', intent.topic)


def send_policy(db, gid, demand, now, settings):
    from .db import records
    if not settings.get('active') or settings['version'] != demand['settings']['version']:
        return 'cancelled'
    if now - demand.get('created', demand['deadline']) > settings.get('need_ttl_seconds', 86400):
        return 'expired'
    # Existing MVP demands remain compatible. New decisions carry a topic.
    if demand.get('topic'):
        if any(r.data.get('kind') == 'over_intervention' and r.data.get('topic') == demand['topic']
               and now - r.data['at'] < 86400 for r in records(db, 'feedback', gid)):
            return 'feedback_suppressed'
        for r in records(db, 'demand', gid):
            d = r.data
            if d.get('status') == 'sent':
                if d.get('topic') == demand['topic'] and now - d.get('sent_at', 0) < settings.get('duplicate_seconds', 3600):
                    return 'duplicate'
                if now - d.get('sent_at', 0) < settings.get('cooldown_seconds', 300):
                    return 'cooldown'
    return 'ready'
