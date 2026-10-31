"""Deterministic participation policy; silence is a first-class outcome."""
import re
from .contracts import ParticipationDecision


def decide(event, intent, settings):
    if intent.quoted:
        return ParticipationDecision('silent', '引用不触发助手', intent.topic)
    if event.group_id < 0:
        return ParticipationDecision('reply', '私聊直接回应', intent.topic)
    if intent.engagement in ('mention_only', 'social', 'uncertain'):
        return ParticipationDecision('silent', '没有当前助手请求，保持安静', intent.topic)
    if intent.engagement == 'addressed' and event.direct and intent.kind != 'joke':
        return ParticipationDecision('reply', '直接向助手发起请求', intent.topic)
    if intent.kind != 'request' or intent.confidence < .85:
        return ParticipationDecision('silent', '不是确定的求助，保持安静', intent.topic)
    # Guard concrete status updates without imposing a vocabulary whitelist on requests.
    request_words = re.search(r'[？?]|怎么|如何|怎样|几点|何时|[吗么呢](?:[。！!\s]*$)|帮|请|麻烦|能否|能不能|提醒|查|告诉|整理|安排一下|给出|列|总结|对比|解读|说明|生成|压缩|梳理|改写|推荐|预定|预约', event.content)
    statement = re.search(r'^(?:我|我们).*(?:安排|计划|行程|事情).*(?:改到|改成|改为|取消了|完成了)|^我(?:们)?(?:已经)?(?:改到|改成|打算|准备|考虑|决定)|^我(?:们)?(?:今天|明天|后天|周[一二三四五六日天]|星期).*(?:出门|出发|回家|去|开会|看病|复诊)', event.content)
    if statement and not request_words:
        return ParticipationDecision('silent', '近况陈述不触发跟进', intent.topic)
    if intent.target == 'agent' and intent.engagement in ('addressed', 'implicit_request', 'continuation'):
        return ParticipationDecision('reply', '明确面向助手的请求，无需等待家人回应', intent.topic)
    if settings.get('active') and intent.assistant_helpful and intent.engagement == 'unresolved_need':
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
