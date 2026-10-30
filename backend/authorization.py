"""Narrow grants from explicit source commands, independent of model guesses."""
import re
from .contracts import ActionGrant
from .persona import names_for
from .reminder_language import reminder_request


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
    reminder = reminder_request(text, agent_name, created)
    if reminder and reminder.at is not None:
        return [ActionGrant('group_reminder', {'content': reminder.content.strip(), 'at': reminder.at}).data()]
    return []


def permitted(grants, name, args):
    return any(g['tool'] == name and g['arguments'] == args for g in grants)
