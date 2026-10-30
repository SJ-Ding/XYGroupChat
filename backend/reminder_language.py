"""Recognize explicit one-shot reminder commands and resolve local clock language.

The source text grants only its own reminder; ambiguous/past times require a reply,
never a guessed next-day schedule. Resolution is anchored to the source timestamp.
"""
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from .persona import names_for

ZONE = ZoneInfo('Asia/Shanghai')
NUMBER = r'[0-9零〇一二两三四五六七八九十百]+'


@dataclass(frozen=True)
class ReminderRequest:
    content: str
    at: float | None = None
    clarification: str | None = None


def number(value):
    if value.isascii() and value.isdigit():
        return int(value)
    digits = dict(zip('零〇一二两三四五六七八九', [0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9]))
    total, current = 0, 0
    for char in value:
        if char in digits:
            current = digits[char]
        elif char in '十百':
            total += (current or 1) * (10 if char == '十' else 100)
            current = 0
        else:
            raise ValueError('不支持的数字')
    return total + current


def reminder_request(text, agent_name, created):
    names = '|'.join(re.escape(name) for name in names_for(agent_name))
    text = re.sub(r'^\s*@?(?:' + names + r')(?=\s|[，。！？,:：!?]|$)[\s，,:：]*', '', text).strip()
    text = re.sub(r'^(?:请帮我|麻烦你|麻烦|帮我|请)\s*', '', text)
    if '\n' in text or any(mark in text for mark in ['“', '”', '「', '」', '"', '>']):
        return None
    # Restrict the full utterance to a time-led imperative, or a reminder-led one.
    # Named family addressees, narratives, negations, questions about reminders,
    # and quotations cannot grant a write merely by containing “提醒我”.
    if not re.match(r'^(?:提醒(?:我|我们)|' + NUMBER + r'|今天|明天|后天|上午|下午|中午|晚上|早上|早晨|凌晨|傍晚|周[一二三四五六日天]|星期)', text):
        return None
    lead = text.split('提醒', 1)[0].strip()
    if lead and not re.fullmatch(r'(?:(?:今天|明天|后天|上午|下午|中午|晚上|早上|早晨|凌晨|傍晚|星期[一二三四五六日天]|周[一二三四五六日天]|分钟|小时|的时候|点|时|分|天|刻|半|钟|后)|' + NUMBER + r'|[:：，,\s])+', lead):
        return None
    match = re.fullmatch(r'(.*?)提醒(.*)', text)
    if not match:
        return None
    when, tail = match.groups()
    content = re.sub(r'^(?:我们|我)', '', tail).strip(' ：:，,。！!')
    if not content:
        return ReminderRequest('', clarification='需要提醒你做什么？请把提醒内容也告诉我。')
    if re.fullmatch(r'(?:什么|什么事|啥|啥事|做什么)[呢吗?？]*', content):
        return None
    if content.startswith(('的', '过', '了')):
        return None
    # Support the reversed “提醒我下午三点出门” form as well.
    if not when:
        reverse = re.match(r'(?:(?:今天|明天|后天)?(?:上午|下午|中午|晚上|早上|早晨|凌晨|傍晚)?' + NUMBER + r'(?:点|时)(?:一刻|三刻|半|' + NUMBER + r'分?)?|(?:今天|明天|后天)?(?:上午|下午|中午|晚上|早上|早晨|凌晨|傍晚)?\d{1,2}[:：]\d{2})', content)
        if not reverse:
            return ReminderRequest(content, clarification='你希望什么时候提醒？请告诉我具体时间，例如“今天下午三点一刻提醒我出门”。')
        when, content = reverse.group(), content[reverse.end():].strip()
        content = re.sub(r'^(?:的时候|钟)+', '', content).strip()
        if not content:
            return ReminderRequest('', clarification='需要提醒你做什么？请把提醒内容也告诉我。')
    when = re.sub(r'(?:的时候|钟)+\s*$', '', when.strip(' ：:，,'))
    relative = re.fullmatch('(' + NUMBER + r')(分钟|小时|天)后', when)
    if relative:
        count = number(relative[1])
        if not 0 < count <= 365 * 24 * 60 / {'分钟': 1, '小时': 60, '天': 1440}[relative[2]]:
            return ReminderRequest(content, clarification='请给出未来一年内的提醒时间。')
        return ReminderRequest(content, created + count * {'分钟': 60, '小时': 3600, '天': 86400}[relative[2]])
    clock = re.fullmatch(r'(今天|明天|后天)?(上午|下午|中午|晚上|早上|早晨|凌晨|傍晚)?(' + NUMBER + r')(?:[:：](\d{2})|(?:点|时)(一刻|三刻|半|' + NUMBER + r'分?)?)', when)
    if not clock:
        return ReminderRequest(content, clarification='请再确认具体日期和时间，例如“明天下午三点一刻提醒我出门”；这条提醒还没有设置。')
    day, period, raw_hour, colon_minute, spoken_minute = clock.groups()
    hour = number(raw_hour)
    minute = int(colon_minute) if colon_minute else {'一刻': 15, '三刻': 45, '半': 30}.get(spoken_minute)
    if minute is None:
        minute = number(spoken_minute.rstrip('分')) if spoken_minute else 0
    if not 0 <= hour <= 23 or not 0 <= minute <= 59 or (period and hour > 12):
        return ReminderRequest(content, clarification='这个钟点不明确，请用有效的日期和时间重新告诉我；这条提醒还没有设置。')
    local = datetime.fromtimestamp(created, ZONE)
    date = local.date() + timedelta(days={'今天': 0, '明天': 1, '后天': 2, None: 0}[day])
    if period == '晚上' and hour == 12:
        date += timedelta(days=1)
        hour = 0
    elif period in ('下午', '晚上', '傍晚'):
        hour = hour % 12 + 12
    elif period == '中午':
        hour = hour + 12 if hour < 11 else hour
    elif period:
        hour = hour if period == '上午' and hour == 12 else hour % 12
    elif day in ('明天', '后天') and 0 < hour < 12:
        return ReminderRequest(content, clarification=f'你说的{day}{hour}点是上午还是下午？请把时段补进原请求再发一次，例如“{day}下午{hour}点提醒我{content}”。这条提醒还没有设置。')
    hours = [hour]
    if not period and 0 < hour < 12:
        hours += [hour + 12]
    candidates = [datetime(date.year, date.month, date.day, h, minute, tzinfo=ZONE).timestamp() for h in hours]
    future = [at for at in candidates if at > created]
    if not future:
        return ReminderRequest(content, clarification='今天这个时间已经过了。你是希望明天提醒，还是换一个时间？这条提醒还没有设置。')
    return ReminderRequest(content, min(future))
