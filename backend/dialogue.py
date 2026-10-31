"""Durable, user-bound questions. State is context, never a tool grant."""
import re
from .db import Message, get, put
from .addressing import unquoted_text

TTL = 600


def pending(db, gid, user_id, now, source_id=None):
    row = get(db, 'pending_question', gid, str(user_id))
    if not row:
        return None
    value = row.data
    if value.get('status') != 'waiting' or not 0 <= now - value['created'] <= TTL:
        return None
    if source_id is not None and value['message_id'] >= source_id:
        return None
    return value


def close(db, gid, user_id, status='closed', source_id=None):
    row = get(db, 'pending_question', gid, str(user_id))
    if row and (source_id is None or row.data['message_id'] < source_id):
        row.set({**row.data, 'status': status})


def question(content):
    """Conservatively extract questions from the actual delivered reply."""
    clean = unquoted_text(content)
    if not re.search(r'[？?]|(?:请|麻烦)(?:选择|告诉|补充|提供)|要不要|是否需要|可以吗', clean):
        return None
    numbered = re.findall(r'(?:^|\n)\s*(?:[1-9][.、）)]|第[一二三四五六七八九]个[：:])\s*(.+)', clean)
    options = numbered
    if not options and '还是' in clean:
        choice = next((part for part in re.split(r'[。！!？?\n]', content) if '还是' in part), '')
        options = [s.strip() for s in choice.split('还是') if s.strip()]
    kind = 'choice' if len(options) >= 2 else ('confirmation' if re.search(r'要不要|是否|需要我|可以吗|好吗|行吗|需要.*吗', clean) else 'information')
    if len(re.findall(r'[？?]', clean)) > 1:
        kind = 'ambiguous'
    return {'text': content, 'type': kind,
            'options': [{'index': i + 1, 'text': text, 'action': {'type': 'selection', 'value': text}} for i, text in enumerate(options)]}


def remember(db, gid, source_id, message_id, content, now):
    source = db.get(Message, source_id)
    if not source or source.group_id != gid or source.user_id == 0:
        return
    row = get(db, 'pending_question', gid, str(source.user_id))
    if row and (row.data['message_id'] >= message_id or row.data['source_id'] > source_id):
        return
    value = question(content)
    decision = get(db, 'decision', gid, str(source_id))
    intent = decision.data.get('intent', {}) if decision else {}
    from .appointment_intent import appointment_operation
    operation = appointment_operation(source.content)
    request = source.content
    if row and intent.get('engagement') == 'continuation':
        answer = answer_text(row.data, source.content)
        if answer is not None:
            request = row.data.get('request', '') + '\n补充：' + answer
    if value:
        put(db, 'pending_question', gid, str(source.user_id), {
            **value, 'request': request,
            'scene': intent.get('scene') or ('family-appointment' if operation else None),
            'operation': intent.get('operation') or operation,
            'user_id': source.user_id, 'source_id': source_id,
            'message_id': message_id, 'created': now, 'expires_at': now + TTL, 'status': 'waiting'})
    else:
        close(db, gid, source.user_id, 'completed')


def short_answer(text):
    return bool(re.fullmatch(r'\s*(?:好的?|可以|行|嗯|同意|就这样办|收到|谢谢|第[一二三四五六七八九十\d]+个|(?:今天|明天|后天)?(?:上午|下午|晚上)|\d{1,2}点(?:半|\d{1,2}分)?)\s*[。！!，,]*\s*', text))


def answer_text(value, text):
    """Resolve only unambiguous original choices; agreement is not a selection."""
    if value['type'] == 'ambiguous':
        return None
    if value['type'] == 'choice':
        match = re.fullmatch(r'\s*第([一二三四五六七八九]|[1-9])个[。！!\s]*', text)
        if match:
            digit = match[1]
            index = int(digit) if digit.isdigit() else '一二三四五六七八九'.index(digit) + 1
            return next((o['text'] for o in value.get('options', []) if o['index'] == index), None)
        matches = [o for o in value.get('options', []) if o['text'] == text or any(
            word in o['text'] and word in text for word in ('上午', '下午', '晚上'))]
        if len(matches) == 1:
            return text
        return None
    elif value['type'] == 'information' and re.fullmatch(r'\s*(?:好的?|可以|行|嗯|同意|就这样办)[。！!\s]*', text):
        return None
    return text
