"""Validate narrow command confirmations against the immediate conversation turn."""
import re
from .authorization import command_grants


def confirmed_command(candidate, messages, agent_name):
    if not isinstance(candidate, str) or len(messages) < 3:
        return None
    user, suggestion, reply = messages[-3:]
    if suggestion['sender'] != 0 or user['sender'] != reply['sender'] or reply['sender'] == 0:
        return None
    age = reply.get('created', 0) - suggestion.get('created', 0)
    if not 0 <= age <= 1800:
        return None
    if not re.fullmatch(r'\s*(?:好的?|可以|行|嗯|同意|就这样办|帮我执行|执行吧)[呀啊吧呢。！!，,\s]*', reply['text']):
        return None
    if not candidate.strip() or candidate not in suggestion['text']:
        return None
    if not command_grants(candidate, agent_name, reply.get('created', 0)):
        return None
    return candidate
