"""Shared assistant addressing; quoted text never becomes an invocation."""
import re
from .persona import names_for


def unquoted_text(text):
    lines = []
    fenced = False
    for line in (text or '').splitlines(keepends=True):
        if line.lstrip().startswith('```'):
            fenced = not fenced
            lines.append(' ' * len(line))
        elif fenced or line.lstrip().startswith(('>', '引用', '转发')):
            lines.append(' ' * len(line))
        else:
            lines.append(line)
    value = ''.join(lines)
    # Retain offsets so removing an actual address never changes quoted facts.
    return re.sub(r'“[^”]*(?:”|$)|「[^」]*(?:」|$)|『[^』]*(?:』|$)|"[^"\n]*"|`[^`\n]*`', lambda m: ' ' * len(m[0]), value)


def mention_pattern(name):
    names = '|'.join(re.escape(n) for n in names_for(name))
    boundary = r'(?=$|[\s，。！？,:：!?、；;（）()]|帮|请|给|查|预|订|挂|提醒|记住|记下|我|你|能|把|取消|今天|明天|你好|谢谢|安排|整理|解释|看看|找|早上|晚上|识别|识图|处理|分析|总结|生成|翻译|读|来|说|推荐|辛苦|在吗)'
    return re.compile(r'(?<![a-zA-Z0-9_@＠])[@＠](?:' + names + r')' + boundary)


def direct_mention(text, name):
    clean = unquoted_text(text)
    names = '|'.join(re.escape(n) for n in names_for(name))
    return bool(mention_pattern(name).search(clean) or re.match(r'^\s*(?:' + names + r')(?=\s|[，。！？,:：!?]|$)', clean))


def strip_assistant_address(text, name):
    clean = unquoted_text(text)
    spans = [m.span() for m in mention_pattern(name).finditer(clean)]
    for start, end in reversed(spans):
        text = text[:start] + text[end:]
    names = '|'.join(re.escape(n) for n in names_for(name))
    # Bare names are addresses only at the beginning.
    text = re.sub(r'^\s*(?:' + names + r')(?=\s|[，。！？,:：!?]|$)[\s，,:：]*', '', text)
    return text.strip()
