"""Text context selection; attachments retain their existing transport path."""
import json


def text_size(message):
    content = message.get('content') or ''
    if isinstance(content, str):
        return len(content)
    return sum(len(b.get('text', '')) for b in content if b.get('type') == 'text')


def bounded_context(messages, budget=24000):
    if len(messages) < 2:
        return messages
    mandatory = text_size(messages[0]) + text_size(messages[-1])
    if mandatory > budget:
        raise ValueError('当前消息与系统规则超过上下文预算，请缩短消息')
    remaining = budget - mandatory
    selected = [messages[-1]]
    # Preserve complete turns, identities, provenance and negations.
    for message in reversed(messages[1:-1]):
        cost = text_size(message)
        if cost <= remaining:
            selected.append(message)
            remaining -= cost
    return [messages[0], *reversed(selected)]


def fit_sections(prompt, source_size, sections, budget=24000):
    remaining = budget - len(prompt) - source_size
    if remaining < 0:
        raise ValueError('当前消息与系统规则超过上下文预算，请缩短消息')
    for label, value in sections:
        part = '\n' + label + '：' + json.dumps(value, ensure_ascii=False)
        if len(part) <= min(remaining // 2, 6000):
            prompt += part
            remaining -= len(part)
    return prompt


def tool_content(result, max_chars=8000):
    content = json.dumps(result, ensure_ascii=False)
    if len(content) <= max_chars:
        return content
    return json.dumps({'result_stored': True, 'message': '结果超过上下文预算，完整结果保存在工具执行记录中，请缩小查询范围。'}, ensure_ascii=False)


def analysis_payload(waiting, memories, names, messages, budget=24000):
    selected = [messages[-1]] if messages else []
    payload = {'waiting': [], 'known_memories': [], 'members': names, 'messages': selected}
    remaining = budget - len(json.dumps(payload, ensure_ascii=False))
    if remaining < 0:
        raise ValueError('最新消息超过分析预算')
    for key, values in [('waiting', waiting[-10:]), ('known_memories', memories[-20:])]:
        for value in values:
            cost = len(json.dumps(value, ensure_ascii=False))
            if cost <= min(remaining // 2, 6000):
                payload[key].append(value)
                remaining -= cost
    for value in reversed(messages[:-1]):
        cost = len(json.dumps(value, ensure_ascii=False))
        if cost <= remaining:
            selected.insert(0, value)
            remaining -= cost
    return payload
