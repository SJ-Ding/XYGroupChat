"""Shared, narrow appointment phrases for routing and simulator source checks."""
import re
from .addressing import unquoted_text

BOOKING_RE = re.compile(r'(?:挂|预约|预定|预订|订|安排|排).{0,16}(?:号|门诊|医生|专家|复诊|科)|约.{0,12}(?:的号|个号|门诊|医生|专家|科)|挂个')
NEGATION_RE = re.compile(r'(?:不要|不用|别|先别|不想|不必|不需要).{0,6}(?:挂|约|订|定|排)|取消')


def appointment_operation(text):
    clean = unquoted_text(text).strip()
    if not clean or NEGATION_RE.search(clean) or re.search(r'举例|示例|开玩笑|假设|如果', clean):
        return None
    if re.search(r'^(?:他说|她说|妈妈说|爸爸说|听说)|(?:已经|刚刚|昨天).{0,10}(?:约|挂|订)|(?:约|挂|订)(?:好|上|过|了)', clean):
        return None
    query = re.search(r'查询|查一下|查查|看看|有哪些|还有号|有没有号|有号吗|号(?:还有|有|能约)(?:吗|么|没|没有)|号源', clean)
    explicit_book = re.search(r'(?:帮|给).{0,12}(?:挂|约|订)|(?:预定|预订|订|排|安排).{0,12}(?:号|门诊|科)|^预约|(?:并|然后|直接).{0,4}(?:约|挂|订)', clean)
    if query and not explicit_book and re.search(r'号源|挂号|科|门诊|医生|还有号|有没有号|有号吗|号(?:还有|有|能约)(?:吗|么|没|没有)', clean):
        return 'query'
    if BOOKING_RE.search(clean):
        return 'book'
    return None


def appointment_time(text):
    """Preserve an explicitly requested clock time instead of broadening to a session."""
    from .reminder_language import number
    match = re.search(r'(?:(上午|早上|凌晨|下午|午后|中午|晚上)\s*)?([0-9零〇一二两三四五六七八九十]+)(?:[点时](半|一刻|三刻|[0-9零〇一二两三四五六七八九十]+分?)?|[:：](\d{1,2}))', text or '')
    if not match:
        return None
    period, hour, minute, colon_minute = match.groups()
    hour = number(hour)
    if colon_minute:
        minute = int(colon_minute)
    elif minute in ('半', '一刻', '三刻'):
        minute = {'半':30, '一刻':15, '三刻':45}[minute]
    else:
        minute = number(minute.removesuffix('分')) if minute else 0
    if period in ('下午','午后','晚上') and hour < 12:
        hour += 12
    if period == '凌晨' and hour == 12:
        hour = 0
    return f'{hour:02d}:{minute:02d}' if 0 <= hour < 24 and 0 <= minute < 60 else None
