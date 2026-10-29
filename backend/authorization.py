"""Narrow grants from explicit source commands, independent of model guesses."""
import re
from .contracts import ActionGrant
from .persona import names_for


def command_grants(text, agent_name, created):
    names = '|'.join(re.escape(name) for name in names_for(agent_name))
    text = re.sub(r'^\s*@?(?:' + names + r')(?=\s|[，。！？,:：!?]|$)[\s，,:：]*', '', text).strip()
    text = re.sub(r'^(?:请帮我|帮我|请)\s*', '', text)
    # Only unambiguous, supported commands grant side effects. Other phrasing
    # may be answered with instructions to use the explicit task/reminder form.
    if text.startswith(('记住', '记下')):
        content = text[2:].lstrip(' ：:')
        if content:
            return [ActionGrant('remember', {'content': content}).data()]
    m = re.fullmatch(r'(?:添加|创建|新增)待办[：:]\s*(.+)', text, re.S)
    if m:
        return [ActionGrant('family_tasks', {'action': 'create', 'title': m[1].strip()}).data()]
    m = re.fullmatch(r'完成待办[：:]\s*([\w-]+)', text)
    if m:
        return [ActionGrant('family_tasks', {'action': 'complete', 'key': m[1]}).data()]
    m = re.fullmatch(r'(\d+|一|两|二|三|五|十)(分钟|小时|天)后提醒(?:我们|我)?[：:，,\s]*(.+)', text, re.S)
    if m:
        count = int(m[1]) if m[1].isdigit() else {'一': 1, '两': 2, '二': 2, '三': 3, '五': 5, '十': 10}[m[1]]
        at = created + count * {'分钟': 60, '小时': 3600, '天': 86400}[m[2]]
        return [ActionGrant('group_reminder', {'content': m[3].strip(), 'at': at}).data()]
    return []


def permitted(grants, name, args):
    return any(g['tool'] == name and g['arguments'] == args for g in grants)
